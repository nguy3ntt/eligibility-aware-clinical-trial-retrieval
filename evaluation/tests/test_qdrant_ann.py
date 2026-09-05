"""ANN measurement and non-destructive snapshot/rebuild regression checks."""

# ruff: noqa: E402
import copy
import json
import os
from uuid import uuid4

import httpx
import pytest

np = pytest.importorskip("numpy")

from backend.app.repositories.qdrant import (
    HNSW_PROFILE,
    OPTIMIZER_PROFILE,
    QdrantRepository,
    query_body,
)
from evaluation.qdrant_ann import (
    check_hits,
    graph_telemetry,
    latency_summary,
    recall_at_k,
    telemetry_delta,
)
from pipelines.connectors.snapshots import write_json
from pipelines.embeddings import file_hash
from pipelines.indexing import qdrant as indexing
from pipelines.indexing import qdrant_recovery as recovery


def test_recall_uses_available_neighbors_and_does_not_reward_empty_queries():
    assert recall_at_k(["a", "b"], ["a", "c"]) == 0.5
    assert recall_at_k(["a"], []) == 0
    assert recall_at_k([], []) is None
    with pytest.raises(ValueError, match="empty"):
        recall_at_k([], ["a"])
    with pytest.raises(ValueError, match="duplicate"):
        recall_at_k(["a"], ["a", "a"])


def test_telemetry_rejects_fallback_restart_and_concurrent_queries():
    before = {"segment_id": "one", "counts": {"filtered_large_cardinality": 5}}
    after = {
        "segment_id": "one",
        "counts": {"filtered_large_cardinality": 15, "filtered_exact": 10},
    }
    assert telemetry_delta(before, after, 10)["filtered_large_cardinality"] == 10
    for changed in (
        {**after, "segment_id": "rebuilt"},
        {**after, "counts": {"filtered_large_cardinality": 14}},
        {**after, "counts": {"filtered_large_cardinality": 16}},
        {**after, "counts": {**after["counts"], "filtered_small_cardinality": 1}},
        {**after, "counts": {**after["counts"], "filtered_exact": 11}},
    ):
        with pytest.raises(ValueError):
            telemetry_delta(before, changed, 10)
    with pytest.raises(ValueError, match="one populated"):
        graph_telemetry({"shards": [{"local": {"segments": []}}]})


def test_latency_and_retrieved_scores_reject_invalid_measurements():
    assert latency_summary([1, 2, 3])["median_ms"] == 2
    for values in ([], [-1], [float("nan")]):
        with pytest.raises(ValueError):
            latency_summary(values)
    for hit in (
        {"score": 0.5, "payload": {"trial_id": "unknown"}},
        {"score": 0.6, "payload": {"trial_id": "known"}},
        {"score": float("nan"), "payload": {"trial_id": "known"}},
    ):
        with pytest.raises(ValueError):
            check_hits([hit], {"known": 0.5})


def test_ann_query_parameters_and_versioned_profile():
    contract = {"dimension": 2, "artifact_sha256": "a" * 64}
    body = query_body([1, 0], contract, exact=False, hnsw_ef=128)
    assert body["params"] == {"exact": False, "hnsw_ef": 128}
    assert HNSW_PROFILE["full_scan_threshold"] == 10  # 1.19.0 rejects smaller thresholds.
    for ef in (0, 9, 513, True, 1.5):
        with pytest.raises(ValueError, match="hnsw_ef"):
            query_body([1, 0], contract, hnsw_ef=ef)


