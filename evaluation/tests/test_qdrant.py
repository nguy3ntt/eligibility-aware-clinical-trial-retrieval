"""Offline failures plus opt-in real-server exact-search and persistence contracts."""

# ruff: noqa: E402
import copy
import json
import os
from uuid import uuid4

import httpx
import pytest

np = pytest.importorskip("numpy")

from dataclasses import asdict

from backend.app.repositories.qdrant import QdrantRepository, compatibility_filter, point_id
from pipelines.embeddings import MODELS
from pipelines.indexing import qdrant as indexing
from pipelines.indexing.qdrant import make_point, payload_matches, verify_import


def fixture_data():
    contract = {"dimension": 3, "documents": 5, "artifact_sha256": "a" * 64}
    metadata = [
        {"sex": "Male", "minimum_age": "18 Years", "maximum_age": "70 Years"},
        {"sex": "Female"},
        {"sex": "Unknown", "minimum_age": "N/A"},
        {"sex": None, "minimum_age": "71 Years"},
        {"maximum_age": "69 Years"},
    ]
    vectors = np.array([[1, 0, 0], [0.8, 0.6, 0], [0.6, 0.8, 0], [0, 1, 0], [-1, 0, 0]])
    points = [
        make_point(
            {
                "trial_id": f"NCT{i:08d}",
                "filter_metadata": meta,
                "representations": {"title_conditions": "Invented trial"},
                "source": {"archive": "synthetic-fixture"},
                "content_sha256": "b" * 64,
            },
            vec,
            contract,
        )
        for i, (meta, vec) in enumerate(zip(metadata, vectors, strict=True), 1)
    ]
    return contract, points


def test_payload_provenance_unknowns_and_stable_identifiers():
    _, points = fixture_data()
    assert points[0]["id"] == point_id("NCT00000001")
    assert len({p["id"] for p in points}) == 5
    assert points[2]["payload"]["filter_metadata"]["sex"] == "Unknown"
    assert "sex" not in points[2]["payload"]
    assert "minimum_age_days" not in points[2]["payload"]
    assert points[0]["payload"]["eligibility_assessment"] == "not_performed"
    with pytest.raises(ValueError, match="NCT"):
        point_id("../../trial")


def test_float_round_trip_tolerance_does_not_hide_changed_evidence():
    expected = {"maximum_age_days": 25566.975000000002, "filter_metadata": {"sex": None}}
    actual = {**expected, "maximum_age_days": 25566.975}
    assert payload_matches(actual, expected)
    assert not payload_matches({**actual, "maximum_age_days": 25567}, expected)
    assert not payload_matches({**actual, "filter_metadata": {"sex": "All"}}, expected)
    assert not payload_matches({**actual, "maximum_age_days": float("nan")}, expected)
    assert not payload_matches({}, expected)


@pytest.mark.parametrize(
    "metadata",
    [
        {"minimum_age": 18},
        {"minimum_age": "80 Years", "maximum_age": "70 Years"},
        {"minimum_age": "9" * 400 + " Years"},
    ],
)
def test_malformed_metadata_rejected_before_import(metadata):
    row = {
        "trial_id": "NCT00000001",
        "filter_metadata": metadata,
        "representations": {"title_conditions": "Invented"},
        "source": {},
        "content_sha256": "a" * 64,
    }
    with pytest.raises(ValueError):
        make_point(row, np.array([1, 0, 0]), {"artifact_sha256": "b" * 64})


def test_unsupported_artifact_fails_before_server_access(monkeypatch, tmp_path):
    manifest = {
        "encoder": {
            "model": asdict(MODELS["minilm"]),
            "normalization": "l2",
            "dtype": "float32",
            "prompt": "",
        },
        "dimension": 3,
    }
    monkeypatch.setattr(indexing, "load_index", lambda path: (manifest, [], np.zeros((0, 3))))

    class UnusedServer:
        def ensure_collection(self, contract):
            pytest.fail("invalid source reached server")

    with pytest.raises(ValueError, match="pinned"):
        indexing.import_index(UnusedServer(), tmp_path)
    for batch_size in (True, 1.5, 0, 129):
        with pytest.raises(ValueError, match="batch"):
            indexing.import_index(UnusedServer(), tmp_path, batch_size=batch_size)


@pytest.mark.parametrize("age", [-1, True, float("inf"), float("nan"), "70"])
def test_invalid_query_age_rejected(age):
    with pytest.raises(ValueError, match="age"):
        compatibility_filter({"age_days": age})


def test_missing_query_facts_add_no_constraints():
    assert compatibility_filter({}) == {}
    assert compatibility_filter({"sex": None, "age_days": None}) == {}
    with pytest.raises(ValueError, match="sex"):
        compatibility_filter({"sex": "unsupported"})


@pytest.mark.parametrize(
    "url", ["https://example.com", "http://127.0.0.1/a", "http://u:p@localhost"]
)
def test_nonlocal_or_credential_urls_rejected(url):
    with pytest.raises(ValueError, match="loopback"):
        QdrantRepository(url)


