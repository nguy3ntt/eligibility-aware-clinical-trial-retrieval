"""Offline contract and failure-path tests; never download model weights."""

# The optional NumPy gate must precede imports of dense-only project modules.
# ruff: noqa: E402

import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from evaluation.baselines.dense import exact_top_k
from evaluation.dense_search import search_topic
from evaluation.dense_smoke import verify_smoke
from evaluation.run_dense_diagnostic import balanced_ids
from evaluation.tests.test_retrieval_baseline import synthetic_trial
from pipelines.connectors.snapshots import write_json
from pipelines.dense import local_id
from pipelines.dense_artifacts import encode_sample, load_index, load_sample, sample_documents
from pipelines.embeddings import (
    MODELS,
    REQUIRED_MODEL_FILES,
    EncodedBatch,
    ModelSpec,
    file_hash,
    file_record,
    model_directory,
    prepare_model,
    validate_vectors,
    verify_files,
    verify_model,
)
from pipelines.render_trials import REPRESENTATIONS, VERSION, render_trial


def normalized(values):
    matrix = np.asarray(values, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=-1, keepdims=True)


@pytest.mark.parametrize("block_size", [1, 4, 100])
def test_exact_search_matches_independent_full_matrix_reference(block_size):
    rng = np.random.default_rng(7)
    docs = normalized(rng.normal(size=(31, 8)))
    query = normalized(rng.normal(size=8))
    ids = [f"NCT{i:08d}" for i in range(len(docs))]
    expected = sorted(zip(ids, docs @ query, strict=True), key=lambda x: (-x[1], x[0]))[:9]
    actual = exact_top_k(docs, query, ids, k=9, block_size=block_size)
    assert [row[0] for row in actual] == [row[0] for row in expected]
    assert [row[1] for row in actual] == pytest.approx([row[1] for row in expected], abs=1e-6)


def test_exact_search_ties_negative_scores_and_large_k():
    docs = np.array([[1, 0], [-1, 0], [1, 0]], dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)
    assert exact_top_k(docs, query, ["c", "b", "a"], k=10, block_size=1) == [
        ("a", 1.0),
        ("c", 1.0),
        ("b", -1.0),
    ]


@pytest.mark.parametrize(
    "matrix",
    [
        np.zeros((1, 2), dtype=np.float32),
        np.array([[float("nan"), 0]], dtype=np.float32),
        np.array([[float("inf"), 0]], dtype=np.float32),
        np.array([[2, 0]], dtype=np.float32),
        np.array([[1, 0]], dtype=np.float64),
        np.array([[1, 0, 0]], dtype=np.float32),
    ],
)
def test_invalid_embeddings_are_rejected(matrix):
    with pytest.raises(ValueError):
        validate_vectors(matrix, 1, 2)


def test_exact_search_rejects_id_and_query_mismatches():
    docs = np.array([[1, 0], [0, 1]], dtype=np.float32)
    query = docs[0]
    with pytest.raises(ValueError, match="unique trial ID"):
        exact_top_k(docs, query, ["duplicate", "duplicate"])
    with pytest.raises(ValueError, match="shape"):
        exact_top_k(docs, np.array([1, 0, 0], dtype=np.float32), ["a", "b"])
    with pytest.raises(ValueError, match="positive"):
        exact_top_k(docs, query, ["a", "b"], k=0)
    with pytest.raises(ValueError, match="one-dimensional"):
        exact_top_k(docs, query.reshape(1, 2), ["a", "b"])


def source_fixture(root: Path, *, reverse=False) -> Path:
    root.mkdir()
    rows = [
        render_trial(
            synthetic_trial(f"NCT{i:08d}", condition),
            {
                "archive": "fixture.zip",
                "archive_sha256": "a" * 64,
                "member": f"NCT{i:08d}.xml",
                "crc32": "00000000",
            },
        )
        for i, condition in enumerate(["asthma", "diabetes", "migraine", "arthritis"], 1)
    ]
    if reverse:
        rows.reverse()
    path = root / "documents.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    write_json(
        root / "manifest.json",
        {
            "status": "complete",
            "renderer_version": VERSION,
            "documents": len(rows),
            "representations": {k: list(v) for k, v in REPRESENTATIONS.items()},
            "files": [file_record(path, root)],
        },
    )
    return root