def test_graph_readiness_refuses_unbuilt_or_failed_index():
    contract = {"dimension": 2, "documents": 10}
    info = {
        "config": {
            "metadata": {"retrieval_contract": contract},
            "params": {"vectors": {"overview_dense": {"size": 2, "distance": "Cosine"}}},
            "hnsw_config": HNSW_PROFILE,
            "optimizer_config": OPTIMIZER_PROFILE,
        },
        "indexed_vectors_count": 0,
        "status": "green",
        "optimizer_status": "ok",
    }

    def handler(request):
        result = {"count": 10} if request.url.path.endswith("/count") else info
        return httpx.Response(200, json={"status": "ok", "result": result})

    with QdrantRepository(transport=httpx.MockTransport(handler)) as repo:
        with pytest.raises(ValueError, match="not ready"):
            repo.wait_hnsw(contract, timeout=0)
        info["indexed_vectors_count"] = 10
        assert repo.hnsw_ready(contract)["indexed_vectors_count"] == 10
        info["optimizer_status"] = {"error": "disk failure"}
        with pytest.raises(ValueError, match="optimizer failed"):
            repo.hnsw_ready(contract)
        with pytest.raises(ValueError, match="timeout"):
            repo.configure_hnsw(contract, timeout=-1)


def test_existing_restore_target_never_receives_upload(tmp_path):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"version": "1.19.0"} if request.url.path == "/" else {})

    with (
        QdrantRepository(transport=httpx.MockTransport(handler)) as repo,
        pytest.raises(ValueError, match="already exists"),
    ):
        repo.upload_snapshot(tmp_path / "absent.snapshot", "a" * 64)
    assert methods == ["GET", "GET"]


