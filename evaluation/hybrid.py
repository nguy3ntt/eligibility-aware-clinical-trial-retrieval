"""Controlled dense/sparse/RRF ablation on a frozen bounded synthetic-topic diagnostic."""

import argparse
import json
import time
from pathlib import Path

import bm25s
import httpx
import numpy as np

from backend.app.repositories.qdrant import QdrantRepository
from backend.app.services.retrieval.hybrid import (
    CANDIDATE_DEPTH,
    RRF_K,
    rank_results,
    search_branches,
)
from backend.app.services.retrieval.sparse import PARAMETERS
from evaluation.baselines.bm25 import _evaluate, _write_run
from evaluation.baselines.filters import extract_topic_demographics
from evaluation.qdrant_smoke import reference_compatible
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import load_qrels, load_topics
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash
from pipelines.indexing.hybrid import prepare_hybrid, verify_hybrid


def reference_lexical_scores(model, tokens: list[str], documents: int):
    # bm25s 0.3.11 indexes the first query token and cannot score an empty list.
    return model.get_scores(tokens) if tokens else np.zeros(documents, dtype=np.float32)


def check_branch(hits, reference, *, depth=100, tolerance=1e-5) -> float:
    expected = sorted(reference.items(), key=lambda p: (-p[1], p[0]))[:depth]
    ids = [h["payload"]["trial_id"] for h in hits]
    if len(hits) != len(expected) or len(ids) != len(set(ids)):
        raise ValueError("branch reference count/uniqueness mismatch")
    errors = []
    for hit, (_, score) in zip(hits, expected, strict=True):
        trial_id = hit["payload"]["trial_id"]
        if trial_id not in reference or not np.isfinite(hit["score"]):
            raise ValueError("branch returned an invalid or contradictory trial")
        errors.extend([abs(hit["score"] - reference[trial_id]), abs(hit["score"] - score)])
    maximum = max(errors, default=0)
    if maximum > tolerance:
        raise ValueError("branch scores/ranking differ from the independent reference")
    return maximum


