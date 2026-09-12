import json
from datetime import date

import httpx
import pytest

from pipelines.incremental import acquire, load_registry, materialize, verify_acquisition

START, END = date(2021, 1, 1), date(2021, 1, 3)


def study(n=1, title="Invented trial"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": f"NCT90000{n:03d}", "briefTitle": title},
            "statusModule": {"lastUpdatePostDateStruct": {"date": "2021-01-02"}},
        }
    }


def client(pages, *, fail_page=None, changed_version=False):
    versions = 0

    def respond(request):
        nonlocal versions
        if request.url.path.endswith("/version"):
            versions += 1
            return httpx.Response(
                200,
                json={
                    "apiVersion": "invented",
                    "dataTimestamp": "changed" if changed_version and versions > 1 else "fixed",
                },
            )
        page = int(request.url.params.get("pageToken", "0"))
        if page == fail_page:
            return httpx.Response(400)
        assert (
            request.url.params["query.term"]
            == "AREA[LastUpdatePostDate]RANGE[2021-01-01,2021-01-03]"
        )
        return httpx.Response(200, json=pages[page])

    return httpx.Client(transport=httpx.MockTransport(respond))


def fetch(tmp_path, pages, **kwargs):
    root = tmp_path / "raw"
    acquire(client(pages), root, start=START, until=END, scope=[], **kwargs)
    return root


def test_changed_unchanged_added_and_absence_is_not_deletion(tmp_path):
    first = fetch(tmp_path, [{"studies": [study(1), study(2)]}])
    a = tmp_path / "a"
    assert materialize(first, a)["counts"] == {"added": 2, "changed": 0, "unchanged": 0}
    second = tmp_path / "second"
    acquire(
        client([{"studies": [study(1, "Changed invented title"), study(3)]}]),
        second,
        start=START,
        until=END,
        scope=[],
    )
    b = tmp_path / "b"
    result = materialize(second, b, a)
    assert result["counts"] == {"added": 1, "changed": 1, "unchanged": 0}
    assert result["records"] == 3 and result["active_catalog_changed"] is False
    assert materialize(second, tmp_path / "replay", b)["counts"]["unchanged"] == 2
    assert load_registry(b)[1]["NCT90000002"]["study"] == study(2)


def test_resume_uses_verified_committed_page_and_completes_cursor_chain(tmp_path):
    root = tmp_path / "raw"
    pages = [{"studies": [study(1)], "nextPageToken": "1"}, {"studies": [study(2)]}]
    with pytest.raises(httpx.HTTPStatusError):
        acquire(client(pages, fail_page=1), root, start=START, until=END, scope=[])
    assert not (root / "manifest.json").exists()
    result = acquire(client(pages), root, start=START, until=END, scope=[], resume=True)
    assert result["records"] == 2 and verify_acquisition(root) == result
    payload = root / result["pages"][0]["source"]["path"]
    payload.write_bytes(b"corrupted")
    with pytest.raises(ValueError):
        verify_acquisition(root)


@pytest.mark.parametrize(
    "pages",
    [
        [{"studies": [study(1), study(1)]}],
        [{"studies": [{"protocolSection": {}}]}],
        [
            {"studies": [study(1)], "nextPageToken": "1"},
            {"studies": [study(2)], "nextPageToken": "1"},
        ],
        [{"studies": [], "nextPageToken": "1"}],
    ],
)
def test_invalid_records_or_cursors_never_publish_completion(tmp_path, pages):
    with pytest.raises(ValueError):
        fetch(tmp_path, pages)
    assert not (tmp_path / "raw" / "manifest.json").exists()
    assert list((tmp_path / "raw").glob("failure-*.json"))


def test_registry_revision_change_and_budget_exhaustion_do_not_advance_watermark(tmp_path):
    with pytest.raises(ValueError, match="registry changed"):
        acquire(
            client([{"studies": [study()]}], changed_version=True),
            tmp_path / "changed",
            start=START,
            until=END,
            scope=[],
        )
    with pytest.raises(ValueError, match="budget exhausted"):
        fetch(tmp_path, [{"studies": [study()], "nextPageToken": "1"}], max_pages=1)


def test_gap_in_incremental_history_is_rejected(tmp_path):
    first = fetch(tmp_path, [{"studies": [study()]}])
    previous = tmp_path / "previous"
    materialize(first, previous)
    m = json.loads((previous / "manifest.json").read_bytes())
    m["watermark"] = "2020-12-01"
    (previous / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="overlapping"):
        materialize(first, tmp_path / "next", previous)


@pytest.mark.parametrize("mutation", ["query", "intent", "terminal"])
def test_snapshot_verification_rejects_changed_contract(tmp_path, mutation):
    root = fetch(tmp_path, [{"studies": [study()]}])
    path = root / "manifest.json"
    m = json.loads(path.read_bytes())
    if mutation == "query":
        m["pages"][0]["params"]["sort"] = "invented"
    elif mutation == "intent":
        m["until"] = "2021-01-04"
    else:
        m["pages"].append(m["pages"][0])
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        verify_acquisition(root)


def test_older_record_cannot_replace_newer_registry_evidence(tmp_path):
    first = fetch(tmp_path, [{"studies": [study()]}])
    previous = tmp_path / "previous"
    materialize(first, previous)
    older = study(title="Older invented record")
    older["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2021-01-01"
    second = tmp_path / "second"
    acquire(client([{"studies": [older]}]), second, start=START, until=END, scope=[])
    with pytest.raises(ValueError, match="regressed"):
        materialize(second, tmp_path / "next", previous)
    assert not (tmp_path / "next" / "manifest.json").exists()
