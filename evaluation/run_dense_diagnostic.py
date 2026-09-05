"""Compare exact dense models and BM25 on a balanced, explicitly non-benchmark pool."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

from evaluation.baselines.bm25 import PARAMETERS as BM25_PARAMETERS
from evaluation.baselines.bm25 import _evaluate, _write_run
from evaluation.baselines.dense import exact_top_k
from evaluation.baselines.filters import (
    extract_topic_demographics,
    not_deterministically_incompatible,
)
from pipelines.connectors.snapshots import sha256, write_json
from pipelines.connectors.trec import load_qrels, load_topics
from pipelines.dense import local_id
from pipelines.dense_artifacts import load_index, select_document_ids
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash

VERSION = "dense-judged-pool-diagnostic-v1"


def balanced_ids(
    qrels: list[dict], *, per_grade: int = 3, seed: str = "m3-diagnostic-v1"
) -> set[str]:
    grouped: dict[tuple[str, int], list[str]] = {}
    for row in qrels:
        grouped.setdefault((row["topic_id"], row["grade"]), []).append(row["trial_id"])
    selected = set()
    for topic_id in sorted({row["topic_id"] for row in qrels}, key=int):
        for grade in (0, 1, 2):
            candidates = grouped.get((topic_id, grade), [])
            if not candidates:
                raise ValueError(f"topic {topic_id} has no grade-{grade} judgments")
            selected.update(
                sorted(
                    candidates,
                    key=lambda trial_id: (
                        hashlib.sha256(
                            f"{seed}:{topic_id}:{grade}:{trial_id}".encode()
                        ).hexdigest(),
                        trial_id,
                    ),
                )[: min(per_grade, len(candidates))]
            )
    return selected


def filtered_rankings(rankings, rows, demographics):
    metadata = {row["trial_id"]: row["filter_metadata"] for row in rows}
    return {
        topic_id: [
            pair
            for pair in ranking
            if not_deterministically_incompatible(demographics[topic_id], metadata[pair[0]])
        ]
        for topic_id, ranking in rankings.items()
    }


def dense_rankings(vectors, rows, query_vectors, topic_ids):
    ids = [row["trial_id"] for row in rows]
    return {
        topic_id: exact_top_k(vectors, vector, ids, k=len(ids))
        for topic_id, vector in zip(topic_ids, query_vectors, strict=True)
    }


def run_diagnostic(
    pool: Path,
    indexes: dict[str, Path],
    topics_path: Path,
    qrels_path: Path,
    output: Path,
    *,
    threads: int = 10,
) -> dict:
    import bm25s

    raw_topics, raw_qrels = topics_path.read_bytes(), qrels_path.read_bytes()
    topics = load_topics(raw_topics)
    qrels = load_qrels(raw_qrels, {topic["topic_id"] for topic in topics})
    pool_ids = {
        json.loads(line)["trial_id"]
        for line in (pool / "documents.jsonl").read_bytes().splitlines()
    }
    judged = [row for row in qrels if row["trial_id"] in pool_ids]
    topic_ids = [topic["topic_id"] for topic in topics]
    query_texts = [topic["text"] for topic in topics]
    demographics = {
        topic["topic_id"]: extract_topic_demographics(topic["text"]) for topic in topics
    }
    output.mkdir(parents=True, exist_ok=False)
    systems = {}
    all_per_query = {}
    rows_reference = None
    for alias, index in indexes.items():
        manifest, rows, vectors = load_index(index)
        if {row["trial_id"] for row in rows} != pool_ids or manifest["template"][
            "representation"
        ] != "title_conditions":
            raise ValueError("dense indexes must contain the same title/conditions pool")
        encoder = LocalSentenceEncoder(MODELS[alias], Path("models"), threads=threads)
        started = time.perf_counter()
        query_vectors = encoder.encode(query_texts).vectors
        rankings = dense_rankings(vectors, rows, query_vectors, topic_ids)
        elapsed = time.perf_counter() - started
        rows_reference = rows
        for filter_name, run in (
            ("none", rankings),
            ("age_sex", filtered_rankings(rankings, rows, demographics)),
        ):
            name = f"{alias}-{filter_name}"
            _write_run(output / f"{name}.run", run, f"d{alias[:3]}{filter_name[:1]}")
            aggregate, per_query = _evaluate(run, judged)
            write_json(
                output / f"{name}-metrics.json", {"aggregate": aggregate, "per_query": per_query}
            )
            systems[name] = {"metrics": aggregate, "run": f"{name}.run"}
            all_per_query[name] = per_query
        systems[alias + "-none"]["query_and_search_seconds"] = elapsed
    rows = rows_reference
    texts = [row["representations"]["title_conditions"] for row in rows]
    ids = [row["trial_id"] for row in rows]
    started = time.perf_counter()
    retriever = bm25s.BM25(k1=BM25_PARAMETERS["k1"], b=BM25_PARAMETERS["b"], method="lucene")
    retriever.index(
        bm25s.tokenize(
            texts, lower=True, stopwords="english", return_ids=True, show_progress=False
        ),
        show_progress=False,
    )
    result = retriever.retrieve(
        bm25s.tokenize(
            query_texts, lower=True, stopwords="english", return_ids=False, show_progress=False
        ),
        corpus=ids,
        k=len(ids),
        show_progress=False,
    )
    bm25_rankings = {
        topic_id: sorted(
            zip(map(str, docs), map(float, scores), strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        for topic_id, docs, scores in zip(topic_ids, result.documents, result.scores, strict=True)
    }
    for filter_name, run in (
        ("none", bm25_rankings),
        ("age_sex", filtered_rankings(bm25_rankings, rows, demographics)),
    ):
        name = f"bm25-{filter_name}"
        _write_run(output / f"{name}.run", run, f"bpool{filter_name[:1]}")
        aggregate, per_query = _evaluate(run, judged)
        write_json(
            output / f"{name}-metrics.json", {"aggregate": aggregate, "per_query": per_query}
        )
        systems[name] = {"metrics": aggregate, "run": f"{name}.run"}
        all_per_query[name] = per_query
    systems["bm25-none"]["index_and_search_seconds"] = time.perf_counter() - started
    selected = max(systems, key=lambda name: systems[name]["metrics"]["ndcg_at_10"])
    result_manifest = {
        "status": "complete",
        "version": VERSION,
        "scope": "balanced_judged_pool_diagnostic",
        "benchmark_comparable": False,
        "topics": len(topics),
        "pool_documents": len(pool_ids),
        "pool_judgments": len(judged),
        "pool_manifest_sha256": file_hash(pool / "manifest.json"),
        "topics_sha256": sha256(raw_topics),
        "qrels_sha256": sha256(raw_qrels),
        "representation": "title_conditions",
        "systems": systems,
        "selected_system": selected,
        "bm25s_version": importlib.metadata.version("bm25s"),
        "eligibility_assessments_performed": 0,
        "limitations": "Pool was selected from qrels and is not an official full-corpus benchmark.",
    }
    write_json(output / "experiment.json", result_manifest)
    return result_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--documents-id", type=local_id, required=True)
    prepare.add_argument("--topics", type=Path, required=True)
    prepare.add_argument("--qrels", type=Path, required=True)
    prepare.add_argument("--pool-id", type=local_id, required=True)
    prepare.add_argument("--per-grade", type=int, default=3)
    run = commands.add_parser("run")
    run.add_argument("--pool-id", type=local_id, required=True)
    run.add_argument("--minilm-index-id", type=local_id, required=True)
    run.add_argument("--pubmedbert-index-id", type=local_id, required=True)
    run.add_argument("--topics", type=Path, required=True)
    run.add_argument("--qrels", type=Path, required=True)
    run.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        topics = load_topics(args.topics.read_bytes())
        qrels = load_qrels(args.qrels.read_bytes(), {topic["topic_id"] for topic in topics})
        ids = balanced_ids(qrels, per_grade=args.per_grade)
        result = select_document_ids(
            Path("data/processed") / args.documents_id,
            Path("data/processed") / args.pool_id,
            ids,
            selection={
                "method": "balanced_qrels_hash",
                "per_grade_per_topic": args.per_grade,
                "seed": "m3-diagnostic-v1",
                "qrels_sha256": file_hash(args.qrels),
            },
        )
    else:
        result = run_diagnostic(
            Path("data/processed") / args.pool_id,
            {
                "minilm": Path("data/processed") / args.minilm_index_id,
                "pubmedbert": Path("data/processed") / args.pubmedbert_index_id,
            },
            args.topics,
            args.qrels,
            Path("evaluation/reports") / args.output_id,
        )
    print(
        json.dumps(
            {
                key: result[key]
                for key in result
                if key in {"status", "documents", "pool_documents", "selected_system"}
            }
        )
    )


if __name__ == "__main__":
    main()
