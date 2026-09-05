"""Import verified dense artifacts into an isolated, immutable-contract collection."""

from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.app.repositories.qdrant import PAYLOAD_INDEXES, VECTOR_NAME, QdrantRepository, point_id
from evaluation.baselines.filters import trial_age_days
from pipelines.dense_artifacts import load_index
from pipelines.embeddings import MODELS, file_hash
from pipelines.render_trials import REPRESENTATIONS
from pipelines.render_trials import VERSION as RENDERER_VERSION


def artifact_contract(index: Path) -> tuple[dict, list[dict], np.ndarray]:
    manifest, rows, vectors = load_index(index)
    encoder = manifest["encoder"]
    if (
        encoder["model"] != asdict(MODELS["minilm"])
        or encoder["normalization"] != "l2"
        or encoder["dtype"] != "float32"
        or encoder["prompt"] != ""
        or manifest["dimension"] != MODELS["minilm"].dimension
        or manifest["template"]
        != {
            "version": "rendered-representation-identity-v1",
            "renderer": RENDERER_VERSION,
            "representation": "title_conditions",
            "fields": list(REPRESENTATIONS["title_conditions"]),
            "prompt": "",
            "chunking": "none",
        }
    ):
        raise ValueError("only the pinned normalized MiniLM title_conditions artifact is supported")
    contract = {
        "schema_version": "qdrant-trials-v1",
        "artifact_sha256": file_hash(index / "manifest.json"),
        "model": encoder["model"],
        "snapshot_sha256": encoder["snapshot_sha256"],
        "template": manifest["template"],
        "dimension": manifest["dimension"],
        "documents": len(rows),
        "benchmark_comparable": False,
        "filter_version": "qdrant-age-sex-v1",
    }
    return contract, rows, vectors


def make_point(row: dict, vector: np.ndarray, contract: dict) -> dict:
    metadata = row["filter_metadata"]
    if any(value is not None and not isinstance(value, str) for value in metadata.values()):
        raise ValueError("filter metadata must contain strings or null")
    sex = (metadata.get("sex") or "").strip().lower()
    payload = {
        "trial_id": row["trial_id"],
        "artifact_sha256": contract["artifact_sha256"],
        "title": row["representations"]["title_conditions"].split("\n")[0],
        "source": row["source"],
        "content_sha256": row["content_sha256"],
        "filter_metadata": metadata,
        "eligibility_assessment": "not_performed",
    }
    if sex in {"male", "female", "all", "both"}:
        payload["sex"] = sex
    for key in ("minimum_age", "maximum_age"):
        value = trial_age_days(metadata.get(key))
        if value is not None:
            if not math.isfinite(value):
                raise ValueError("nonfinite trial age")
            payload[key + "_days"] = value
    minimum, maximum = payload.get("minimum_age_days"), payload.get("maximum_age_days")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"inverted age bounds for {row['trial_id']}")
    return {
        "id": point_id(row["trial_id"]),
        "vector": {VECTOR_NAME: vector.tolist()},
        "payload": payload,
    }


def payload_matches(actual: dict, expected: dict) -> bool:
    """Preserve evidence exactly; permit only float serialization noise in derived ages."""
    if actual.keys() != expected.keys():
        return False
    for key, value in expected.items():
        if key in {"minimum_age_days", "maximum_age_days"}:
            received = actual[key]
            if isinstance(received, bool) or not isinstance(received, int | float):
                return False
            if not math.isclose(received, value, abs_tol=1e-9, rel_tol=0):
                return False
        elif actual[key] != value:
            return False
    return True


def verify_import(repo: QdrantRepository, points: list[dict], contract: dict) -> dict:
    repo.version()
    repo.check_contract(contract)
    if repo.count() != len(points):
        raise ValueError("collection point count differs from the verified artifact")
    for start in range(0, len(points), 64):
        expected = {point["id"]: point for point in points[start : start + 64]}
        received = repo.retrieve(list(expected))
        if {point["id"] for point in received} != set(expected):
            raise ValueError("Qdrant is missing imported IDs")
        for point in received:
            source = expected[point["id"]]
            if not payload_matches(point["payload"], source["payload"]):
                raise ValueError("stored payload differs from source evidence")
            if not np.allclose(
                point["vector"][VECTOR_NAME], source["vector"][VECTOR_NAME], atol=1e-6, rtol=0
            ):
                raise ValueError("stored vector differs from the artifact")
    schema = repo.info().get("payload_schema", {})
    if any(schema.get(key, {}).get("data_type") != kind for key, kind in PAYLOAD_INDEXES.items()):
        raise ValueError("required payload indexes are missing")
    return {
        "status": "verified",
        "collection": repo.collection,
        "points": len(points),
        "payload_indexes": len(PAYLOAD_INDEXES),
        "artifact_sha256": contract["artifact_sha256"],
        "benchmark_comparable": False,
        "server_version": repo.version(),
    }


def import_index(repo: QdrantRepository, index: Path, *, batch_size: int = 64) -> dict:
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 128
    ):
        raise ValueError("batch size must be 1..128")
    contract, rows, vectors = artifact_contract(index)
    # Validate every payload before creating or modifying anything remotely.
    points = [make_point(row, vector, contract) for row, vector in zip(rows, vectors, strict=True)]
    repo.ensure_collection(contract)
    for start in range(0, len(points), batch_size):
        repo.upsert(points[start : start + batch_size])
    return verify_import(repo, points, contract)
