"""Frozen bounded reranking quality/latency comparison; no default promotion."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from backend.app.services.retrieval.reranker import LocalReranker, reorder
from backend.app.services.retrieval.sparse import SparseBM25
from evaluation.baselines.bm25 import _evaluate
from evaluation.baselines.filters import extract_topic_demographics
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.connectors.trec import load_qrels
from pipelines.criteria.artifacts import file_hash, local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder
from pipelines.indexing.qdrant import artifact_contract
from pipelines.rerank import EVIDENCE_ID, INDEX_ID, TOPICS, candidates, explain
from pipelines.reranking_data import load_evidence

DEPTHS = (10, 20)
REPEATS = 2


def fingerprints():
    names = (
        "backend/app/services/retrieval/reranker.py",
        "backend/app/services/explanations/evidence.py",
        "backend/app/services/retrieval/sparse.py",
        "backend/app/services/eligibility/rules.py",
        "backend/app/services/patient_extraction/extractor.py",
        "backend/app/services/patient_extraction/rules.py",
        "backend/app/schemas/eligibility.py",
        "backend/app/schemas/patient.py",
        "backend/app/schemas/criteria.py",
        "pipelines/criteria/parser.py",
        "pipelines/reranking_data.py",
        "pipelines/rerank.py",
        "pipelines/prepare_reranker.py",
        "pipelines/dense_artifacts.py",
        "pipelines/embeddings.py",
        "pipelines/indexing/qdrant.py",
        "pipelines/render_trials.py",
        "pipelines/connectors/synthetic_cases.py",
        "pipelines/connectors/trec.py",
        "evaluation/reranking.py",
        "evaluation/baselines/filters.py",
        "evaluation/qdrant_smoke.py",
        "evaluation/metrics/retrieval.py",
    )
    return {name: file_hash(Path(name)) for name in names}


def comparison(base, changed):
    deltas = {t: changed[t]["ndcg_at_10"] - v["ndcg_at_10"] for t, v in base.items()}
    ordered = sorted(deltas.items(), key=lambda p: (p[1], p[0]))
    return {
        "mean_ndcg_at_10_delta": float(np.mean(list(deltas.values()))),
        "wins": sum(d > 1e-12 for d in deltas.values()),
        "losses": sum(d < -1e-12 for d in deltas.values()),
        "ties": sum(abs(d) <= 1e-12 for d in deltas.values()),
        "largest_losses": ordered[:5],
        "largest_gains": ordered[-5:][::-1],
        "per_query_delta": deltas,
    }


def latency_summary(values):
    return {
        "samples": len(values),
        "median_seconds": float(np.median(values)),
        "p95_seconds": float(np.percentile(values, 95)),
    }


def evaluate(args, output):
    started = time.perf_counter()
    index = Path("data/processed") / args.index_id
    contract, rows, vectors = artifact_contract(index)
    evidence_root = Path("data/processed") / args.evidence_id
    records = load_evidence(evidence_root, rows, contract["artifact_sha256"])
    cases = load_cases(args.topics, topics=True)
    if len(cases) != 50:
        raise ValueError("frozen diagnostic requires all 50 synthetic topics")
    topic_ids = {c.case_id.split(":")[-1] for c in cases}
    qrels = load_qrels(args.qrels.read_bytes(), topic_ids)
    pool = {r["trial_id"] for r in rows}
    judged = [q for q in qrels if q["trial_id"] in pool]
    if {q["topic_id"] for q in judged} != topic_ids:
        raise ValueError("every diagnostic topic needs judgments")
    encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("dense model/artifact mismatch")
    model = LocalReranker()
    lexical = SparseBM25([r["representations"]["title_conditions"] for r in rows])
    loading = time.perf_counter() - started
    # Warm both models before recording per-query timings.
    encoder.encode([cases[0].text])
    model.score(cases[0], [rows[0]["representations"]["summary"]])
    systems = {name: {} for name in ("bm25", "dense", "rerank-10", "rerank-20")}
    predictions, explanations, timings = [], [], []
    for position, case in enumerate(cases):
        topic_id = case.case_id.split(":")[-1]
        facts = extract_topic_demographics(case.text)
        t = time.perf_counter()
        encoded = encoder.encode([case.text])
        dense = candidates(rows, vectors @ encoded.vectors[0], facts)
        retrieval_seconds = time.perf_counter() - t
        query, lexical_audit = lexical.query(case.text)
        weights = dict(zip(query["indices"], query["values"], strict=True))
        lexical_scores = [
            sum(weights.get(i, 0) * v for i, v in zip(d["indices"], d["values"], strict=True))
            for d in lexical.document_vectors
        ]
        sparse = [r for r in candidates(rows, lexical_scores, facts) if r["score"] > 0]
        systems["dense"][topic_id] = [(r["trial_id"], r["score"]) for r in dense]
        systems["bm25"][topic_id] = [(r["trial_id"], r["score"]) for r in sparse]
        if len(dense) < max(DEPTHS):
            raise ValueError("insufficient candidates for fixed diagnostic depths")
        entry = {
            "topic_id": topic_id,
            "case": case.model_dump(mode="json"),
            "filter_facts": facts,
            "dense": dense,
            "bm25": sparse,
            "lexical_query": lexical_audit,
            "reranked": {},
            "dense_query_tokens": encoded.token_counts[0],
            "dense_query_truncated": encoded.token_counts[0] > encoder.spec.max_tokens,
        }
        topic_timing = {
            "topic_id": topic_id,
            "dense_retrieval_seconds": retrieval_seconds,
            "reranking_seconds": {},
        }
        # Alternate order to reduce systematic timing-order bias, never quality selection.
        for depth in DEPTHS if position % 2 == 0 else DEPTHS[::-1]:
            documents = [
                records[r["trial_id"]]["row"]["representations"]["summary"] for r in dense[:depth]
            ]
            repeated, durations = [], []
            for _ in range(REPEATS):
                t = time.perf_counter()
                repeated.append(model.score(case, documents))
                durations.append(time.perf_counter() - t)
            if repeated[0] != repeated[1]:
                raise ValueError("repeated reranking scores/evidence differ")
            ranked = reorder(dense, repeated[0])
            if {r["trial_id"] for r in ranked} != {r["trial_id"] for r in dense} or [
                r["trial_id"] for r in ranked[depth:]
            ] != [r["trial_id"] for r in dense[depth:]]:
                raise ValueError("reranking changed candidate membership or tail")
            name = f"rerank-{depth}"
            # Metrics use order only; reciprocal rank is an export ordinal, not a fused score.
            systems[name][topic_id] = [(r["trial_id"], 1 / r["rank"]) for r in ranked]
            entry["reranked"][name] = ranked
            topic_timing["reranking_seconds"][name] = durations
        t = time.perf_counter()
        explanations.append(
            {
                "topic_id": topic_id,
                "results": explain(case, entry["reranked"]["rerank-20"], records, 3),
            }
        )
        topic_timing["explanation_seconds"] = time.perf_counter() - t
        predictions.append(entry)
        timings.append(topic_timing)
        print(f"Verified topic {position + 1}/{len(cases)}", flush=True)
    metrics, per_query = {}, {}
    for name, rankings in systems.items():
        metrics[name], per_query[name] = _evaluate(rankings, judged)
    judgments = {(q["topic_id"], q["trial_id"]): q["grade"] for q in judged}
    errors = [
        {
            "topic_id": e["topic_id"],
            "rankings": {
                name: [
                    {"trial_id": trial_id, "source_grade": judgments.get((e["topic_id"], trial_id))}
                    for trial_id, _ in rankings[e["topic_id"]][:10]
                ]
                for name, rankings in systems.items()
            },
        }
        for e in predictions
    ]
    write_json(output / "predictions.json", predictions)
    write_json(output / "explanations.json", explanations)
    write_json(output / "error-analysis.json", errors)
    write_json(
        output / "latency.json",
        {
            "model_artifact_loading_seconds": loading,
            "queries": timings,
            "method": "warm CPU, two repeats per depth, alternating order; not service latency",
            "summary": {
                name: latency_summary([v for t in timings for v in t["reranking_seconds"][name]])
                for name in ("rerank-10", "rerank-20")
            },
            "dense_retrieval": latency_summary([t["dense_retrieval_seconds"] for t in timings]),
            "explanations": latency_summary([t["explanation_seconds"] for t in timings]),
        },
    )
    report = {
        "status": "complete",
        "version": "bounded-reranking-evaluation-v1",
        "contract": contract,
        "model": model.metadata,
        "encoder": encoder.metadata,
        "lexical": lexical.manifest,
        "topics": len(cases),
        "pool_judgments": len(judged),
        "topics_sha256": file_hash(args.topics),
        "qrels_sha256": file_hash(args.qrels),
        "evidence_manifest_sha256": file_hash(evidence_root / "manifest.json"),
        "depths": list(DEPTHS),
        "warm_repeats": REPEATS,
        "metrics": metrics,
        "per_query": per_query,
        "comparisons": {
            name: comparison(per_query["dense"], per_query[name])
            for name in ("rerank-10", "rerank-20")
        },
        "code_sha256": fingerprints(),
        "deterministic_files": {
            n: file_hash(output / n)
            for n in ("predictions.json", "explanations.json", "error-analysis.json")
        },
        "promotion": {"enabled": False, "reason": "judgment_selected_pool_not_held_out"},
        "limitations": "Pooled qrels; unjudged is zero gain, not established irrelevance. "
        "General passage model and truncated summary inputs; no eligibility probability. "
        "No full-corpus/held-out quality, significance or clinical validation claim.",
    }
    write_json(output / "experiment.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default=INDEX_ID)
    parser.add_argument("--evidence-id", type=local_id, default=EVIDENCE_ID)
    parser.add_argument("--topics", type=Path, default=TOPICS)
    parser.add_argument("--qrels", type=Path, default=TOPICS.with_name("qrels2022.txt"))
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh report ID.\n")
    write_json(
        output / "started.json",
        {"status": "running", "depths": list(DEPTHS), "protocol_sha256": file_hash(Path(__file__))},
    )
    try:
        result = evaluate(args, output)
        print(
            json.dumps(
                {"status": result["status"], "metrics": result["metrics"], "report": str(output)},
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(1, f"Reranking evaluation failed ({type(exc).__name__}).\n")


if __name__ == "__main__":
    main()
