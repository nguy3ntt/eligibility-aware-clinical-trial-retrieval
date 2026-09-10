"""Real PostgreSQL migrations and full API integration; never substitute SQLite."""

import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import inspect, text, update

from backend.app.core.config import get_settings
from backend.app.db.models import cases, metadata
from backend.app.repositories.postgres import (
    ConflictError,
    EvidenceError,
    PostgresStore,
    digest,
    local_engine,
    migrate,
)


@pytest.fixture
def database():
    if os.environ.get("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("explicit local PostgreSQL integration opt-in")
    settings = get_settings()
    schema = "test_m10_" + uuid.uuid4().hex
    admin = local_engine(settings.database_url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = local_engine(settings.database_url, options=f"-csearch_path={schema}")
    try:
        migrate(engine)
        yield PostgresStore(engine, "test-catalog"), settings
    finally:
        engine.dispose()
        assert schema.startswith("test_m10_") and len(schema) == 41
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def tiny_seed(store):
    from backend.tests.test_research_api import MemoryStore

    source = MemoryStore()
    store.seed(source.catalog(), source.data["cases"], source.data["trials"])
    return source


def test_real_migrations_are_idempotent_and_match_models(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    store, _ = database
    migrate(store.engine)
    with store.engine.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), metadata) == []
    tiny_seed(store)
    assert store.ready()["revision"] == "0001_catalogs"


def test_transactional_import_replay_conflict_and_rollback(database):
    store, _ = database
    source = tiny_seed(store)
    tiny_seed(store)
    assert store.page("cases", 10, 0)["total"] == 1
    changed = source.get("cases", "reranking-demo")
    changed["text"] = "Different invented source"
    with pytest.raises(ConflictError):
        store.seed(source.catalog(), {"new-record": changed, "reranking-demo": changed}, {})
    assert store.get("cases", "new-record") is None
    assert store.get("cases", "reranking-demo") == source.get("cases", "reranking-demo")


def test_database_tampering_is_detected(database):
    store, _ = database
    source = tiny_seed(store)
    changed = source.get("cases", "reranking-demo")
    changed["text"] = "Tampered invented source"
    with store.engine.begin() as c:
        c.execute(update(cases).where(cases.c.id == "reranking-demo").values(payload=changed))
    with pytest.raises(EvidenceError):
        store.get("cases", "reranking-demo")


def test_migration_downgrade_and_upgrade_in_owned_schema_only(database):
    from alembic import command
    from alembic.config import Config

    store, _ = database
    config = Config()
    config.set_main_option("script_location", str(Path("backend/app/db/migrations").resolve()))
    with store.engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "base")
        assert "ctr_cases" not in inspect(c).get_table_names()
    migrate(store.engine)
    tiny_seed(store)
    assert store.ready()["status"] == "ready"


def test_database_operation_persists_across_connections(database):
    store, _ = database
    tiny_seed(store)
    key = digest({"invented_operation": 1})
    payload = {"kind": "experiment", "status": "complete", "evidence": "invented"}
    store.save_operation(key, "experiment", {}, payload)
    store.engine.dispose()
    other = PostgresStore(store.engine, store.catalog_id)
    assert other.get("operations", key) == payload
    with pytest.raises(ConflictError):
        other.save_operation(key, "experiment", {}, {**payload, "evidence": "changed"})


@pytest.mark.skipif(
    os.environ.get("RUN_API_INTEGRATION") != "1", reason="real models/Qdrant opt-in"
)
def test_complete_api_with_real_postgres_qdrant_models_and_persistence(database):
    import numpy as np
    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from backend.app.services.application import ResearchService
    from evaluation.baselines.filters import extract_topic_demographics
    from pipelines.api_data import seed
    from pipelines.rerank import candidates

    store, settings = database
    result = seed(store, settings)
    assert (result["cases"], result["trials"]) == (51, 446)
    service = ResearchService(store, settings)
    with TestClient(create_app(service=service), base_url="http://localhost") as client:
        assert client.get("/v1/ready").status_code == 200
        assert client.get("/v1/trials").json()["total"] == 446
        for method in ("dense", "sparse", "hybrid"):
            response = client.post(
                "/v1/search", json={"case_id": "trec-ct-2022:29", "method": method}
            )
            assert response.status_code == 200, response.text
            packet = response.json()
            assert packet["replayed"] is False
            assert packet["result"]["dense_mode"] == "exact"
            assert len(packet["result"]["results"]) == 3
            assert all(r["screening"]["assessment"]["notice"] for r in packet["result"]["results"])
            if method == "dense":
                dense_packet = packet
        from backend.app.schemas.patient import SyntheticCase

        case = SyntheticCase.model_validate(service.record("cases", "trec-ct-2022:29"))
        contract, rows, vectors, _, _ = service.prepared
        vector = service.encoder.encode([case.text]).vectors[0]
        reference = candidates(
            rows, np.asarray(vectors) @ vector, extract_topic_demographics(case.text)
        )
        actual = dense_packet["result"]["results"]
        assert [r["trial_id"] for r in actual] == [r["trial_id"] for r in reference[:3]]
        assert np.allclose(
            [r["relevance"]["ranking"]["score"] for r in actual],
            [r["score"] for r in reference[:3]],
            atol=1e-6,
            rtol=0,
        )
        profiled = client.post(
            "/v1/search", json={"case_id": "trec-ct-2022:29", "fact_extractor": "profile"}
        )
        assert profiled.status_code == 200
        assert profiled.json()["result"]["filter_plan"] is not None
        reranked = client.post(
            "/v1/search", json={"case_id": "trec-ct-2022:29", "rerank": True, "rerank_depth": 10}
        )
        assert reranked.status_code == 200, reranked.text
        assert reranked.json()["result"]["reranker"]["revision"]
        nli = client.post(
            "/v1/screening",
            json={"case_id": "reranking-demo", "trial_id": "NCT90009001", "semantic": True},
        )
        assert nli.status_code == 200, nli.text
        assert nli.json()["result"]["assessment"]["status"] == "insufficient_information"
        assert all(a["promoted"] is False for a in nli.json()["result"]["semantic"]["advisories"])
        operation_id = dense_packet["operation_id"]
    with TestClient(
        create_app(service=ResearchService(store, settings)), base_url="http://localhost"
    ) as restarted:
        replay = restarted.post("/v1/search", json={"case_id": "trec-ct-2022:29"})
        assert replay.json()["replayed"] is True
        assert replay.json()["operation_id"] == operation_id
        assert replay.json()["result"] == dense_packet["result"]
        assert (
            restarted.get("/v1/experiments/" + operation_id).json()["result"]
            == dense_packet["result"]
        )
