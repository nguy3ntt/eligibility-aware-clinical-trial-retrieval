"""Offline contract tests. All case/trial text below is invented for tests."""

import json
from pathlib import Path

import httpx
import pytest

from pipelines import inspection
from pipelines.connectors import snapshots, trec
from pipelines.connectors.clinicaltrials import fetch_trials
from pipelines.connectors.snapshots import Snapshot, fetch_bytes, sha256, verify_snapshot
from pipelines.connectors.trec import (
    SourceValidationError,
    load_qrels,
    load_topics,
    select_trial_ids,
)
from pipelines.inspection import ABSENT, acquire, field_value, inventory, profile, state

TOPICS = b"""<topics task="2022 TREC Clinical Trials">
<topic number="1">  SYNTHETIC TEST CASE: adult; age not supplied.  </topic>
<topic number="2">SYNTHETIC TEST CASE: no medical history supplied.</topic>
</topics>"""
QRELS = b"1 0 NCT00000001 0\n1 0 NCT00000002 1\n2 0 NCT00000003 2\n"


def trial(trial_id: str) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": trial_id, "briefTitle": "SYNTHETIC TEST TRIAL"},
            "eligibilityModule": {
                "healthyVolunteers": False,
                "minimumAge": "18 Years",
                "eligibilityCriteria": (
                    "Inclusion Criteria:\n* SYNTHETIC test\nExclusion Criteria:\n* Test"
                ),
            },
            "designModule": {"enrollmentInfo": {"count": 0}},
        }
    }


def source_client(*, missing: str | None = None, bad_topics: bytes | None = None) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("topics2022.xml"):
            return httpx.Response(200, content=bad_topics if bad_topics is not None else TOPICS)
        if request.url.path.endswith("qrels2022.txt"):
            return httpx.Response(200, content=QRELS)
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"apiVersion": "test", "dataTimestamp": "test-frozen"})
        assert request.url.path.endswith("/studies")
        ids = request.url.params["filter.ids"].split(",")
        return httpx.Response(200, json={"studies": [trial(i) for i in ids if i != missing]})

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_topics_preserve_synthetic_text_and_provenance() -> None:
    topics = load_topics(TOPICS)
    assert topics[0]["text"] == "  SYNTHETIC TEST CASE: adult; age not supplied.  "
    assert topics[0]["synthetic"] is True
    assert topics[0]["case_id"] == "trec-ct-2022:1"
    assert topics[0]["source_locator"] == "/topics/topic[@number='1']"


@pytest.mark.parametrize(
    "raw",
    [
        b"not XML",
        b"<topics/>",
        b'<topics task="2022 TREC Clinical Trials"/>',
        TOPICS.replace(b'number="2"', b'number="1"'),
        TOPICS.replace(b'number="2"', b'number="0"'),
        b'<!DOCTYPE topics [<!ENTITY x "text">]>' + TOPICS,
        TOPICS.replace(b"SYNTHETIC TEST CASE: no medical history supplied.", b" "),
    ],
)
def test_bad_topics_are_rejected_without_narrative_logging(raw: bytes) -> None:
    with pytest.raises(SourceValidationError) as caught:
        load_topics(raw)
    assert "SYNTHETIC TEST CASE" not in str(caught.value.issues)


def test_stale_header_exception_requires_exact_inspected_bytes(monkeypatch) -> None:
    stale = TOPICS.replace(b"2022 TREC", b"2021 TREC")
    assert len(trec.KNOWN_2022_LEGACY_HEADER_SHA256) == 64
    with pytest.raises(SourceValidationError):
        load_topics(stale)
    monkeypatch.setattr(trec, "KNOWN_2022_LEGACY_HEADER_SHA256", sha256(stale))
    assert load_topics(stale)[0]["source_warning"] == "known_2022_file_with_2021_header"
    with pytest.raises(SourceValidationError):
        load_topics(stale + b" ")