class FakeEncoder:
    spec = ModelSpec("fixture", "invented/test", "f" * 40, 3, 4)

    def __init__(self):
        self.metadata = {
            "model": asdict(self.spec),
            "snapshot_sha256": "c" * 64,
            "normalization": "l2",
            "prompt": "",
        }
        self.batch_lengths = []

    def encode(self, texts):
        self.batch_lengths.append(len(texts))
        vectors = normalized([[len(text), text.count("a") + 1, 2] for text in texts])
        return EncodedBatch(vectors, [len(text.split()) for text in texts])


def index_fixture(tmp_path):
    source = source_fixture(tmp_path / "source")
    sample = tmp_path / "sample"
    sample_documents(source, sample, limit=3)
    encoder = FakeEncoder()
    output = tmp_path / "index"
    manifest = encode_sample(sample, output, encoder, batch_size=2)
    return sample, output, encoder, manifest


def test_sample_is_query_independent_order_invariant_and_immutable(tmp_path):
    a = source_fixture(tmp_path / "a")
    b = source_fixture(tmp_path / "b", reverse=True)
    left, right = tmp_path / "left", tmp_path / "right"
    sample_documents(a, left, limit=3)
    sample_documents(b, right, limit=3)
    lm, lr = load_sample(left)
    _, rr = load_sample(right)
    assert lr == rr
    assert lm["benchmark_metrics_permitted"] is False
    assert lm["source_documents"] == 4
    with pytest.raises(FileExistsError):
        sample_documents(a, left, limit=3)
    assert file_hash(left / "documents.jsonl") == file_hash(right / "documents.jsonl")
    with pytest.raises(ValueError, match="512"):
        sample_documents(a, tmp_path / "too_large", limit=513)


@pytest.mark.parametrize("problem", ["row", "file", "duplicate"])
def test_corrupt_source_fails_visibly_without_publishing_sample(tmp_path, problem):
    source = source_fixture(tmp_path / "source")
    path = source / "documents.jsonl"
    lines = path.read_text().splitlines()
    if problem == "row":
        row = json.loads(lines[0])
        row["representations"]["summary"] = "Changed fixture"
        lines[0] = json.dumps(row)
    elif problem == "duplicate":
        lines[-1] = lines[0]
    else:
        lines = lines[:-1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = tmp_path / "bad"
    with pytest.raises(ValueError):
        sample_documents(source, output, limit=2)
    assert json.loads((output / "manifest.json").read_bytes())["status"] == "failed"
    assert json.loads((output / "validation-issues.json").read_bytes())
    with pytest.raises(ValueError, match="completed"):
        load_sample(output)


def test_batched_encoding_roundtrip_records_truncation_and_provenance(tmp_path):
    _, output, encoder, manifest = index_fixture(tmp_path)
    loaded, rows, vectors = load_index(output)
    assert loaded == manifest
    assert encoder.batch_lengths == [2, 1]
    assert vectors.shape == (3, 3)
    assert manifest["truncated_documents"] == 3
    assert manifest["vector_bytes"] == 36
    assert manifest["benchmark_metrics_permitted"] is False
    assert all(row["source"]["archive"] == "fixture.zip" for row in rows)
    assert manifest["template"]["representation"] == "summary"
    assert manifest["code"]["source_sha256"]
    with pytest.raises(FileExistsError):
        encode_sample(tmp_path / "sample", output, encoder)


def test_invalid_encoder_output_leaves_a_failed_artifact(tmp_path):
    sample, _, encoder, _ = index_fixture(tmp_path)
    encoder.encode = lambda texts: EncodedBatch(np.zeros((len(texts), 3), np.float32), [5])
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="normalized"):
        encode_sample(sample, output, encoder)
    with pytest.raises(ValueError, match="completed"):
        load_index(output)
    assert (output / "validation-issues.json").exists()


def test_tampered_vectors_are_rejected_before_search(tmp_path):
    _, output, _, _ = index_fixture(tmp_path)
    with (output / "vectors.npy").open("r+b") as handle:
        handle.seek(-1, 2)
        handle.write(b"x")
    with pytest.raises(ValueError, match="checksum"):
        load_index(output)


def test_synthetic_query_search_preserves_provenance_and_rejects_wrong_model(tmp_path):
    _, output, encoder, _ = index_fixture(tmp_path)
    topics = tmp_path / "topics.xml"
    topics.write_text(
        '<topics task="2022 TREC Clinical Trials">'
        '<topic number="1">An invented synthetic asthma case.</topic></topics>'
    )
    result = search_topic(output, topics, "1", encoder, k=2)
    repeat = search_topic(output, topics, "1", encoder, k=2)
    assert result["results"] == repeat["results"]
    assert result["documents_searched"] == 3
    assert result["eligibility_assessment"] == "not_performed"
    assert result["query_truncated"] is True
    assert all(row["source"]["archive"] == "fixture.zip" for row in result["results"])
    smoke = verify_smoke(output, topics, encoder, ["1"])
    assert smoke["status"] == "passed"
    assert smoke["self_retrieval_checks"] == 3
    with pytest.raises(ValueError, match="topic ID"):
        search_topic(output, topics, "999", encoder)
    encoder.spec = replace(encoder.spec, revision="e" * 40)
    with pytest.raises(ValueError, match="does not match"):
        search_topic(output, topics, "1", encoder)