def evaluate(repo, index: Path, topics_path: Path, qrels_path: Path, encoder, output: Path) -> dict:
    contract, rows, vectors, lexical, points = prepare_hybrid(index)
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("query model differs from saved artifact")
    verify_hybrid(repo, contract, points)
    config = repo.info()["config"]
    topics = load_topics(topics_path.read_bytes())
    qrels = load_qrels(qrels_path.read_bytes(), {t["topic_id"] for t in topics})
    pool_ids = {row["trial_id"] for row in rows}
    judged = [q for q in qrels if q["trial_id"] in pool_ids]
    if {q["topic_id"] for q in judged} != {t["topic_id"] for t in topics}:
        raise ValueError("each topic requires judgments in the bounded pool")
    texts = [r["representations"]["title_conditions"] for r in rows]
    reference_bm25 = bm25s.BM25(k1=PARAMETERS["k1"], b=PARAMETERS["b"], method="lucene")
    reference_bm25.index(
        bm25s.tokenize(
            texts,
            return_ids=True,
            show_progress=False,
            lower=True,
            token_pattern=PARAMETERS["token_pattern"],
            stopwords="english",
        ),
        show_progress=False,
    )
    encoded = encoder.encode([t["text"] for t in topics])
    systems, all_queries, checks = {}, {}, []
    for mode in ("none", "age_sex"):
        rankings = {method: {} for method in ("dense", "sparse", "hybrid")}
        provenance = []
        for topic, vector in zip(topics, encoded.vectors, strict=True):
            text, topic_id = topic["text"], topic["topic_id"]
            facts = extract_topic_demographics(text) if mode == "age_sex" else {}
            branches, audit = search_branches(
                repo, contract, lexical, vector.tolist(), text, demographics=facts
            )
            dense_scores = np.asarray(vectors) @ vector
            tokens = bm25s.tokenize(
                [text],
                return_ids=False,
                show_progress=False,
                lower=True,
                token_pattern=PARAMETERS["token_pattern"],
                stopwords="english",
            )[0]
            sparse_scores = reference_lexical_scores(reference_bm25, tokens, len(rows))
            references = {"dense": {}, "sparse": {}}
            for row, dense_score, sparse_score in zip(
                rows, dense_scores, sparse_scores, strict=True
            ):
                if reference_compatible(facts, row["filter_metadata"]):
                    references["dense"][row["trial_id"]] = float(dense_score)
                    if sparse_score > 0:
                        references["sparse"][row["trial_id"]] = float(sparse_score)
            checks.append(
                {
                    "topic_id": topic_id,
                    "filter": mode,
                    "dense_max_error": check_branch(
                        branches["dense"], references["dense"], tolerance=1e-6
                    ),
                    "sparse_max_error": check_branch(branches["sparse"], references["sparse"]),
                    "filter_facts": facts,
                    "lexical_query": audit,
                }
            )
            outputs = {}
            for method in rankings:
                outputs[method] = rank_results(branches, method=method, k=100)
                rankings[method][topic_id] = [(r["trial_id"], r["score"]) for r in outputs[method]]
            provenance.append(
                {
                    "topic_id": topic_id,
                    "filter_facts": facts,
                    "lexical_query": audit,
                    "branches": branches,
                    "results": outputs,
                }
            )
        write_json(output / f"{mode}-provenance.json", provenance)
        for method, ranking in rankings.items():
            name = f"{method}-{mode}"
            _write_run(output / f"{name}.run", ranking, f"m5{method}{mode}")
            aggregate, per_query = _evaluate(ranking, judged)
            write_json(
                output / f"{name}-metrics.json", {"aggregate": aggregate, "per_query": per_query}
            )
            systems[name] = aggregate
            all_queries[name] = per_query
    comparisons = {}
    for mode in ("none", "age_sex"):
        hybrid = systems[f"hybrid-{mode}"]["ndcg_at_10"]
        comparisons[mode] = {
            "hybrid_exceeds_both_mean_ndcg_at_10": all(
                hybrid > systems[f"{b}-{mode}"]["ndcg_at_10"] for b in ("dense", "sparse")
            )
        }
        for baseline in ("dense", "sparse"):
            deltas = {
                topic: all_queries[f"hybrid-{mode}"][topic]["ndcg_at_10"] - values["ndcg_at_10"]
                for topic, values in all_queries[f"{baseline}-{mode}"].items()
            }
            comparisons[mode][baseline] = {
                "mean_ndcg_at_10_delta": float(np.mean(list(deltas.values()))),
                "wins": sum(d > 1e-12 for d in deltas.values()),
                "losses": sum(d < -1e-12 for d in deltas.values()),
                "ties": sum(abs(d) <= 1e-12 for d in deltas.values()),
                "largest_gains": sorted(
                    ((t, d) for t, d in deltas.items() if d > 1e-12), key=lambda p: (-p[1], p[0])
                )[:5],
                "largest_losses": sorted(
                    ((t, d) for t, d in deltas.items() if d < -1e-12), key=lambda p: (p[1], p[0])
                )[:5],
            }
    verify_hybrid(repo, contract, points)
    if repo.info()["config"] != config:
        raise ValueError("collection configuration changed during evaluation")
    return {
        "status": "complete",
        "version": "hybrid-ablation-v1",
        "contract": contract,
        "collection": repo.collection,
        "collection_config": config,
        "server_version": repo.version(),
        "topics": len(topics),
        "pool_judgments": len(judged),
        "all_source_judgments": len(qrels),
        "topics_sha256": file_hash(topics_path),
        "qrels_sha256": file_hash(qrels_path),
        "rrf_k": RRF_K,
        "branch_weights": {"dense": 1, "sparse": 1},
        "candidate_depth_per_branch": CANDIDATE_DEPTH,
        "bounded_fetch_depth": len(rows),
        "dense_mode": "exact",
        "systems": systems,
        "comparisons": comparisons,
        "checks": checks,
        "query_truncations": sum(c > encoder.spec.max_tokens for c in encoded.token_counts),
        "encoder": encoder.metadata,
        "benchmark_comparable": False,
        "eligibility_assessments_performed": 0,
        "code_sha256": {
            str(p): file_hash(p)
            for p in (
                Path(__file__),
                Path("backend/app/services/retrieval/hybrid.py"),
                Path("backend/app/services/retrieval/sparse.py"),
                Path("backend/app/repositories/qdrant.py"),
                Path("pipelines/indexing/hybrid.py"),
                Path("evaluation/metrics/retrieval.py"),
                Path("evaluation/baselines/filters.py"),
            )
        },
        "limitations": "Judgment-selected diagnostic; not a held-out or full-corpus benchmark. "
        "Metrics restrict qrels to the pool; unjudged pairs receive zero gain. "
        "Sparse retrieval returns positive matches only, with no zero-score padding. "
        "RRF parameters were fixed before this evaluation; no superiority is presumed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collection", type=local_id, default="trials_hybrid_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.exit(1, f"Use a fresh output ID: {exc}\n")
    write_json(output / "started.json", {"status": "running"})
    try:
        started = time.perf_counter()
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        with QdrantRepository(args.url, args.collection) as repo:
            result = evaluate(
                repo,
                Path("data/processed") / args.index_id,
                args.topics,
                args.qrels,
                encoder,
                output,
            )
        result["total_seconds_including_model_load_and_verification"] = (
            time.perf_counter() - started
        )
        result["files"] = [
            {"name": p.name, "sha256": file_hash(p)}
            for p in sorted(output.iterdir())
            if p.is_file()
        ]
        write_json(output / "experiment.json", result)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "systems": result["systems"],
                    "comparisons": result["comparisons"],
                    "report": str(output),
                },
                indent=2,
            )
        )
    except (ValueError, OSError, httpx.HTTPError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error": str(exc)})
        parser.exit(1, f"Hybrid evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
