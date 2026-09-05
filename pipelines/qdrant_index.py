"""Load, verify, or search local Qdrant using an existing checked MiniLM artifact."""

import argparse
import json
from pathlib import Path

import httpx

from backend.app.repositories.qdrant import QdrantRepository
from evaluation.baselines.filters import extract_topic_demographics
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder
from pipelines.indexing.qdrant import artifact_contract, import_index, make_point, verify_import
from pipelines.indexing.qdrant_recovery import create_backup, rebuild_index, restore_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["load", "verify", "search", "configure-ann", "snapshot", "restore", "rebuild"],
    )
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collection", type=local_id, default="trials_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path)
    parser.add_argument("--topic-id")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--filter", choices=["none", "age_sex"], default="none")
    parser.add_argument("--mode", choices=["exact", "ann"], default="exact")
    parser.add_argument("--hnsw-ef", type=int, default=32)
    parser.add_argument("--backup-id", type=local_id)
    parser.add_argument("--report-id", type=local_id)
    args = parser.parse_args()
    if args.command == "search" and (args.topics is None or args.topic_id is None):
        parser.error("search requires --topics and --topic-id")
    if args.command in {"snapshot", "restore"} and not args.backup_id:
        parser.error("snapshot/restore requires --backup-id")
    if args.command in {"restore", "rebuild"} and (
        args.collection == "trials_v1" or not args.report_id
    ):
        parser.error("restore/rebuild requires a new --collection and a fresh --report-id")
    report_path = None
    try:
        if args.command in {"restore", "rebuild"}:
            report_dir = Path("evaluation/reports") / args.report_id
            report_dir.mkdir(parents=True, exist_ok=False)
            report_path = report_dir / "recovery.json"
            write_json(
                report_dir / "started.json", {"status": "running", "operation": args.command}
            )
        index = Path("data/processed") / args.index_id
        with QdrantRepository(args.url, args.collection) as repo:
            if args.command == "load":
                result = import_index(repo, index)
            elif args.command == "snapshot":
                result = create_backup(
                    repo, index, Path("artifacts/qdrant-backups") / args.backup_id
                )
            elif args.command == "restore":
                result = restore_backup(
                    repo, index, Path("artifacts/qdrant-backups") / args.backup_id
                )
            elif args.command == "rebuild":
                result = rebuild_index(repo, index)
            else:
                contract, rows, vectors = artifact_contract(index)
                if args.command in {"verify", "configure-ann"}:
                    points = [
                        make_point(row, vector, contract)
                        for row, vector in zip(rows, vectors, strict=True)
                    ]
                    result = verify_import(repo, points, contract)
                    if args.command == "configure-ann":
                        info = repo.configure_hnsw(contract)
                        result = {
                            **result,
                            "indexed_vectors": info["indexed_vectors_count"],
                            "hnsw_config": info["config"]["hnsw_config"],
                        }
                else:
                    repo.version()
                    # Bounded diagnostic: check evidence as well as count before returning it.
                    points = [
                        make_point(row, vector, contract)
                        for row, vector in zip(rows, vectors, strict=True)
                    ]
                    verify_import(repo, points, contract)
                    topics = {t["topic_id"]: t for t in load_topics(args.topics.read_bytes())}
                    if args.topic_id not in topics:
                        raise ValueError("unknown synthetic topic ID")
                    text = topics[args.topic_id]["text"]
                    encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
                    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
                        raise ValueError("query model snapshot differs from the indexed model")
                    encoded = encoder.encode([text])
                    demographics = (
                        extract_topic_demographics(text) if args.filter == "age_sex" else None
                    )
                    hits = repo.search(
                        encoded.vectors[0].tolist(),
                        contract,
                        k=args.top_k,
                        demographics=demographics,
                        exact=args.mode == "exact",
                        hnsw_ef=args.hnsw_ef,
                    )
                    result = {
                        "status": "complete",
                        "collection": args.collection,
                        "search_mode": args.mode,
                        "hnsw_ef": args.hnsw_ef if args.mode == "ann" else None,
                        "filter": args.filter,
                        "filter_facts": demographics,
                        "topic_id": args.topic_id,
                        "documents": len(rows),
                        "benchmark_comparable": False,
                        "eligibility_assessment": "not_performed",
                        "notice": "Potential matches only; requires professional review. "
                        "Missing information is not evidence of satisfying a criterion.",
                        "query_truncated": encoded.token_counts[0] > encoder.spec.max_tokens,
                        "results": [
                            {"rank": i, "cosine_similarity": p["score"], **p["payload"]}
                            for i, p in enumerate(hits, 1)
                        ],
                    }
        if report_path:
            write_json(report_path, result)
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        if report_path:
            write_json(
                report_path, {"status": "failed", "operation": args.command, "error": str(exc)}
            )
        parser.exit(1, f"Qdrant operation failed: {exc}\n")


if __name__ == "__main__":
    main()
