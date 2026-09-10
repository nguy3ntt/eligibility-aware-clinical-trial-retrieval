"""Load, verify, or search a bounded hybrid index using synthetic TREC topics only."""

import argparse
import json
from pathlib import Path

import httpx

from backend.app.repositories.qdrant import QdrantRepository
from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.patient_extraction.filters import build_filter_plan
from backend.app.services.retrieval.hybrid import (
    CANDIDATE_DEPTH,
    RRF_K,
    rank_results,
    search_branches,
)
from evaluation.baselines.filters import extract_topic_demographics
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder
from pipelines.indexing.hybrid import load_hybrid, prepare_hybrid, verify_hybrid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["load", "verify", "search"])
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collection", type=local_id, default="trials_hybrid_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path)
    parser.add_argument("--topic-id")
    parser.add_argument("--method", choices=["dense", "sparse", "hybrid"], default="dense")
    parser.add_argument("--filter", choices=["none", "age_sex"], default="age_sex")
    parser.add_argument(
        "--fact-extractor",
        choices=["legacy", "profile"],
        default="legacy",
        help="Explicit profile integration; legacy preserves frozen retrieval runs",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.command == "search" and (args.topics is None or args.topic_id is None):
        parser.error("search requires --topics and --topic-id")
    if not 1 <= args.top_k <= 100:
        parser.error("top-k must be 1..100")
    try:
        index = Path("data/processed") / args.index_id
        with QdrantRepository(args.url, args.collection) as repo:
            if args.command == "load":
                result = load_hybrid(repo, index)
            else:
                contract, _, _, lexical, points = prepare_hybrid(index)
                result = verify_hybrid(repo, contract, points)
                if args.command == "search":
                    topics = {
                        t["topic_id"]: t["text"] for t in load_topics(args.topics.read_bytes())
                    }
                    if args.topic_id not in topics:
                        raise ValueError("unknown synthetic topic ID")
                    text = topics[args.topic_id]
                    encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
                    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
                        raise ValueError("query model differs from saved artifact")
                    encoded = encoder.encode([text])
                    facts = extract_topic_demographics(text) if args.filter == "age_sex" else None
                    profile, filter_plan = None, None
                    if args.fact_extractor == "profile":
                        case = next(
                            c
                            for c in load_cases(args.topics, topics=True)
                            if c.case_id == "trec-ct-2022:" + args.topic_id
                        )
                        profile = extract_profile(case)
                        filter_plan = build_filter_plan(profile)
                        facts = filter_plan["demographics"] if args.filter == "age_sex" else None
                    branches, audit = search_branches(
                        repo,
                        contract,
                        lexical,
                        encoded.vectors[0].tolist(),
                        text,
                        demographics=facts,
                    )
                    result = {
                        "status": "complete",
                        "collection": repo.collection,
                        "topic_id": args.topic_id,
                        "method": args.method,
                        "filter": args.filter,
                        "filter_facts": facts,
                        "fact_extractor": args.fact_extractor,
                        "patient_profile": profile.model_dump(mode="json") if profile else None,
                        "profile_filter_plan": filter_plan,
                        "profile_filters_applied": args.fact_extractor == "profile"
                        and args.filter == "age_sex",
                        "contract": contract,
                        "dense_mode": "exact",
                        "candidate_depth_per_branch": CANDIDATE_DEPTH,
                        "bounded_fetch_depth": contract["documents"],
                        "rrf_k": RRF_K,
                        "branch_counts": {b: len(hits) for b, hits in branches.items()},
                        "lexical_query": audit,
                        "query_truncated": encoded.token_counts[0] > encoder.spec.max_tokens,
                        "missing_branch_meaning": "not retrieved within the branch candidate depth",
                        "eligibility_assessment": "not_performed",
                        "benchmark_comparable": False,
                        "notice": "Potential matches only; requires professional review. "
                        "Missing information does not satisfy a criterion.",
                        "results": [
                            {"rank": i, **item}
                            for i, item in enumerate(
                                rank_results(branches, method=args.method, k=args.top_k), 1
                            )
                        ],
                    }
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(1, f"Hybrid operation failed: {exc}\n")


if __name__ == "__main__":
    main()
