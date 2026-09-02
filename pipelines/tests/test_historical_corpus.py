"""Offline historical-corpus gate tests using tiny public-schema synthetic trials."""

import json
import zipfile
from pathlib import Path

import httpx
import pytest

from pipelines import historical_corpus
from pipelines.connectors.snapshots import sha256
from pipelines.connectors.trec_corpus import (
    ARCHIVES,
    CONTENTS_MEMBER,
    ArchiveSpec,
    acquire_archives,
    validate_corpus,
    verify_archive_snapshot,
)

MODIFIED = "Wed, 28 Apr 2021 20:55:58 GMT"
CONTENTS = (
    b"All 375,580 studies in XML format\r\n"
    b"  Studies grouped by leading part of NCT Id\r\n"
    b"  Studies published on April 26, 2021\r\n"
)


def trial_xml(trial_id: str) -> bytes:
    return f"""<clinical_study>
<id_info><nct_id>{trial_id}</nct_id></id_info>
<brief_title>SYNTHETIC TEST TRIAL</brief_title>
<brief_summary><textblock>Invented public trial fixture.</textblock></brief_summary>
<condition>Invented condition</condition>
<eligibility><criteria><textblock>Invented criterion.</textblock></criteria>
<gender>All</gender><minimum_age>18 Years</minimum_age></eligibility>
</clinical_study>""".encode()


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    import io

    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in entries.items():
            bundle.writestr(name, raw)
    return target.getvalue()


def archive_client(payloads: dict[str, bytes]) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = payloads[Path(request.url.path).name]
        range_header = request.headers.get("range")
        if range_header:
            offset = int(range_header.removeprefix("bytes=").removesuffix("-"))
            return httpx.Response(
                206,
                content=payload[offset:],
                headers={
                    "last-modified": MODIFIED,
                    "content-range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}",
                },
            )
        return httpx.Response(200, content=payload, headers={"last-modified": MODIFIED})

    return httpx.Client(transport=httpx.MockTransport(respond))


def acquire_fixture(root: Path, payloads: dict[str, bytes]) -> tuple[ArchiveSpec, ...]:
    specs = tuple(ArchiveSpec(name, len(raw), MODIFIED) for name, raw in payloads.items())
    with archive_client(payloads) as client:
        acquire_archives(root, client, archives=specs)
    return specs


def test_download_resumes_then_publishes_immutable_snapshot(tmp_path: Path) -> None:
    payload = zip_bytes({"NCT00000001.xml": trial_xml("NCT00000001")})
    name = "fixture.zip"
    staging = tmp_path / "corpus.incomplete"
    staging.mkdir()
    (staging / f"{name}.part").write_bytes(payload[:17])
    spec = ArchiveSpec(name, len(payload), MODIFIED)
    with archive_client({name: payload}) as client:
        result = acquire_archives(tmp_path / "corpus", client, resume=True, archives=(spec,))
    assert result["status"] == "complete"
    assert not staging.exists()
    assert (tmp_path / "corpus" / name).read_bytes() == payload
    assert result["archives"][0]["resumed_from_bytes"] == 17
    with archive_client({name: payload}) as client, pytest.raises(FileExistsError):
        acquire_archives(tmp_path / "corpus", client, archives=(spec,))


def test_download_rejects_changed_source_metadata_and_keeps_failure(tmp_path: Path) -> None:
    payload = b"fixture"
    spec = ArchiveSpec("fixture.zip", len(payload), MODIFIED)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=payload,
                headers={"last-modified": "Thu, 29 Apr 2021 00:00:00 GMT"},
            )
        )
    )
    with client, pytest.raises(ValueError, match="timestamp changed"):
        acquire_archives(tmp_path / "corpus", client, archives=(spec,))
    failure = json.loads((tmp_path / "corpus.incomplete/manifest.json").read_bytes())
    assert failure["status"] == "failed"
    assert (tmp_path / "corpus.incomplete/fixture.zip.part").exists() is False


