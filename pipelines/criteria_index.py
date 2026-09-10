"""Build, load, verify, and inspect a bounded criterion collection; no patient screening."""

import argparse
import json
from pathlib import Path

import httpx

from backend.app.repositories.criteria import CriteriaRepository
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder
from pipelines.indexing.criteria import build_artifact, load_artifact, verify_collection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "load", "verify", "search"])
    parser.add_argument("--source-id", type=local_id, default="criteria-source-m7-v3")
    parser.add_argument("--index-id", type=local_id, default="criterion-vectors-m7-v3")
    parser.add_argument("--output-id", type=local_id)
    parser.add_argument("--collection", type=local_id, default="criteria_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument(
        "--row", type=int, default=1, help="One-based artifact row used as the source-text query"
    )
    parser.add_argument("--method", choices=["dense", "sparse"], default="dense")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100 or args.row < 1:
        parser.error("row must be positive and top-k must be 1..100")
    output = None
    if args.command == "build":
        if not args.output_id:
            parser.error("build requires a fresh --output-id")
        output = Path("data/processed") / args.output_id
        try:
            output.mkdir(parents=True, exist_ok=False)
        except OSError:
            parser.exit(1, "Use a fresh output ID.\n")
    try:
        if output:
            encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
            result = build_artifact(Path("data/processed") / args.source_id, output, encoder)
        else:
            contract, records, vectors, lexical, points = load_artifact(
                Path("data/processed") / args.index_id
            )
            with CriteriaRepository(args.url, args.collection) as repo:
                if args.command == "load":
                    repo.ensure_criteria(contract)
                    for start in range(0, len(points), 64):
                        repo.upsert(points[start : start + 64])
                result = verify_collection(repo, contract, points)
                if args.command == "search":
                    if args.row > len(records):
                        raise ValueError("query row exceeds criterion artifact")
                    record = records[args.row - 1]
                    audit = {
                        a["criterion_id"]: a
                        for a in json.loads(
                            (
                                Path("data/processed") / args.index_id / "encoding-audit.json"
                            ).read_bytes()
                        )
                    }
                    sparse = args.method == "sparse"
                    query = (
                        lexical.query(record["input_text"])[0]
                        if sparse
                        else vectors[args.row - 1].tolist()
                    )
                    hits = repo.query_criteria(query, contract, sparse=sparse, k=args.top_k)
                    result = {
                        "status": "complete",
                        "collection": repo.collection,
                        "method": args.method,
                        "query_criterion_id": record["criterion_id"],
                        "query_text": record["input_text"],
                        "query_mode": "saved_criterion_text",
                        "query_encoding_audit": audit[record["criterion_id"]],
                        "score_kind": "bm25_lucene" if sparse else "cosine_similarity",
                        "eligibility_assessment": "not_performed",
                        "notice": "Criterion similarity only; requires professional review.",
                        "results": [
                            {
                                "rank": i,
                                "score": h["score"],
                                **h["payload"],
                                "encoding_audit": audit[h["payload"]["criterion_id"]],
                            }
                            for i, h in enumerate(hits, 1)
                        ],
                    }
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError, httpx.HTTPError) as exc:
        if output:
            write_json(
                output / "failure.json", {"status": "failed", "error_type": type(exc).__name__}
            )
        parser.exit(
            1,
            f"Criterion index failed ({type(exc).__name__}); check artifact contracts.\n",
        )


if __name__ == "__main__":
    main()
