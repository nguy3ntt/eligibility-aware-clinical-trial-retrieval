"""Compare local-server exact search with a direct matrix reference on synthetic topics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import numpy as np

from backend.app.repositories.qdrant import QdrantRepository
from evaluation.baselines.filters import extract_topic_demographics, trial_age_days
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import load_topics
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash
from pipelines.indexing.qdrant import artifact_contract, make_point, verify_import


def reference_compatible(facts: dict, metadata: dict) -> bool:
    """Independent filter oracle over original strings, not Qdrant payload expressions."""
    age = facts.get("age_days")
    if age is not None:
        minimum = trial_age_days(metadata.get("minimum_age"))
        maximum = trial_age_days(metadata.get("maximum_age"))
        if minimum is not None and age < minimum - 1e-8:
            return False
        if maximum is not None and age > maximum + 1e-8:
            return False
    sex = (metadata.get("sex") or "").lower().strip()
    return not (
        facts.get("sex") in {"Male", "Female"}
        and sex in {"male", "female"}
        and facts["sex"].lower() != sex
    )


def verify_exact(repo, index: Path, topics_path: Path, encoder) -> dict:
    contract, rows, vectors = artifact_contract(index)
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("query model snapshot differs from artifact")
    points = [make_point(row, v, contract) for row, v in zip(rows, vectors, strict=True)]
    verification = verify_import(repo, points, contract)
    topics = load_topics(topics_path.read_bytes())
    queries = encoder.encode([t["text"] for t in topics]).vectors
    checks = []
    for topic, query in zip(topics, queries, strict=True):
        scores = np.asarray(vectors) @ query
        for mode in ("none", "age_sex"):
            facts = extract_topic_demographics(topic["text"]) if mode == "age_sex" else {}
            reference = sorted(
                [
                    (row["trial_id"], float(score))
                    for row, score in zip(rows, scores, strict=True)
                    if reference_compatible(facts, row["filter_metadata"])
                ],
                key=lambda item: (-item[1], item[0]),
            )[:10]
            hits = repo.search(query.tolist(), contract, k=10, demographics=facts)
            expected_count = len(reference)
            if len(hits) != expected_count or len({h["id"] for h in hits}) != expected_count:
                raise ValueError("exact result count or uniqueness mismatch")
            by_id = {
                row["trial_id"]: (row, float(score))
                for row, score in zip(rows, scores, strict=True)
            }
            errors = []
            for hit, (_, expected_score) in zip(hits, reference, strict=True):
                row, score = by_id[hit["payload"]["trial_id"]]
                if not reference_compatible(facts, row["filter_metadata"]):
                    raise ValueError("server returned a known demographic contradiction")
                errors.extend([abs(hit["score"] - score), abs(hit["score"] - expected_score)])
            error = max(errors, default=0)
            if error > 1e-6:
                raise ValueError("server exact search disagrees with matrix reference")
            checks.append(
                {
                    "topic_id": topic["topic_id"],
                    "filter": mode,
                    "result_count": len(hits),
                    "max_score_error": error,
                    "same_ordered_ids": [h["payload"]["trial_id"] for h in hits]
                    == [p[0] for p in reference],
                }
            )
    return {
        "status": "passed",
        "scope": "bounded_exact_functionality_only",
        "server_version": repo.version(),
        "collection": repo.collection,
        "collection_config": repo.info()["config"],
        "contract": contract,
        "import_verification": verification,
        "topics_sha256": file_hash(topics_path),
        "checks": checks,
        "code_sha256": {
            str(path): file_hash(path)
            for path in (
                Path(__file__),
                Path("backend/app/repositories/qdrant.py"),
                Path("pipelines/indexing/qdrant.py"),
            )
        },
        "benchmark_comparable": False,
        "ann_evaluated": False,
        "eligibility_assessments_performed": 0,
        "note": "Scores within 1e-6 permit floating-point boundary ties; ID agreement is reported.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collection", type=local_id, default="trials_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.exit(1, f"Cannot create a fresh report directory: {exc}\n")
    try:
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        with QdrantRepository(args.url, args.collection) as repo:
            report = verify_exact(
                repo, Path("data/processed") / args.index_id, args.topics, encoder
            )
        write_json(output / "verification.json", report)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "documents": report["contract"]["documents"],
                    "exact_checks": len(report["checks"]),
                    "ann_evaluated": False,
                    "report": str(output / "verification.json"),
                },
                indent=2,
            )
        )
    except (ValueError, OSError, httpx.HTTPError) as exc:
        write_json(output / "verification.json", {"status": "failed", "error": str(exc)})
        parser.exit(1, f"Qdrant verification failed: {exc}\n")


if __name__ == "__main__":
    main()