@pytest.mark.parametrize(
    "bad,reason",
    [
        (b"1 0 NCT00000001", "expected four columns"),
        (b"9 0 NCT00000001 0", "unknown topic"),
        (b"1 0 NCT1 0", "invalid iteration, NCT ID, or label"),
        (b"1 0 NCT00000001 3", "invalid iteration, NCT ID, or label"),
        (b"1 Q0 NCT00000001 0", "invalid iteration, NCT ID, or label"),
        (b"1 0 NCT00000001 2", "duplicate topic/trial judgment"),
    ],
)
def test_qrel_validation_retains_line_numbers(bad: bytes, reason: str) -> None:
    with pytest.raises(SourceValidationError) as caught:
        load_qrels(QRELS + bad, {"1", "2"})
    assert caught.value.issues == [{"source": "qrels", "line": 4, "reason": reason}]


def test_qrels_preserve_labels_and_report_all_errors() -> None:
    assert [r["grade"] for r in load_qrels(QRELS, {"1", "2"})] == [0, 1, 2]
    with pytest.raises(SourceValidationError) as caught:
        load_qrels(b"bad\nwrong\n", {"1"})
    assert len(caught.value.issues) == 2


def test_selection_is_unique_bounded_and_order_independent() -> None:
    rows = load_qrels(QRELS, {"1", "2"})
    selected = select_trial_ids(rows, 2, "test-seed")
    assert selected == select_trial_ids(list(reversed(rows)) + rows, 2, "test-seed")
    assert len(set(selected)) == 2
    for limit in [0, 1001, 4]:
        with pytest.raises(ValueError):
            select_trial_ids(rows, limit, "test-seed")


@pytest.mark.parametrize(
    "value,expected,result",
    [
        (ABSENT, str, "absent"),
        (None, str, "null"),
        (" ", str, "empty"),
        ([], list, "empty"),
        (False, bool, "present"),
        (0, int, "present"),
        (True, int, "wrong_type"),
        ("18 Years", str, "present"),
        (18, str, "wrong_type"),
    ],
)
def test_missingness_never_conflates_false_zero_or_unknown(value, expected, result) -> None:
    assert state(value, expected) == result


def test_malformed_parent_is_not_silently_counted_as_missing() -> None:
    study = {"protocolSection": {"eligibilityModule": []}}
    assert state(field_value(study, "eligibilityModule.sex"), str) == "wrong_type"
    assert state(field_value(study, "missingModule.sex"), str) == "absent"


def test_inventory_counts_paths_once_per_record_without_values() -> None:
    observed = inventory({"items": [{"x": 1}, {"x": "SYNTHETIC SECRET"}]})
    assert observed["/items/[]/x"] == {"int", "str"}
    assert "SYNTHETIC SECRET" not in str(observed)


def test_acquisition_and_offline_replay_are_auditable_and_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    with source_client() as client:
        acquire(root, 3, "test", client)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    report = profile(root, tmp_path / "first")
    profile(root, tmp_path / "second")
    assert report["received_trials"] == 3
    assert report["qrels_with_current_trial"] == 3
    assert report["historical_trial_records_loaded"] == 0
    assert report["human_reviews_completed"] == 0
    assert report["fields"]["maximum_age"]["absent"] == 3
    assert report["fields"]["healthy_volunteers"]["present"] == 3
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    for path in (tmp_path / "first").iterdir():
        assert path.read_bytes() == (tmp_path / "second" / path.name).read_bytes()
    pairs = [
        json.loads(line) for line in (tmp_path / "first/pair-review.jsonl").read_text().splitlines()
    ]
    assert {p["grade"] for p in pairs} == {0, 1, 2}
    for pair in pairs:
        assert pair["system_eligibility_assessment"] is None
        assert pair["benchmark_comparable"] is False
        source = pair["current_trial_source"]
        assert sha256((root / source["file"]).read_bytes()) == source["sha256"]


def test_missing_current_trial_is_recorded_without_inventing_evidence(tmp_path: Path) -> None:
    with source_client(missing="NCT00000002") as client:
        acquire(tmp_path / "raw", 3, "test", client)
    report = profile(tmp_path / "raw", tmp_path / "out")
    assert report["missing_requested_ids"] == ["NCT00000002"]
    assert report["qrels_missing_from_api"] == 1
    assert report["validation_issues"] == 1


def test_unselected_qrels_remain_traceable_as_outside_sample(tmp_path: Path) -> None:
    with source_client() as client:
        acquire(tmp_path / "raw", 1, "test", client)
    report = profile(tmp_path / "raw", tmp_path / "out")
    assert report["qrels_outside_sample"] == 2
    assert report["qrels_missing_from_api"] == 0