def test_backup_completion_and_failure_do_not_overwrite_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "verify_artifact_collection", lambda *args: ({}, {}))

    class Server:
        collection = "fixture"

        def hnsw_ready(self, contract):
            return {"config": {}}

        def version(self):
            return "1.19.0"

        def download_snapshot(self, path):
            path.write_bytes(b"invented snapshot bytes")
            return {"size": path.stat().st_size, "checksum": file_hash(path)}

    backup = tmp_path / "good"
    result = recovery.create_backup(Server(), tmp_path, backup)
    assert result["status"] == "complete"
    assert json.loads((backup / "started.json").read_text())["status"] == "running"
    assert recovery.validate_backup(backup, {}) == result
    original = (backup / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        recovery.create_backup(Server(), tmp_path, backup)
    assert (backup / "manifest.json").read_bytes() == original
    (backup / "collection.snapshot").write_bytes(b"x" * result["bytes"])
    with pytest.raises(ValueError, match="checksum"):
        recovery.validate_backup(backup, {})

    class FailingServer(Server):
        def download_snapshot(self, path):
            raise ValueError("simulated download failure")

    failed = tmp_path / "failed"
    with pytest.raises(ValueError, match="download failure"):
        recovery.create_backup(FailingServer(), tmp_path, failed)
    assert json.loads((failed / "manifest.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        recovery.validate_backup(failed, {})


def test_bad_backup_blocks_all_server_access(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "artifact_contract", lambda _: ({}, [], None))
    write_json(tmp_path / "manifest.json", {"status": "running"})

    class UnusedServer:
        def upload_snapshot(self, *args):
            pytest.fail("invalid snapshot reached server")

    with pytest.raises(ValueError, match="incomplete"):
        recovery.restore_backup(UnusedServer(), tmp_path, tmp_path)


def test_source_reencoding_is_batched_and_detects_changed_vectors():
    from types import SimpleNamespace

    from evaluation.qdrant_recovery_smoke import verify_reencoding

    batches = []

    class Encoder:
        spec = SimpleNamespace(dimension=2)

        def encode(self, texts):
            batches.append(len(texts))
            return SimpleNamespace(
                vectors=np.tile(np.array([[1, 0]], dtype=np.float32), (len(texts), 1))
            )

    rows = [{"representations": {"title_conditions": "invented"}} for _ in range(35)]
    vectors = np.tile(np.array([[1, 0]], dtype=np.float32), (35, 1))
    assert verify_reencoding(rows, vectors, Encoder())["maximum_absolute_error"] == 0
    assert batches == [16, 16, 3]
    vectors[34] = [0, 1]
    with pytest.raises(ValueError, match="re-encoding"):
        verify_reencoding(rows, vectors, Encoder())


def test_snapshot_download_bounds_and_unsafe_names(tmp_path):
    for description in (
        {"name": "../bad.snapshot", "size": 3},
        {"name": "good.snapshot", "size": 1024**3},
        {"name": "good.snapshot", "size": 3},
    ):

        def handler(request, description=description):
            if request.method == "POST":
                return httpx.Response(200, json={"status": "ok", "result": description})
            return httpx.Response(200, content=b"ab")  # Truncated download.

        with (
            QdrantRepository(transport=httpx.MockTransport(handler)) as repo,
            pytest.raises(ValueError),
        ):
            repo.download_snapshot(tmp_path / (uuid4().hex + ".snapshot"))


def test_recovery_cli_failure_preserves_final_failure_report(tmp_path, monkeypatch, capsys):
    from pipelines import qdrant_index

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qdrant_index",
            "rebuild",
            "--collection",
            "new_collection",
            "--report-id",
            "failure-test",
        ],
    )

    def fail(*args):
        raise ValueError("invented rebuild failure")

    monkeypatch.setattr(qdrant_index, "rebuild_index", fail)
    with pytest.raises(SystemExit) as exc:
        qdrant_index.main()
    assert exc.value.code == 1
    report = tmp_path / "evaluation/reports/failure-test/recovery.json"
    assert json.loads(report.read_text())["status"] == "failed"
    assert "invented rebuild failure" in capsys.readouterr().err


def test_live_ann_snapshot_restore_and_rebuild(tmp_path, monkeypatch):
    url = os.environ.get("QDRANT_TEST_URL")
    if not url:
        pytest.skip("set QDRANT_TEST_URL to test the actual Qdrant server")
    # Invented documents and random normalized vectors; no downloaded models/data needed.
    rng = np.random.default_rng(4)
    vectors = rng.normal(size=(64, 384)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    contract = {"dimension": 384, "documents": 64, "artifact_sha256": "a" * 64}
    rows = [
        {
            "trial_id": f"NCT{i:08d}",
            "filter_metadata": {"sex": "All"},
            "representations": {"title_conditions": "Invented trial"},
            "source": {"archive": "invented"},
            "content_sha256": "b" * 64,
        }
        for i in range(64)
    ]
    monkeypatch.setattr(indexing, "artifact_contract", lambda _: (contract, rows, vectors))
    monkeypatch.setattr(recovery, "artifact_contract", lambda _: (contract, rows, vectors))
    prefix = "test_" + uuid4().hex[:8]
    repos = [QdrantRepository(url, prefix + suffix) for suffix in ("_s", "_r", "_b")]
    source, restored, rebuilt = repos
    try:
        indexing.import_index(source, tmp_path)
        source.configure_hnsw(contract)
        before = graph_telemetry(source.collection_telemetry())
        query = vectors[0].tolist()
        expected = source.search(query, contract, k=10)
        actual = source.search(query, contract, k=10, exact=False, hnsw_ef=128)
        assert recall_at_k([h["id"] for h in expected], [h["id"] for h in actual]) >= 0.9
        telemetry_delta(before, graph_telemetry(source.collection_telemetry()), 1)
        backup = tmp_path / "backup"
        recovery.create_backup(source, tmp_path, backup)
        assert recovery.restore_backup(restored, tmp_path, backup)["status"] == "verified"
        assert recovery.rebuild_index(rebuilt, tmp_path)["status"] == "verified"
        for target in (restored, rebuilt):
            hits = target.search(query, contract, k=10)
            assert [h["id"] for h in hits] == [h["id"] for h in expected]
            with pytest.raises(ValueError, match="already exists"):
                recovery.restore_backup(target, tmp_path, backup)
        assert source.count() == 64
        # Incompatible metadata is rejected before overwriting any collection.
        wrong = copy.deepcopy(contract)
        wrong["artifact_sha256"] = "c" * 64
        with pytest.raises(ValueError, match="incompatible"):
            recovery.validate_backup(backup, wrong)
    finally:
        for repo in repos:
            response = repo.client.get(repo.path)
            if response.status_code == 200:
                repo.request("DELETE", repo.path)  # Only randomly named test-owned collections.
            repo.client.close()