def test_contract_mismatch_refuses_all_writes():
    methods = []

    def handler(request):
        methods.append(request.method)
        body = (
            {"version": "1.19.0"}
            if request.url.path == "/"
            else {"status": "ok", "result": {"config": {"metadata": {}}}}
        )
        return httpx.Response(200, json=body)

    with (
        QdrantRepository(transport=httpx.MockTransport(handler)) as repo,
        pytest.raises(ValueError, match="different artifact"),
    ):
        repo.ensure_collection({"dimension": 3})
    assert set(methods) == {"GET"}


@pytest.mark.parametrize("status", ["acknowledged", "failed"])
def test_unfinished_write_not_reported_as_success(status):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"status": "ok", "result": {"status": status}})
    )
    with (
        QdrantRepository(transport=transport) as repo,
        pytest.raises(ValueError, match="not completed"),
    ):
        repo.upsert([])


def test_transport_error_and_wrong_server_version_visible():
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    with QdrantRepository(transport=transport) as repo, pytest.raises(httpx.HTTPStatusError):
        repo.count()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"version": "1.18.0"}))
    with (
        QdrantRepository(transport=transport) as repo,
        pytest.raises(ValueError, match="1.19.0"),
    ):
        repo.version()


def test_search_sends_exact_named_vector_with_artifact_filter():
    contract, _ = fixture_data()
    requests = []

    def handler(request):
        if request.method == "GET":
            result = {
                "config": {
                    "metadata": {"retrieval_contract": contract},
                    "params": {"vectors": {"overview_dense": {"size": 3, "distance": "Cosine"}}},
                }
            }
        else:
            requests.append(json.loads(request.content))
            result = {"points": []}
        return httpx.Response(200, json={"status": "ok", "result": result})

    with QdrantRepository(transport=httpx.MockTransport(handler)) as repo:
        assert repo.search([1, 0, 0], contract) == []
        for bad in ([2, 0, 0], [float("nan"), 0, 0], [1, 0]):
            with pytest.raises(ValueError, match="vector"):
                repo.search(bad, contract)
        for k in (True, 1.5, 0, 101):
            with pytest.raises(ValueError, match="top-k"):
                repo.search([1, 0, 0], contract, k=k)
    assert requests[0]["params"] == {"exact": True}
    assert requests[0]["using"] == "overview_dense"
    assert requests[0]["filter"]["must"][0]["match"]["value"] == "a" * 64


def test_real_server_import_resume_filters_and_roundtrip():
    url = os.environ.get("QDRANT_TEST_URL")
    if not url:
        pytest.skip("set QDRANT_TEST_URL for an isolated live-server integration test")
    contract, points = fixture_data()
    name = "test_" + uuid4().hex[:12]
    with QdrantRepository(url, name) as repo:
        try:
            repo.ensure_collection(contract)
            repo.upsert(points[:2])
            with pytest.raises(ValueError, match="count"):
                verify_import(repo, points, contract)
            repo.ensure_collection(contract)
            repo.upsert(points)
            assert verify_import(repo, points, contract)["points"] == 5
            repo.upsert(points)
            assert repo.count() == 5
            wrong = {**contract, "artifact_sha256": "c" * 64}
            with pytest.raises(ValueError, match="different artifact"):
                repo.ensure_collection(wrong)
            hits = repo.search([1, 0, 0], contract, k=10)
            assert [p["payload"]["trial_id"] for p in hits] == [f"NCT{i:08d}" for i in range(1, 6)]
            assert [p["score"] for p in hits] == pytest.approx([1, 0.8, 0.6, 0, -1], abs=1e-6)
            # Exact upper boundary survives; opposite sex and out-of-range ages do not.
            hits = repo.search(
                [1, 0, 0], contract, k=10, demographics={"age_days": 70 * 365.2425, "sex": "Male"}
            )
            assert [p["payload"]["trial_id"] for p in hits] == ["NCT00000001", "NCT00000003"]
            hits = repo.search(
                [1, 0, 0], contract, k=10, demographics={"age_days": 18 * 365.2425, "sex": "Male"}
            )
            assert "NCT00000001" in [p["payload"]["trial_id"] for p in hits]
            changed = copy.deepcopy(points[0])
            changed["payload"]["title"] = "Altered evidence"
            repo.upsert([changed])
            with pytest.raises(ValueError, match="payload"):
                verify_import(repo, points, contract)
            repo.upsert(points)
            assert verify_import(repo, points, contract)["status"] == "verified"
            changed = copy.deepcopy(points[0])
            changed["vector"]["overview_dense"] = [0, 1, 0]
            repo.upsert([changed])
            with pytest.raises(ValueError, match="vector"):
                verify_import(repo, points, contract)
        finally:
            # Only this test's randomly named collection is removed, never trials_v1.
            repo.request("DELETE", repo.path)