def test_failed_acquisition_keeps_raw_and_issue_manifest(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    with (
        source_client(bad_topics=b"invalid XML") as client,
        pytest.raises(SourceValidationError),
    ):
        acquire(root, 1, "test", client)
    assert (root / "topics2022.xml").read_bytes() == b"invalid XML"
    assert json.loads((root / "manifest.json").read_bytes())["status"] == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        verify_snapshot(root)
    with pytest.raises(FileExistsError):
        Snapshot(root)


def test_checksum_tampering_blocks_profile(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    with source_client() as client:
        acquire(root, 3, "test", client)
    # Deliberate corruption of a disposable test fixture, never an actual source snapshot.
    (root / "ctgov-001.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="checksum"):
        profile(root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"studies": [trial("NCT00000009")]},
        {"studies": [{}]},
        {"studies": [trial("NCT00000001"), trial("NCT00000001")]},
    ],
)
def test_malformed_and_unrequested_trials_are_not_silently_dropped(tmp_path, payload) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        issues = fetch_trials(client, Snapshot(tmp_path / "raw"), ["NCT00000001", "NCT00000002"])
    assert any("source" in issue for issue in issues)


def test_full_page_cursor_is_harmless_when_all_explicit_ids_arrived(tmp_path) -> None:
    payload = {"studies": [trial("NCT00000001")], "nextPageToken": "terminal-cursor"}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        assert fetch_trials(client, Snapshot(tmp_path / "raw"), ["NCT00000001"]) == []


def test_incomplete_pagination_is_rejected_instead_of_scanning_corpus(tmp_path) -> None:
    payload = {"studies": [], "nextPageToken": "unexpected"}
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client,
        pytest.raises(SourceValidationError),
    ):
        fetch_trials(client, Snapshot(tmp_path / "raw"), ["NCT00000001"])


def test_changed_api_version_invalidates_snapshot(tmp_path) -> None:
    versions = iter(["first", "changed"])
    base = source_client()

    def respond(request):
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"apiVersion": "test", "dataTimestamp": next(versions)})
        return base.send(request)

    with (
        base,
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(ValueError, match="changed during acquisition"),
    ):
        acquire(tmp_path / "raw", 1, "test", client)
    assert json.loads((tmp_path / "raw/manifest.json").read_bytes())["status"] == "failed"


def test_transient_http_retry_and_permanent_error(monkeypatch) -> None:
    sleeps = []
    monkeypatch.setattr(snapshots.time, "sleep", sleeps.append)
    statuses = iter([429, 503, 200])
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(next(statuses), content=b"ok"))
    ) as client:
        body, metadata = fetch_bytes(client, "https://example.test")
    assert body == b"ok" and metadata["attempts"] == 3
    assert sleeps == [1, 2]
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        fetch_bytes(client, "https://example.test")
    assert sleeps == [1, 2]


def test_response_size_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(snapshots, "MAX_RESPONSE_BYTES", 4)
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"12345"))
        ) as client,
        pytest.raises(ValueError, match="bound"),
    ):
        fetch_bytes(client, "https://example.test")


def test_placeholder_eligibility_is_flagged_without_claiming_usable_criteria(tmp_path) -> None:
    base = source_client()

    def respond(request):
        if request.url.path.endswith("/studies"):
            ids = request.url.params["filter.ids"].split(",")
            records = [trial(i) for i in ids]
            for record in records:
                record["protocolSection"]["eligibilityModule"]["eligibilityCriteria"] = (
                    "No eligibility criteria"
                )
            return httpx.Response(200, json={"studies": records})
        return base.send(request)

    with base, httpx.Client(transport=httpx.MockTransport(respond)) as client:
        acquire(tmp_path / "raw", 1, "test", client)
    report = profile(tmp_path / "raw", tmp_path / "out")
    assert report["fields"]["eligibility_text"]["present"] == 1
    assert len(report["eligibility_placeholder_records"]) == 1
    assert report["human_reviews_completed"] == 0


def test_cli_rejects_path_traversal(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["inspection", "fetch", "--run-id", "../escape"])
    with pytest.raises(SystemExit) as caught:
        inspection.main()
    assert caught.value.code == 2