def test_validation_builds_provenance_index_and_confirms_qrel_coverage(tmp_path: Path) -> None:
    payloads = {
        "part1.zip": zip_bytes(
            {
                "NCT00000001.xml": trial_xml("NCT00000001"),
                "NCT00000002.xml": trial_xml("NCT00000002"),
            }
        ),
        "part2.zip": zip_bytes({"nested/NCT00000003.xml": trial_xml("NCT00000003")}),
    }
    acquire_fixture(tmp_path / "corpus", payloads)
    qrels = tmp_path / "qrels.txt"
    qrels.write_bytes(b"1 0 NCT00000001 0\n1 0 NCT00000002 1\n2 0 NCT00000003 2\n")
    report = validate_corpus(tmp_path / "corpus", tmp_path / "profile", qrels, expected_trials=3)
    assert report["status"] == "complete"
    assert report["trial_records"] == 3
    assert report["qrels"]["missing_from_corpus"] == 0
    assert report["eligibility_assessments_performed"] == 0
    assert report["benchmark_metrics_permitted"] is True
    rows = [
        json.loads(line)
        for line in (tmp_path / "profile/trial-index.jsonl").read_text().splitlines()
    ]
    assert {row["trial_id"] for row in rows} == {
        "NCT00000001",
        "NCT00000002",
        "NCT00000003",
    }
    assert all({"archive", "member", "crc32", "uncompressed_bytes"} <= row.keys() for row in rows)


def test_official_layout_accepts_only_the_checksummed_contents_metadata(tmp_path: Path) -> None:
    payloads = {archive.name: zip_bytes({}) for archive in ARCHIVES}
    payloads[ARCHIVES[0].name] = zip_bytes(
        {"ClinicalTrials.2021-04-27.part1/NCT00000001.xml": trial_xml("NCT00000001")}
    )
    payloads[ARCHIVES[-1].name] = zip_bytes({CONTENTS_MEMBER: CONTENTS})
    acquire_fixture(tmp_path / "corpus", payloads)
    qrels = tmp_path / "qrels.txt"
    qrels.write_bytes(b"1 0 NCT00000001 2\n")
    report = validate_corpus(tmp_path / "corpus", tmp_path / "profile", qrels, expected_trials=1)
    assert report["status"] == "complete"
    assert report["archive_contents_metadata"]["verified"] is True

    payloads[ARCHIVES[-1].name] = zip_bytes({CONTENTS_MEMBER: CONTENTS + b"changed"})
    acquire_fixture(tmp_path / "changed-corpus", payloads)
    changed = validate_corpus(
        tmp_path / "changed-corpus", tmp_path / "changed-profile", qrels, expected_trials=1
    )
    assert changed["status"] == "failed"
    assert "unexpected archive metadata content" in {issue["reason"] for issue in changed["issues"]}


def test_validation_records_unsafe_malformed_duplicate_and_missing_ids(tmp_path: Path) -> None:
    payloads = {
        "part1.zip": zip_bytes(
            {
                "NCT00000001.xml": trial_xml("NCT00000001"),
                "../NCT00000002.xml": trial_xml("NCT00000002"),
                "NCT00000003.xml": b"not XML",
            }
        ),
        "part2.zip": zip_bytes({"NCT00000001.xml": trial_xml("NCT00000001")}),
    }
    acquire_fixture(tmp_path / "corpus", payloads)
    qrels = tmp_path / "qrels.txt"
    qrels.write_bytes(b"1 0 NCT00000001 0\n1 0 NCT00000002 1\n")
    report = validate_corpus(tmp_path / "corpus", tmp_path / "profile", qrels, expected_trials=2)
    reasons = {issue["reason"] for issue in report["issues"]}
    assert report["status"] == "failed"
    assert report["benchmark_metrics_permitted"] is False
    assert "unsafe or unsupported archive member" in reasons
    assert "invalid XML" in reasons
    assert "duplicate NCT ID" in reasons
    assert "judged trial IDs missing from corpus" in reasons
    assert json.loads((tmp_path / "profile/manifest.json").read_bytes())["status"] == "failed"


def test_archive_checksum_tampering_and_cli_path_traversal_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {"part.zip": zip_bytes({"NCT00000001.xml": trial_xml("NCT00000001")})}
    acquire_fixture(tmp_path / "corpus", payloads)
    (tmp_path / "corpus/part.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_archive_snapshot(tmp_path / "corpus")

    monkeypatch.setattr("sys.argv", ["historical-corpus", "fetch", "--run-id", "../escape"])
    with pytest.raises(SystemExit) as caught:
        historical_corpus.main()
    assert caught.value.code == 2


def test_manifest_checksum_covers_downloaded_archive(tmp_path: Path) -> None:
    payloads = {"part.zip": zip_bytes({"NCT00000001.xml": trial_xml("NCT00000001")})}
    acquire_fixture(tmp_path / "corpus", payloads)
    manifest = verify_archive_snapshot(tmp_path / "corpus")
    assert manifest["archives"][0]["sha256"] == sha256(payloads["part.zip"])
    assert manifest["source_checksum_published"] is False
