"""Reproducible BM25 indexing, retrieval, filtering, and run-file generation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

from evaluation.baselines.filters import (
    extract_topic_demographics,
    not_deterministically_incompatible,
)
from evaluation.metrics.retrieval import aggregate_metrics, query_metrics
from pipelines.connectors.snapshots import sha256, write_json
from pipelines.connectors.trec import load_qrels, load_topics
from pipelines.render_trials import REPRESENTATIONS
from pipelines.render_trials import VERSION as RENDERER_VERSION

VERSION = "bm25-baseline-v1"
PARAMETERS = {
    "method": "lucene",
    "k1": 1.2,
    "b": 0.75,
    "token_pattern": r"(?u)\b\w\w+\b",
    "lower": True,
    "stopwords": "english",
    "stemmer": None,
    "run_depth": 1000,
    "filter_candidate_multiplier": 5,
    "ndcg_gain": "linear_source_grade",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rendered_documents(
    path: Path, representation: str
) -> tuple[list[str], list[str], list[dict[str, str | None]]]:
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation: {representation}")
    trial_ids, texts, metadata = [], [], []
    seen = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            trial_id = row.get("trial_id")
            if (
                not isinstance(trial_id, str)
                or trial_id in seen
                or row.get("renderer_version") != RENDERER_VERSION
            ):
                raise ValueError(f"invalid rendered document at line {line_number}")
            text = row.get("representations", {}).get(representation)
            filters = row.get("filter_metadata")
            if not isinstance(text, str) or not isinstance(filters, dict):
                raise ValueError(f"invalid representation at line {line_number}")
            seen.add(trial_id)
            trial_ids.append(trial_id)
            texts.append(text)
            metadata.append(filters)
    if not trial_ids:
        raise ValueError("rendered corpus is empty")
    return trial_ids, texts, metadata


def _rankings(result: object, topic_ids: list[str]) -> dict[str, list[tuple[str, float]]]:
    rankings = {}
    for topic_id, documents, scores in zip(topic_ids, result.documents, result.scores, strict=True):
        pairs = [
            (str(document), float(score)) for document, score in zip(documents, scores, strict=True)
        ]
        rankings[topic_id] = sorted(pairs, key=lambda pair: (-pair[1], pair[0]))
    return rankings


def _write_run(path: Path, rankings: dict[str, list[tuple[str, float]]], run_name: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for topic_id in sorted(rankings, key=int):
            for rank, (trial_id, score) in enumerate(rankings[topic_id], 1):
                handle.write(f"{topic_id} Q0 {trial_id} {rank} {score:.8f} {run_name}\n")


def _evaluate(
    rankings: dict[str, list[tuple[str, float]]], qrels: list[dict]
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    judgments: dict[str, dict[str, int]] = {}
    for row in qrels:
        judgments.setdefault(row["topic_id"], {})[row["trial_id"]] = row["grade"]
    per_query = {
        topic_id: query_metrics([trial_id for trial_id, _ in ranking], judgments[topic_id])
        for topic_id, ranking in rankings.items()
    }
    return aggregate_metrics(per_query), per_query


def run_experiment(
    documents_dir: Path,
    topics_path: Path,
    qrels_path: Path,
    output: Path,
) -> dict[str, object]:
    try:
        import bm25s
        import numpy as np
    except ImportError as exc:
        raise RuntimeError('install the declared "ml" extra before running BM25') from exc

    rendered_manifest = json.loads((documents_dir / "manifest.json").read_bytes())
    if rendered_manifest.get("status") != "complete":
        raise ValueError("rendered corpus is incomplete")
    documents_path = documents_dir / "documents.jsonl"
    if rendered_manifest["files"][0]["sha256"] != _file_sha256(documents_path):
        raise ValueError("rendered corpus checksum mismatch")
    topics_raw, qrels_raw = topics_path.read_bytes(), qrels_path.read_bytes()
    topics = load_topics(topics_raw)
    qrels = load_qrels(qrels_raw, {topic["topic_id"] for topic in topics})
    topic_ids = [topic["topic_id"] for topic in topics]
    query_texts = [topic["text"] for topic in topics]
    topic_demographics = {
        topic["topic_id"]: extract_topic_demographics(topic["text"]) for topic in topics
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "topic-demographics.json", topic_demographics)
    experiment: dict[str, object] = {
        "status": "running",
        "pipeline_version": VERSION,
        "bm25s_version": importlib.metadata.version("bm25s"),
        "numpy_version": importlib.metadata.version("numpy"),
        "parameters": PARAMETERS,
        "inputs": {
            "documents_manifest_sha256": sha256((documents_dir / "manifest.json").read_bytes()),
            "documents_sha256": _file_sha256(documents_path),
            "topics_sha256": sha256(topics_raw),
            "qrels_sha256": sha256(qrels_raw),
        },
        "topics": len(topics),
        "qrels": len(qrels),
        "representations": {},
    }
    all_per_query: dict[str, dict[str, dict[str, float]]] = {}
    for representation in REPRESENTATIONS:
        started = time.perf_counter()
        trial_ids, texts, filter_metadata = load_rendered_documents(documents_path, representation)
        id_to_index = {trial_id: index for index, trial_id in enumerate(trial_ids)}
        corpus_tokens = bm25s.tokenize(
            texts,
            lower=PARAMETERS["lower"],
            token_pattern=PARAMETERS["token_pattern"],
            stopwords=PARAMETERS["stopwords"],
            return_ids=True,
            show_progress=True,
        )
        del texts
        retriever = bm25s.BM25(k1=PARAMETERS["k1"], b=PARAMETERS["b"], method=PARAMETERS["method"])
        retriever.index(corpus_tokens, show_progress=True)
        index_dir = output / f"index-{representation}"
        retriever.save(index_dir, corpus=trial_ids, show_progress=False)
        query_tokens = bm25s.tokenize(
            query_texts,
            lower=PARAMETERS["lower"],
            token_pattern=PARAMETERS["token_pattern"],
            stopwords=PARAMETERS["stopwords"],
            return_ids=False,
            show_progress=False,
        )
        unfiltered_result = retriever.retrieve(
            query_tokens,
            corpus=trial_ids,
            k=PARAMETERS["run_depth"],
            show_progress=False,
        )
        unfiltered = _rankings(unfiltered_result, topic_ids)
        filtered = {}
        allowed_counts = {}
        for topic_id, tokens in zip(topic_ids, query_tokens, strict=True):
            allowed = np.fromiter(
                (
                    not_deterministically_incompatible(topic_demographics[topic_id], metadata)
                    for metadata in filter_metadata
                ),
                dtype=np.float32,
                count=len(filter_metadata),
            )
            allowed_counts[topic_id] = int(allowed.sum())
            candidate_depth = min(
                len(trial_ids),
                PARAMETERS["run_depth"] * PARAMETERS["filter_candidate_multiplier"],
            )
            result = retriever.retrieve(
                [tokens],
                corpus=trial_ids,
                k=candidate_depth,
                show_progress=False,
                weight_mask=allowed,
            )
            ranking = _rankings(result, [topic_id])[topic_id]
            filtered[topic_id] = [pair for pair in ranking if allowed[id_to_index[pair[0]]] > 0][
                : PARAMETERS["run_depth"]
            ]
            required = min(PARAMETERS["run_depth"], allowed_counts[topic_id])
            if len(filtered[topic_id]) != required:
                raise ValueError("filter mask returned fewer than the requested run depth")
        run_results = {}
        for filter_name, rankings in [("none", unfiltered), ("age_sex", filtered)]:
            run_name = f"b25{representation[:3]}{'f' if filter_name != 'none' else 'u'}"
            run_path = output / f"{representation}-{filter_name}.run"
            _write_run(run_path, rankings, run_name)
            aggregate, per_query = _evaluate(rankings, qrels)
            write_json(
                output / f"{representation}-{filter_name}-metrics.json",
                {"aggregate": aggregate, "per_query": per_query},
            )
            all_per_query[f"{representation}-{filter_name}"] = per_query
            run_results[filter_name] = {
                "run": run_path.name,
                "run_sha256": _file_sha256(run_path),
                "metrics": aggregate,
            }
        experiment["representations"][representation] = {
            "fields": list(REPRESENTATIONS[representation]),
            "documents": len(trial_ids),
            "index_seconds": time.perf_counter() - started,
            "allowed_documents_by_topic": allowed_counts,
            "runs": run_results,
        }
        del corpus_tokens, retriever, trial_ids, filter_metadata
    candidates = [
        (
            details["runs"][filter_name]["metrics"]["ndcg_at_10"],
            representation,
            filter_name,
        )
        for representation, details in experiment["representations"].items()
        for filter_name in details["runs"]
    ]
    _, best_representation, best_filter = max(candidates)
    best_name = f"{best_representation}-{best_filter}"
    best_queries = all_per_query[best_name]
    ordered = sorted(best_queries, key=lambda topic: best_queries[topic]["ndcg_at_10"])
    experiment["selected_run"] = best_name
    experiment["error_analysis_topics"] = {
        "lowest_ndcg_at_10": ordered[:5],
        "highest_ndcg_at_10": ordered[-5:][::-1],
    }
    experiment["status"] = "complete"
    write_json(output / "experiment.json", experiment)
    return experiment
