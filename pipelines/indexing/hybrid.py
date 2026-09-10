"""Isolated hybrid collection built from the same verified dense source artifact."""

from pathlib import Path

import numpy as np

from backend.app.services.retrieval.sparse import (
    SPARSE_CONFIG,
    SPARSE_NAME,
    SparseBM25,
    check_sparse_config,
)
from pipelines.indexing.qdrant import artifact_contract, make_point, verify_import


def prepare_hybrid(index: Path):
    base, rows, vectors = artifact_contract(index)
    lexical = SparseBM25([row["representations"]["title_conditions"] for row in rows])
    contract = {**base, "schema_version": "qdrant-hybrid-v1", "lexical": lexical.manifest}
    points = [make_point(row, vector, contract) for row, vector in zip(rows, vectors, strict=True)]
    for point, sparse in zip(points, lexical.document_vectors, strict=True):
        point["vector"][SPARSE_NAME] = sparse
    return contract, rows, vectors, lexical, points


def verify_hybrid(repo, contract, points) -> dict:
    result = verify_import(repo, points, contract)
    check_sparse_config(repo.info())
    for start in range(0, len(points), 64):
        expected = {p["id"]: p["vector"][SPARSE_NAME] for p in points[start : start + 64]}
        retrieved = repo.retrieve(list(expected))
        if len(retrieved) != len(expected) or {p["id"] for p in retrieved} != set(expected):
            raise ValueError("sparse readback IDs differ from source")
        for point in retrieved:
            actual = point["vector"].get(SPARSE_NAME)
            reference = expected[point["id"]]
            if (
                actual is None
                or actual["indices"] != reference["indices"]
                or len(actual["values"]) != len(reference["values"])
                or not np.allclose(actual["values"], reference["values"], atol=1e-7, rtol=0)
            ):
                raise ValueError("stored sparse vector differs from lexical source")
    return {
        **result,
        "sparse_vectors_verified": len(points),
        "vocabulary_size": contract["lexical"]["vocabulary_size"],
    }


def load_hybrid(repo, index: Path) -> dict:
    contract, _, _, _, points = prepare_hybrid(index)
    repo.ensure_collection(contract, sparse_vectors=SPARSE_CONFIG)
    check_sparse_config(repo.info())
    for start in range(0, len(points), 64):
        repo.upsert(points[start : start + 64])
    return verify_hybrid(repo, contract, points)
