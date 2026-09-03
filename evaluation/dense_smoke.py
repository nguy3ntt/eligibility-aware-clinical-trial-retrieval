"""Check saved dense artifacts with real-model repeats and an independent exact reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from evaluation.baselines.dense import exact_top_k
from evaluation.dense_search import search_topic
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.dense_artifacts import load_index
from pipelines.embeddings import MODELS, Encoder, LocalSentenceEncoder, file_hash


def verify_smoke(index: Path, topics_path: Path, encoder: Encoder, topic_ids: list[str]) -> dict:
    manifest, rows, vectors = load_index(index)
    topics = {row["topic_id"]: row for row in load_topics(topics_path.read_bytes())}
    if not topic_ids or any(topic_id not in topics for topic_id in topic_ids):
        raise ValueError("smoke test needs at least one existing synthetic topic ID")
    checks = []
    ids = [row["trial_id"] for row in rows]
    for topic_id in topic_ids:
        result = search_topic(index, topics_path, topic_id, encoder)
        query = encoder.encode([topics[topic_id]["text"]]).vectors[0]
        repeated = encoder.encode([topics[topic_id]["text"]]).vectors[0]
        repeat_error = float(np.max(np.abs(query - repeated)))
        if repeat_error > 1e-6:
            raise ValueError("repeat encoding exceeded the numerical tolerance")
        actual = exact_top_k(vectors, query, ids, k=5, block_size=31)
        reference = sorted(
            zip(ids, np.clip(np.asarray(vectors) @ query, -1.0, 1.0), strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )[:5]
        if [row[0] for row in actual] != [row[0] for row in reference]:
            raise ValueError("blockwise ranking differs from the full-matrix reference")
        if [row["trial_id"] for row in result["results"]] != [row[0] for row in actual]:
            raise ValueError("repeat search changed the ranking")
        score_error = max(abs(a[1] - float(b[1])) for a, b in zip(actual, reference, strict=True))
        if score_error > 1e-6:
            raise ValueError("exact scores exceeded the reference tolerance")
        checks.append(
            {
                "topic_id": topic_id,
                "repeat_max_absolute_error": repeat_error,
                "reference_max_absolute_error": score_error,
                "query_tokens": result["query_tokens"],
                "query_truncated": result["query_truncated"],
                "results": result["results"],
            }
        )
    representation = manifest["template"]["representation"]
    self_texts = [row["representations"][representation] for row in rows[:8]]
    self_vectors = encoder.encode(self_texts).vectors
    cosine = np.asarray(vectors) @ self_vectors.T
    for position in range(len(self_texts)):
        own = float(cosine[position, position])
        if own < 0.9999 or float(cosine[:, position].max()) > own + 1e-5:
            raise ValueError("self-retrieval failed or document/query encoding differs")
    return {
        "status": "passed",
        "scope": "bounded_functionality_only",
        "index_manifest_sha256": file_hash(index / "manifest.json"),
        "smoke_code_sha256": file_hash(Path(__file__)),
        "encoder": encoder.metadata,
        "documents": len(rows),
        "dimensions": manifest["dimension"],
        "queries": checks,
        "self_retrieval_checks": len(self_texts),
        "benchmark_metrics_permitted": False,
        "eligibility_assessments_performed": 0,
        "note": "Operational correctness only; no relevance or BM25 superiority claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, required=True)
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--output-id", type=local_id, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
        index = Path("data/processed") / args.index_id
        manifest, _, _ = load_index(index)
        spec = MODELS[manifest["encoder"]["model"]["alias"]]
        encoder = LocalSentenceEncoder(spec, Path("models"), threads=args.threads)
        report = verify_smoke(index, args.topics, encoder, ["1", "15", "38"])
        write_json(output / "smoke.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "queries": len(report["queries"]),
                    "self_retrieval_checks": report["self_retrieval_checks"],
                }
            )
        )
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Dense smoke verification failed: {exc}\n")


if __name__ == "__main__":
    main()
