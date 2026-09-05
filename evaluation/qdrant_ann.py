"""Bounded ANN Recall@10 and paired warm HTTP latency against checked exact neighbors."""

from __future__ import annotations

import argparse
import json
import platform
import random
import time
from pathlib import Path

import httpx
import numpy as np

from backend.app.repositories.qdrant import VECTOR_NAME, QdrantRepository, query_body
from evaluation.baselines.filters import extract_topic_demographics
from evaluation.qdrant_smoke import reference_compatible
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash
from pipelines.indexing.qdrant import artifact_contract
from pipelines.indexing.qdrant_recovery import verify_artifact_collection

EF_VALUES = (10, 32, 128)


def recall_at_k(exact_ids: list[str], ann_ids: list[str]) -> float | None:
    if len(set(exact_ids)) != len(exact_ids) or len(set(ann_ids)) != len(ann_ids):
        raise ValueError("duplicate retrieval IDs")
    if not exact_ids:
        if ann_ids:
            raise ValueError("ANN returned candidates when exact reference is empty")
        return None
    return len(set(exact_ids) & set(ann_ids)) / len(exact_ids)


def graph_telemetry(telemetry: dict) -> dict:
    """The bounded profile requires one populated HNSW segment for unambiguous counters."""
    segments = [
        s
        for shard in telemetry["shards"]
        for s in shard["local"].get("segments", [])
        if s["info"]["num_points"] > 0
    ]
    if len(segments) != 1:
        raise ValueError("diagnostic requires one populated segment; wait for optimization")
    segment = segments[0]
    if segment["config"]["vector_data"][VECTOR_NAME]["index"]["type"] != "hnsw":
        raise ValueError("populated segment has no HNSW graph")
    indexes = [v for v in segment["vector_index_searches"] if v["index_name"] == VECTOR_NAME]
    if len(indexes) != 1:
        raise ValueError("missing named-vector telemetry")
    return {
        "segment_id": segment["info"]["uuid"],
        "counts": {
            k: v["count"] for k, v in indexes[0].items() if isinstance(v, dict) and "count" in v
        },
    }


def telemetry_delta(before: dict, after: dict, ann_requests: int) -> dict:
    if before["segment_id"] != after["segment_id"]:
        raise ValueError("graph changed during measurement; rerun with no concurrent writes")
    keys = before["counts"].keys() | after["counts"].keys()
    delta = {k: after["counts"].get(k, 0) - before["counts"].get(k, 0) for k in keys}
    # Every query includes the artifact filter. This counter is the HNSW path in 1.19.0.
    if (
        any(v < 0 for v in delta.values())
        or delta.get("filtered_large_cardinality", 0) != ann_requests
    ):
        raise ValueError("telemetry does not confirm one graph search per ANN request")
    if delta.get("filtered_small_cardinality", 0) or delta.get("filtered_plain", 0):
        raise ValueError("ANN measurement fell back to a scan")
    if delta.get("filtered_exact", 0) != ann_requests or any(
        value
        for key, value in delta.items()
        if key not in {"filtered_large_cardinality", "filtered_exact"}
    ):
        raise ValueError("unexpected concurrent search or fallback during measurement")
    return delta


def latency_summary(values: list[float]) -> dict:
    if not values or not all(np.isfinite(v) and v >= 0 for v in values):
        raise ValueError("latency samples must be finite and nonnegative")
    return {
        "samples": len(values),
        "median_ms": float(np.median(values)),
        "p95_ms": float(np.percentile(values, 95)),
        "minimum_ms": min(values),
    }


