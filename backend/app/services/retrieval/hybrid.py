"""Deterministic rank fusion with distinct raw branch scores and stored evidence."""

import math

from backend.app.repositories.qdrant import query_body
from backend.app.services.retrieval.sparse import SPARSE_NAME, check_sparse_config

RRF_K = 60
CANDIDATE_DEPTH = 100


def reciprocal_rank_fusion(
    branches: dict[str, list[dict]], *, k: int = 10, rrf_k: int = RRF_K
) -> list[dict]:
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
        raise ValueError("result count must be 1..100")
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or not 1 <= rrf_k <= 1000:
        raise ValueError("RRF constant must be 1..1000")
    merged = {}
    for branch, hits in branches.items():
        if branch not in {"dense", "sparse"}:
            raise ValueError("unknown retrieval branch")
        seen = set()
        for rank, hit in enumerate(hits, 1):
            trial_id = hit["payload"]["trial_id"]
            if trial_id in seen or not math.isfinite(hit["score"]):
                raise ValueError("duplicate ID or nonfinite branch score")
            seen.add(trial_id)
            item = merged.setdefault(
                trial_id,
                {
                    "trial_id": trial_id,
                    "score": 0.0,
                    "score_kind": "reciprocal_rank_fusion",
                    "branches": {},
                    "payload": hit["payload"],
                },
            )
            if item["payload"] != hit["payload"]:
                raise ValueError("retrieval branches disagree on stored evidence")
            contribution = 1 / (rrf_k + rank)
            item["score"] += contribution
            item["branches"][branch] = {
                "rank": rank,
                "raw_score": hit["score"],
                "score_kind": "cosine_similarity" if branch == "dense" else "bm25_lucene",
                "rrf_contribution": contribution,
            }
    return sorted(merged.values(), key=lambda p: (-p["score"], p["trial_id"]))[:k]


def search_branches(
    repo, contract, lexical, vector, text, *, demographics=None, candidate_depth=CANDIDATE_DEPTH
) -> tuple[dict, dict]:
    if (
        isinstance(candidate_depth, bool)
        or not isinstance(candidate_depth, int)
        or not 1 <= candidate_depth <= 100
    ):
        raise ValueError("candidate depth must be 1..100")
    if contract.get("lexical") != lexical.manifest:
        raise ValueError("query lexical model differs from collection contract")
    if not 1 <= contract["documents"] <= 512:
        raise ValueError("hybrid diagnostic requires 1..512 documents")
    repo.check_contract(contract)
    check_sparse_config(repo.info())
    body = query_body(vector, contract, k=candidate_depth, demographics=demographics)
    # Bounded diagnostic only: fetch all to make cutoff ties deterministic by NCT ID.
    body["limit"] = contract["documents"]
    dense = repo.query_points(body)[:candidate_depth]
    sparse_vector, audit = lexical.query(text)
    sparse = []
    if sparse_vector["indices"]:
        sparse_body = {**body, "query": sparse_vector, "using": SPARSE_NAME}
        sparse = [hit for hit in repo.query_points(sparse_body) if hit["score"] > 0][
            :candidate_depth
        ]
    return {"dense": dense, "sparse": sparse}, audit


def rank_results(branches: dict, *, method="hybrid", k=10) -> list[dict]:
    if method not in {"dense", "sparse", "hybrid"}:
        raise ValueError("unknown search method")
    if method == "hybrid":
        return reciprocal_rank_fusion(branches, k=k)
    # Reuse provenance generation but expose the selected branch's original score.
    result = reciprocal_rank_fusion({method: branches[method]}, k=k)
    for item in result:
        contribution = item["branches"][method]
        item["score"] = contribution["raw_score"]
        item["score_kind"] = contribution["score_kind"]
        contribution.pop("rrf_contribution")
    return result
