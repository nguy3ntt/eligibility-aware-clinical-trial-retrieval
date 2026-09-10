"""HTTP contracts, privacy, evidence boundaries and bounded research behavior."""

import copy

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")
pytest.importorskip("numpy")

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repositories.postgres import ConflictError, digest
from backend.app.schemas.api import SearchRequest
from backend.app.services.application import ResearchService
from pipelines.rerank import demo_data


class MemoryStore:
    """Unit-test double only. Production has no in-memory or SQLite fallback."""

    catalog_id = "unit-catalog"

    def __init__(self):
        case, _, records = demo_data()
        self.data = {
            "cases": {case.case_id: case.model_dump(mode="json")},
            "trials": records,
            "operations": {},
        }
        self.manifest = {
            "schema_version": "api-catalog-v1",
            "contract": {},
            "case_hashes": {k: digest(v) for k, v in self.data["cases"].items()},
            "trial_hashes": {k: digest(v) for k, v in records.items()},
        }

    def catalog(self):
        return copy.deepcopy(self.manifest)

    def get(self, kind, key):
        return copy.deepcopy(self.data[kind].get(key))

    def page(self, kind, limit, offset):
        return {
            "limit": limit,
            "offset": offset,
            "total": len(self.data[kind]),
            "items": [
                {"id": k, "payload": copy.deepcopy(self.data[kind][k])}
                for k in sorted(self.data[kind])[offset : offset + limit]
            ],
        }

    def save_operation(self, key, kind, request, payload):
        if key in self.data["operations"] and self.data["operations"][key] != payload:
            raise ConflictError("conflict")
        self.data["operations"][key] = copy.deepcopy(payload)
        return payload


@pytest.fixture
def setup_api():
    store = MemoryStore()
    service = ResearchService(store, Settings(_env_file=None))
    with TestClient(create_app(service=service), base_url="http://localhost") as client:
        yield client, service, store


def test_defaults_and_openapi(setup_api):
    client, _, _ = setup_api
    request = SearchRequest(case_id="reranking-demo")
    assert (request.method, request.filter, request.fact_extractor, request.rerank) == (
        "dense",
        "age_sex",
        "legacy",
        False,
    )
    schema = client.get("/openapi.json").json()
    assert "SearchResponse" in schema["components"]["schemas"]
    assert "TrialAssessment" in schema["components"]["schemas"]
    assert "text" not in schema["components"]["schemas"]["SearchRequest"]["properties"]
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize(
    "trial_id,status",
    [
        ("NCT90009001", "insufficient_information"),
        ("NCT90009002", "potential_match"),
        ("NCT90009003", "likely_exclusion"),
    ],
)
def test_screening_and_persistent_replay(setup_api, trial_id, status):
    client, service, store = setup_api
    body = {"case_id": "reranking-demo", "trial_id": trial_id}
    first = client.post("/v1/screening", json=body)
    assert first.status_code == 200, first.text
    packet = first.json()
    assert packet["result"]["assessment"]["status"] == status
    assert packet["result"]["explanation"]["assessment"] == packet["result"]["assessment"]
    assert packet["replayed"] is False
    replay = client.post("/v1/screening", json=body).json()
    assert replay["operation_id"] == packet["operation_id"]
    assert replay["replayed"] is True
    assert replay["result"] == packet["result"]
    with TestClient(
        create_app(service=ResearchService(store, service.settings)), base_url="http://localhost"
    ) as restarted:
        assert restarted.post("/v1/screening", json=body).json()["replayed"] is True
    assert len(store.data["operations"]) == 1
    assert (
        client.get("/v1/experiments/" + packet["operation_id"]).json()["result"] == packet["result"]
    )


