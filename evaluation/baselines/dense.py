"""Exact blockwise cosine search with stable ID tie-breaking and strict validation."""

from __future__ import annotations

import numpy as np

from pipelines.embeddings import validate_vectors


def exact_top_k(
    documents: np.ndarray,
    query: np.ndarray,
    trial_ids: list[str],
    *,
    k: int = 5,
    block_size: int = 128,
) -> list[tuple[str, float]]:
    """Score every document, retaining only the best k after each block."""
    if documents.ndim != 2 or not len(documents):
        raise ValueError("document vectors must be a nonempty matrix")
    if query.ndim != 1:
        raise ValueError("query vector must be one-dimensional")
    if k < 1 or block_size < 1 or not isinstance(k, int) or not isinstance(block_size, int):
        raise ValueError("k and block size must be positive integers")
    if len(trial_ids) != len(documents) or len(set(trial_ids)) != len(trial_ids):
        raise ValueError("one unique trial ID is required per document vector")
    if any(not isinstance(trial_id, str) or not trial_id for trial_id in trial_ids):
        raise ValueError("trial IDs must be nonempty strings")
    validate_vectors(query.reshape(1, -1), 1, documents.shape[1])
    best: list[tuple[str, float]] = []
    for start in range(0, len(documents), block_size):
        block = documents[start : start + block_size]
        validate_vectors(block, len(block), documents.shape[1])
        scores = np.clip(block @ query, -1.0, 1.0)
        candidates = [(trial_ids[start + i], float(score)) for i, score in enumerate(scores)]
        best = sorted(best + candidates, key=lambda pair: (-pair[1], pair[0]))[:k]
    return best