def evaluate_ann(repo, index: Path, topics_path: Path, encoder, *, repeats: int = 3) -> dict:
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1..10")
    contract, rows, vectors = artifact_contract(index)
    if encoder.metadata["model"] != contract["model"] or (
        encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]
    ):
        raise ValueError("query model differs from artifact")
    verify_artifact_collection(repo, index)
    config = repo.hnsw_ready(contract)["config"]
    topics = load_topics(topics_path.read_bytes())
    encoded = encoder.encode([t["text"] for t in topics])
    rng = random.Random(20260905)
    configurations = []
    for mode in ("none", "age_sex"):
        cases = []
        for topic, query in zip(topics, encoded.vectors, strict=True):
            facts = extract_topic_demographics(topic["text"]) if mode == "age_sex" else {}
            scores = np.asarray(vectors) @ query
            eligible = {
                r["trial_id"]: float(s)
                for r, s in zip(rows, scores, strict=True)
                if reference_compatible(facts, r["filter_metadata"])
            }
            matrix_top = sorted(eligible.items(), key=lambda p: (-p[1], p[0]))[:10]
            body = query_body(query.tolist(), contract, k=10, demographics=facts)
            exact = repo.query_points(body)
            check_hits(exact, eligible)
            if len(exact) != len(matrix_top) or any(
                abs(h["score"] - ref[1]) > 1e-6 for h, ref in zip(exact, matrix_top, strict=True)
            ):
                raise ValueError("exact server neighbors differ from direct-matrix reference")
            cases.append(
                {
                    "topic_id": topic["topic_id"],
                    "body": body,
                    "eligible": eligible,
                    "exact_ids": [h["payload"]["trial_id"] for h in exact],
                }
            )
        for ef in EF_VALUES:
            # Warm every query and both modes once, outside the timing/counter window.
            for case in cases:
                repo.query_points(case["body"])
                repo.query_points({**case["body"], "params": {"exact": False, "hnsw_ef": ef}})
            before = graph_telemetry(repo.collection_telemetry())
            measurements = []
            for repeat in range(repeats):
                order = list(range(len(cases)))
                rng.shuffle(order)
                for i in order:
                    case = cases[i]
                    methods = ["exact", "ann"]
                    rng.shuffle(methods)
                    pair = {}
                    for method in methods:
                        body = (
                            case["body"]
                            if method == "exact"
                            else {**case["body"], "params": {"exact": False, "hnsw_ef": ef}}
                        )
                        start = time.perf_counter_ns()
                        hits = repo.query_points(body)
                        ms = (time.perf_counter_ns() - start) / 1e6
                        check_hits(hits, case["eligible"])
                        ids = [h["payload"]["trial_id"] for h in hits]
                        if method == "exact" and ids != case["exact_ids"]:
                            raise ValueError("exact rankings changed during experiment")
                        pair[method] = {"ids": ids, "milliseconds": ms}
                    measurements.append(
                        {
                            "topic_id": case["topic_id"],
                            "repeat": repeat,
                            "exact": pair["exact"],
                            "ann": pair["ann"],
                            "recall_at_10": recall_at_k(pair["exact"]["ids"], pair["ann"]["ids"]),
                        }
                    )
            after = graph_telemetry(repo.collection_telemetry())
            counts = telemetry_delta(before, after, len(measurements))
            recalls = [m["recall_at_10"] for m in measurements if m["recall_at_10"] is not None]
            configurations.append(
                {
                    "filter": mode,
                    "hnsw_ef": ef,
                    "mean_recall_at_10": float(np.mean(recalls)) if recalls else None,
                    "minimum_recall_at_10": min(recalls, default=None),
                    "empty_reference_samples": len(measurements) - len(recalls),
                    "exact_latency": latency_summary(
                        [m["exact"]["milliseconds"] for m in measurements]
                    ),
                    "ann_latency": latency_summary(
                        [m["ann"]["milliseconds"] for m in measurements]
                    ),
                    "graph_segment_id": before["segment_id"],
                    "search_counter_delta": counts,
                    "measurements": measurements,
                }
            )
    verify_artifact_collection(repo, index)
    if repo.hnsw_ready(contract)["config"] != config:
        raise ValueError("collection configuration changed during experiment")
    return {
        "status": "complete",
        "version": "qdrant-ann-evaluation-v1",
        "scope": "bounded diagnostic (at most 512 trials); not a full-corpus benchmark",
        "contract": contract,
        "server_version": repo.version(),
        "collection": repo.collection,
        "collection_config": config,
        "encoder": encoder.metadata,
        "query_truncations": sum(t > encoder.spec.max_tokens for t in encoded.token_counts),
        "topics_sha256": file_hash(topics_path),
        "topics": len(topics),
        "k": 10,
        "repeats": repeats,
        "warmups_per_query_per_method": 1,
        "seed": 20260905,
        "latency_boundary": "warm sequential HTTP, JSON encoding/decoding and result sorting; "
        "excludes embeddings, integrity checks, telemetry and startup",
        "recall_definition": "strict ID overlap / exact reference size (min(10, available)); "
        "empty references are excluded, tied cutoff IDs may differ",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "httpx": httpx.__version__,
            "numpy": np.__version__,
        },
        "code_sha256": {
            str(p): file_hash(p)
            for p in (
                Path(__file__),
                Path("backend/app/repositories/qdrant.py"),
                Path("evaluation/baselines/filters.py"),
                Path("evaluation/qdrant_smoke.py"),
                Path("pipelines/indexing/qdrant.py"),
            )
        },
        "configurations": configurations,
        "benchmark_comparable": False,
        "eligibility_assessments_performed": 0,
        "limitations": "Judgment-selected small pool; no full-corpus relevance or speed claim. "
        "Single writer and no other queries allowed during telemetry checks. "
        "Graph rebuilds need not be byte-identical; reevaluate after rebuild.",
    }


def check_hits(hits: list[dict], eligible: dict[str, float]) -> None:
    ids = [h["payload"]["trial_id"] for h in hits]
    if len(ids) != len(set(ids)) or len(ids) > 10:
        raise ValueError("invalid result cardinality")
    for hit in hits:
        trial_id = hit["payload"]["trial_id"]
        if trial_id not in eligible or not np.isfinite(hit["score"]):
            raise ValueError("result contradicts artifact/filter reference")
        if abs(hit["score"] - eligible[trial_id]) > 1e-6:
            raise ValueError("result score differs from stored vector reference")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collection", type=local_id, default="trials_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--output-id", type=local_id, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.exit(1, f"Use a fresh output ID: {exc}\n")
    write_json(output / "started.json", {"status": "running"})
    try:
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        with QdrantRepository(args.url, args.collection) as repo:
            report = evaluate_ann(
                repo,
                Path("data/processed") / args.index_id,
                args.topics,
                encoder,
                repeats=args.repeats,
            )
        write_json(output / "ann.json", report)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "report": str(output / "ann.json"),
                    "configurations": [
                        {k: v for k, v in c.items() if k != "measurements"}
                        for c in report["configurations"]
                    ],
                },
                indent=2,
            )
        )
    except (ValueError, OSError, httpx.HTTPError) as exc:
        write_json(output / "ann.json", {"status": "failed", "error": str(exc)})
        parser.exit(1, f"ANN evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