def test_model_preparation_is_pinned_local_and_idempotent(tmp_path, monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    calls = []

    def download(repository, **kwargs):
        calls.append((repository, kwargs))
        root = Path(kwargs["local_dir"])
        if os.name == "nt":
            assert str(root).startswith("\\\\?\\")
        for name in REQUIRED_MODEL_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                json.dumps(
                    [
                        {"type": "sentence_transformers.models.Transformer", "path": ""},
                        {"type": "sentence_transformers.models.Pooling", "path": "1_Pooling"},
                    ]
                )
                if name == "modules.json"
                else "{}"
            )
            path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(hub, "snapshot_download", download)
    spec = MODELS["minilm"]
    root = prepare_model(spec, tmp_path / "models")
    assert root == model_directory(tmp_path / "models", spec)
    assert prepare_model(spec, tmp_path / "models") == root
    assert len(calls) == 1
    assert calls[0][1]["revision"] == spec.revision
    assert calls[0][1]["token"] is False
    assert "model.safetensors" in calls[0][1]["allow_patterns"]
    assert "pytorch_model.bin" not in calls[0][1]["allow_patterns"]
    with pytest.raises(ValueError, match="pinned model"):
        verify_model(root, replace(spec, revision="e" * 40))
    (root / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        prepare_model(spec, tmp_path / "models")


def test_local_output_ids_cannot_escape_workspace():
    import argparse

    for value in ("../outside", "C:/outside", "nested/path", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            local_id(value)


def test_artifact_manifest_cannot_reference_outside_or_duplicate_files(tmp_path):
    root = tmp_path / "artifact"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("invented fixture")
    record = {
        "path": "../outside.txt",
        "bytes": outside.stat().st_size,
        "sha256": file_hash(outside),
    }
    with pytest.raises(ValueError, match="invalid or duplicate"):
        verify_files(root, [record], {"../outside.txt"})
    inside = root / "inside.txt"
    inside.write_text("invented fixture")
    record = file_record(inside, root)
    with pytest.raises(ValueError, match="invalid or duplicate"):
        verify_files(root, [record, record], {"inside.txt"})


def test_token_audit_mismatch_fails_encoding(tmp_path):
    sample, _, encoder, _ = index_fixture(tmp_path)
    original = encoder.encode

    def bad_audit(texts):
        encoded = original(texts)
        return EncodedBatch(encoded.vectors, [])

    encoder.encode = bad_audit
    with pytest.raises(ValueError, match="token-count"):
        encode_sample(sample, tmp_path / "bad_audit", encoder)


def test_unsupported_model_module_is_not_marked_complete(tmp_path, monkeypatch):
    hub = pytest.importorskip("huggingface_hub")

    def bad_download(repository, **kwargs):
        root = Path(kwargs["local_dir"])
        for name in REQUIRED_MODEL_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps([{"type": "untrusted.RemoteCode", "path": "../outside"}])
                if name == "modules.json"
                else "{}"
            )

    monkeypatch.setattr(hub, "snapshot_download", bad_download)
    spec = MODELS["minilm"]
    with pytest.raises(ValueError, match="remote code"):
        prepare_model(spec, tmp_path)
    assert not (model_directory(tmp_path, spec) / "snapshot.json").exists()


def test_balanced_diagnostic_pool_is_deterministic_and_keeps_available_grades():
    qrels = [
        {"topic_id": "1", "trial_id": f"NCT0000000{i}", "grade": grade}
        for grade, values in enumerate(((1, 2, 3), (4,), (5, 6, 7)))
        for i in values
    ]
    selected = balanced_ids(qrels, per_grade=2, seed="fixture")
    assert selected == balanced_ids(list(reversed(qrels)), per_grade=2, seed="fixture")
    assert "NCT00000004" in selected
    assert len(selected) == 5
    with pytest.raises(ValueError, match="no grade-1"):
        balanced_ids([row for row in qrels if row["grade"] != 1], per_grade=1)
