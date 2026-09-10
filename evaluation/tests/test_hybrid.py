"""Independent scoring oracles, fusion failures, and isolated live sparse storage."""

# ruff: noqa: E402
import copy
import os
from uuid import uuid4

import httpx
import pytest

np = pytest.importorskip("numpy")
bm25s = pytest.importorskip("bm25s")

from backend.app.repositories.qdrant import QdrantRepository
from backend.app.services.retrieval.hybrid import (
    rank_results,
    reciprocal_rank_fusion,
    search_branches,
)
from backend.app.services.retrieval.sparse import PARAMETERS, SPARSE_CONFIG, SPARSE_NAME, SparseBM25
from evaluation.hybrid import check_branch, reference_lexical_scores
from evaluation.tests.test_qdrant import fixture_data
from pipelines.indexing import hybrid as indexing


def hit(number, score=1):
    return {"score": score, "payload": {"trial_id": f"NCT{number:08d}", "source": "invented"}}


@pytest.mark.parametrize("query", ["alpha", "alpha alpha beta", "ZZZ", "the and", "BETA-gamma"])
def test_sparse_factorization_matches_independent_bm25s(query):
    texts = ["alpha alpha beta", "beta gamma", "alpha gamma delta", "the and"]
    sparse = SparseBM25(texts)
    reference = bm25s.BM25(k1=1.2, b=0.75, method="lucene")
    reference.index(
        bm25s.tokenize(texts, show_progress=False, token_pattern=PARAMETERS["token_pattern"]),
        show_progress=False,
    )
    tokens = bm25s.tokenize([query], return_ids=False, show_progress=False)[0]
    expected = reference_lexical_scores(reference, tokens, len(texts))
    if not tokens:
        assert expected.tolist() == [0, 0, 0, 0]
    vector, audit = sparse.query(query)
    query_values = dict(zip(vector["indices"], vector["values"], strict=True))
    scores = [
        sum(query_values.get(i, 0) * v for i, v in zip(doc["indices"], doc["values"], strict=True))
        for doc in sparse.document_vectors
    ]
    assert scores == pytest.approx(expected, abs=1e-6)
    assert audit["empty_lexical_query"] == (not vector["indices"])
    assert sparse.document_vectors[-1] == {"indices": [], "values": []}


def test_lexical_versioning_and_invalid_corpora():
    first = SparseBM25(["alpha beta", "gamma"])
    reordered = SparseBM25(["gamma", "alpha beta"])
    assert first.vocabulary == reordered.vocabulary
    assert (
        first.manifest["document_lengths_sha256"] != reordered.manifest["document_lengths_sha256"]
    )
    assert first.manifest == SparseBM25(["alpha beta", "gamma"]).manifest
    assert first.manifest != SparseBM25(["alpha alpha beta", "gamma"]).manifest
    for texts in ([], ["the and"], ["alpha"] * 513, [None]):
        with pytest.raises(ValueError):
            SparseBM25(texts)


