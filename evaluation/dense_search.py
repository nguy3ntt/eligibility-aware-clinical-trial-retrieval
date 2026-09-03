"""Search the bounded dense sample using only saved synthetic TREC topics."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from evaluation.baselines.dense import exact_top_k
from pipelines.connectors.snapshots import sha256
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.dense_artifacts import load_index
from pipelines.embeddings import MODELS, Encoder, LocalSentenceEncoder, file_hash


def search_topic(
    index: Path,
    topics_path: Path,
    topic_id: str,
    encoder: Encoder,
    *,
    k: int = 5,
) -> dict:
    manifest, rows, vectors = load_index(index)
    if (
        manifest["encoder"]["model"] != asdict(encoder.spec)
        or manifest["dimension"] != encoder.spec.dimension
        or manifest["encoder"]["snapshot_sha256"] != encoder.metadata["snapshot_sha256"]
        or manifest["encoder"].get("normalization") != "l2"
        or manifest["encoder"].get("prompt") != ""
    ):
        raise ValueError("query encoder does not match the saved document encoder")
    raw = topics_path.read_bytes()
    topics = {row["topic_id"]: row for row in load_topics(raw)}
    if topic_id not in topics:
        raise ValueError("topic ID is not present in the supplied synthetic topics")
    if not 1 <= k <= 100:
        raise ValueError("top-k must be 1..100")
    started = time.perf_counter()
    query = encoder.encode([topics[topic_id]["text"]])
    encoded_at = time.perf_counter()
    ranking = exact_top_k(vectors, query.vectors[0], [row["trial_id"] for row in rows], k=k)
    finished = time.perf_counter()
    lookup = {row["trial_id"]: row for row in rows}
    return {
        "status": "complete",
        "scope": "bounded_smoke_test",
        "synthetic": True,
        "topic_id": topic_id,
        "topics_sha256": sha256(raw),
        "index_manifest_sha256": file_hash(index / "manifest.json"),
        "model": asdict(encoder.spec),
        "query_encoder": encoder.metadata,
        "search_version": "exact-cosine-v1",
        "search_code_sha256": file_hash(Path(__file__).parent / "baselines" / "dense.py"),
        "documents_searched": len(rows),
        "query_seconds": encoded_at - started,
        "search_seconds": finished - encoded_at,
        "query_tokens": query.token_counts[0],
        "query_truncated": query.token_counts[0] > encoder.spec.max_tokens,
        "score_type": "cosine_similarity_not_eligibility_probability",
        "benchmark_metrics_permitted": False,
        "eligibility_assessment": "not_performed",
        "safety": "Synthetic cases only; retrieval candidates require professional review.",
        "results": [
            {
                "rank": rank,
                "trial_id": trial_id,
                "cosine_similarity": score,
                "title": lookup[trial_id]["representations"]["title_conditions"].split("\n")[0],
                "source": lookup[trial_id]["source"],
                "content_sha256": lookup[trial_id]["content_sha256"],
            }
            for rank, (trial_id, score) in enumerate(ranking, 1)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, required=True)
    parser.add_argument("--topics", type=Path, required=True, help="Synthetic TREC topics XML only")
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        index = Path("data/processed") / args.index_id
        manifest, _, _ = load_index(index)
        spec = MODELS[manifest["encoder"]["model"]["alias"]]
        encoder = LocalSentenceEncoder(spec, Path("models"), threads=args.threads)
        print(
            json.dumps(
                search_topic(index, args.topics, args.topic_id, encoder, k=args.top_k),
                ensure_ascii=True,
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Dense search failed: {exc}\n")


if __name__ == "__main__":
    main()