def test_catalog_lookup_and_pagination(setup_api):
    client, _, _ = setup_api
    assert client.get("/v1/cases").json()["total"] == 1
    assert client.get("/v1/trials?limit=2&offset=2").json()["items"][0]["trial_id"] == "NCT90009003"
    assert client.get("/v1/trials?offset=3").json()["items"] == []
    assert client.get("/v1/cases/reranking-demo").json()["case"]["synthetic"] is True
    assert client.get("/v1/trials/NCT90009002").json()["criteria"]["criteria"]
    assert client.get("/v1/cases/unknown").status_code == 404
    assert client.get("/v1/experiments/" + "0" * 64).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"case_id": "reranking-demo", "text": "PRIVATE_SENTINEL"},
        {"case_id": "reranking-demo", "top_k": 11},
        {"case_id": "reranking-demo", "top_k": True},
        {"case_id": "reranking-demo", "rerank_depth": 51},
        {"case_id": "reranking-demo", "method": "PRIVATE_SENTINEL"},
        {"case_id": "reranking-demo", "rerank": "true"},
        {"case_id": "PRIVATE_SENTINEL "},
    ],
)
def test_invalid_inputs_do_not_echo_values(setup_api, body, caplog):
    client, _, store = setup_api
    response = client.post("/v1/search", json=body)
    assert response.status_code == 422
    assert "PRIVATE_SENTINEL" not in response.text + caplog.text
    assert not store.data["operations"]


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "evil.example"},
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"origin": "http://[invalid"},
        {"host": "[invalid"},
    ],
)
def test_nonlocal_browser_requests_rejected(setup_api, headers):
    client, _, _ = setup_api
    response = client.get("/health", headers=headers)
    assert response.status_code == 403
    assert "evil.example" not in response.text


def test_oversize_and_malformed_bodies_are_private(setup_api):
    client, _, _ = setup_api
    assert client.post("/v1/search", content=b"x" * 17000).status_code == 413
    response = client.post("/v1/search", content=b'{"PRIVATE_SENTINEL":')
    assert response.status_code == 422
    assert "PRIVATE_SENTINEL" not in response.text


@pytest.mark.parametrize(
    "exception,status",
    [
        (RuntimeError("PRIVATE_SENTINEL"), 500),
        (ValueError("PRIVATE_SENTINEL"), 409),
        (httpx.ConnectError("PRIVATE_SENTINEL"), 503),
        (FileNotFoundError("PRIVATE_SENTINEL"), 503),
        (ConflictError("PRIVATE_SENTINEL"), 409),
    ],
)
def test_dependency_and_internal_errors_are_not_logged_or_reflected(
    setup_api, exception, status, caplog
):
    client, service, _ = setup_api

    def fail(*args):
        raise exception

    service.screening = fail
    result = client.post(
        "/v1/screening", json={"case_id": "reranking-demo", "trial_id": "NCT90009002"}
    )
    assert result.status_code == status
    assert "PRIVATE_SENTINEL" not in result.text + caplog.text


def test_corrupted_catalog_data_is_rejected(setup_api):
    client, _, store = setup_api
    store.data["cases"]["reranking-demo"]["text"] = "Changed synthetic text"
    assert client.get("/v1/cases/reranking-demo").status_code == 409


def test_busy_gate_and_unknown_case_leave_no_saved_result(setup_api):
    client, service, store = setup_api
    with service.lock:
        assert client.post("/v1/search", json={"case_id": "reranking-demo"}).status_code == 429
    assert client.post("/v1/search", json={"case_id": "unknown"}).status_code == 404
    assert not store.data["operations"]


def test_named_experiment_is_bounded_and_replayable(setup_api):
    client, _, _ = setup_api
    response = client.post("/v1/experiments", json={})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["evaluation"]["exact_pairs"] == 34
    assert result["evaluation"]["criterion_count"] == 41
    assert result["clinical_validation"] is False
    assert client.post("/v1/experiments", json={}).json()["replayed"] is True
    assert client.post("/v1/experiments", json={"path": "../secret"}).status_code == 422


def test_implementation_change_does_not_reuse_old_result(setup_api):
    client, service, store = setup_api
    body = {"case_id": "reranking-demo", "trial_id": "NCT90009002"}
    first = client.post("/v1/screening", json=body).json()
    service.code = {"test_version": "changed"}
    second = client.post("/v1/screening", json=body).json()
    assert second["operation_id"] != first["operation_id"]
    assert len(store.data["operations"]) == 2


def test_missing_catalog_record_is_not_silently_dropped_from_listing(setup_api):
    client, _, store = setup_api
    store.data["trials"].pop("NCT90009002")
    assert client.get("/v1/trials").status_code == 409


def test_private_milestone_helpers_are_not_part_of_public_provenance(setup_api):
    _, service, _ = setup_api
    assert not any("milestone" in name for name in service.code)