def test_rrf_uses_one_based_ranks_not_incompatible_scores():
    branches = {"dense": [hit(1, 0.9), hit(2, 0.8)], "sparse": [hit(2, 500), hit(3, 200)]}
    results = reciprocal_rank_fusion(branches)
    assert [r["trial_id"] for r in results] == ["NCT00000002", "NCT00000001", "NCT00000003"]
    assert results[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert results[0]["branches"]["sparse"]["raw_score"] == 500
    assert results[0]["branches"]["dense"]["rank"] == 2
    assert results[0]["payload"] == hit(2)["payload"]
    scaled = copy.deepcopy(branches)
    scaled["sparse"][0]["score"] *= 1000
    assert [r["score"] for r in reciprocal_rank_fusion(scaled)] == [r["score"] for r in results]
    assert rank_results(branches, method="dense")[0]["score"] == 0.9
    assert "rrf_contribution" not in rank_results(branches, method="dense")[0]["branches"]["dense"]


def test_fusion_ties_empty_branches_and_invalid_inputs():
    assert reciprocal_rank_fusion({"dense": [], "sparse": []}) == []
    assert (
        reciprocal_rank_fusion({"sparse": [hit(2)], "dense": [hit(1)]})[0]["trial_id"]
        == "NCT00000001"
    )
    assert len(reciprocal_rank_fusion({"dense": [hit(1)], "sparse": []})) == 1
    altered = hit(1)
    altered["payload"]["source"] = "changed"
    for branches in (
        {"dense": [hit(1), hit(1)]},
        {"sparse": [hit(1, float("nan"))]},
        {"dense": [hit(1)], "sparse": [altered]},
        {"unknown": []},
    ):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion(branches)
    for k in (True, 0, 101, 1.5):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion({}, k=k)
    for constant in (True, 0, 1001, 1.5):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion({}, rrf_k=constant)
    with pytest.raises(ValueError):
        rank_results({}, method="unknown")


def test_search_filter_parity_empty_query_and_contract_preflight():
    sparse = SparseBM25(["alpha", "beta"])
    contract = {
        "documents": 2,
        "dimension": 3,
        "artifact_sha256": "a" * 64,
        "lexical": sparse.manifest,
    }
    requests = []

    class Repo:
        def check_contract(self, value):
            assert value == contract

        def info(self):
            return {"config": {"params": {"sparse_vectors": SPARSE_CONFIG}}}

        def query_points(self, body):
            requests.append(body)
            return [hit(1)]

    facts = {"age_days": 70 * 365.2425, "sex": "Male"}
    branches, _ = search_branches(Repo(), contract, sparse, [1, 0, 0], "alpha", demographics=facts)
    assert branches["dense"] == branches["sparse"]
    assert requests[0]["filter"] == requests[1]["filter"]
    assert requests[0]["params"] == {"exact": True}
    assert requests[0]["limit"] == requests[1]["limit"] == 2
    assert requests[1]["using"] == SPARSE_NAME
    requests.clear()
    branches, audit = search_branches(Repo(), contract, sparse, [1, 0, 0], "unknownterm")
    assert len(requests) == 1 and branches["sparse"] == []
    assert audit["empty_lexical_query"]
    assert len(rank_results(branches)) == 1
    requests.clear()
    with pytest.raises(ValueError, match="lexical model"):
        search_branches(Repo(), contract, SparseBM25(["different"]), [1, 0, 0], "alpha")
    assert requests == []
    for depth in (0, 101, True, 1.5):
        with pytest.raises(ValueError, match="candidate depth"):
            search_branches(Repo(), contract, sparse, [1, 0, 0], "alpha", candidate_depth=depth)


def test_wrong_sparse_config_fails_before_any_existing_collection_write():
    methods = []
    contract = {"dimension": 3}

    def handler(request):
        methods.append(request.method)
        if request.url.path == "/":
            return httpx.Response(200, json={"version": "1.19.0"})
        config = {
            "metadata": {"retrieval_contract": contract},
            "params": {
                "vectors": {"overview_dense": {"size": 3, "distance": "Cosine"}},
                "sparse_vectors": {SPARSE_NAME: {"modifier": "idf", "index": {"on_disk": False}}},
            },
        }
        return httpx.Response(200, json={"status": "ok", "result": {"config": config}})

    with (
        QdrantRepository(transport=httpx.MockTransport(handler)) as repo,
        pytest.raises(ValueError, match="sparse vector configuration"),
    ):
        repo.ensure_collection(contract, sparse_vectors=SPARSE_CONFIG)
    assert set(methods) == {"GET"}


@pytest.mark.parametrize("damage", ["values", "missing", "duplicate"])
def test_sparse_readback_cannot_hide_corruption_by_broadcasting(monkeypatch, damage):
    monkeypatch.setattr(indexing, "verify_import", lambda *args: {})
    point = {"id": "1", "vector": {SPARSE_NAME: {"indices": [1, 2], "values": [0.5, 0.5]}}}
    changed = copy.deepcopy(point)
    changed["vector"][SPARSE_NAME]["values"] = [0.5]

    class Repo:
        def info(self):
            return {"config": {"params": {"sparse_vectors": SPARSE_CONFIG}}}

        def retrieve(self, ids):
            return {"values": [changed], "missing": [], "duplicate": [point, point]}[damage]

    with pytest.raises(ValueError):
        indexing.verify_hybrid(Repo(), {}, [point])


def test_independent_branch_oracle_rejects_wrong_scores_order_ids():
    reference = {"NCT00000001": 2.0, "NCT00000002": 1.0}
    assert check_branch([hit(1, 2), hit(2, 1)], reference) == 0
    for hits in (
        [hit(1, 2)],
        [hit(1, 2), hit(1, 2)],
        [hit(2, 1), hit(1, 2)],
        [hit(1, 2), hit(3, 1)],
        [hit(1, 9), hit(2, 1)],
    ):
        with pytest.raises(ValueError):
            check_branch(hits, reference)


def test_real_server_sparse_resume_filter_empty_document_and_corruption():
    url = os.environ.get("QDRANT_TEST_URL")
    if not url:
        pytest.skip("set QDRANT_TEST_URL for an isolated live-server integration test")
    base, points = fixture_data()
    lexical = SparseBM25(["alpha", "alpha beta", "alpha", "beta", "the and"])
    contract = {**base, "lexical": lexical.manifest, "schema_version": "qdrant-hybrid-v1"}
    for point, vector in zip(points, lexical.document_vectors, strict=True):
        point["vector"][SPARSE_NAME] = vector
    with QdrantRepository(url, "test_hybrid_" + uuid4().hex[:12]) as repo:
        try:
            repo.ensure_collection(contract, sparse_vectors=SPARSE_CONFIG)
            repo.upsert(points[:2])
            with pytest.raises(ValueError, match="count"):
                indexing.verify_hybrid(repo, contract, points)
            repo.upsert(points)
            repo.upsert(points)
            assert indexing.verify_hybrid(repo, contract, points)["sparse_vectors_verified"] == 5
            branches, _ = search_branches(
                repo,
                contract,
                lexical,
                [1, 0, 0],
                "alpha",
                demographics={"age_days": 70 * 365.2425, "sex": "Male"},
            )
            for hits in branches.values():
                assert [h["payload"]["trial_id"] for h in hits] == ["NCT00000001", "NCT00000003"]
            changed = copy.deepcopy(points[0])
            changed["vector"][SPARSE_NAME]["values"][0] += 0.1
            repo.upsert([changed])
            with pytest.raises(ValueError, match="stored sparse vector"):
                indexing.verify_hybrid(repo, contract, points)
            repo.upsert(points)
            wrong = copy.deepcopy(contract)
            wrong["lexical"]["k1"] = 9
            with pytest.raises(ValueError, match="different artifact"):
                repo.ensure_collection(wrong, sparse_vectors=SPARSE_CONFIG)
            assert indexing.verify_hybrid(repo, contract, points)["points"] == 5
        finally:
            # Only the random collection owned by this test is deleted.
            repo.request("DELETE", repo.path)
