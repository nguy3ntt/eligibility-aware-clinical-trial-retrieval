"""Re-encode source representations and verify original/restored/rebuilt collections."""

import argparse
import json
from pathlib import Path

import httpx
import numpy as np

from backend.app.repositories.qdrant import QdrantRepository
from evaluation.qdrant_smoke import verify_exact
from pipelines.connectors.snapshots import write_json
from pipelines.dense import local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash, validate_vectors
from pipelines.indexing.qdrant import artifact_contract


def verify_reencoding(rows, vectors, encoder) -> dict:
    maximum = 0.0
    for start in range(0, len(rows), 16):
        batch = rows[start : start + 16]
        actual = encoder.encode([r["representations"]["title_conditions"] for r in batch]).vectors
        validate_vectors(actual, len(batch), encoder.spec.dimension)
        error = float(np.max(np.abs(actual - vectors[start : start + len(batch)])))
        if error > 1e-6:
            raise ValueError("source re-encoding differs from the saved vectors")
        maximum = max(maximum, error)
    return {
        "documents_reencoded": len(rows),
        "batch_size": 16,
        "maximum_absolute_error": maximum,
        "tolerance": 1e-6,
        "representation": "title_conditions",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--collections", type=local_id, nargs="+", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.collections) <= 3 or len(set(args.collections)) != len(args.collections):
        parser.error("provide one to three distinct collections")
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.exit(1, f"Use a fresh report ID: {exc}\n")
    try:
        index = Path("data/processed") / args.index_id
        contract, rows, vectors = artifact_contract(index)
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
            raise ValueError("query model snapshot differs from source")
        reencoding = verify_reencoding(rows, vectors, encoder)
        checks = []
        for name in args.collections:
            with QdrantRepository(args.url, name) as repo:
                info = repo.hnsw_ready(contract)
                result = verify_exact(repo, index, args.topics, encoder)
                write_json(output / f"{name}.json", result)
                checks.append(
                    {
                        "collection": name,
                        "exact_checks": len(result["checks"]),
                        "indexed_vectors": info["indexed_vectors_count"],
                        "report_sha256": file_hash(output / f"{name}.json"),
                    }
                )
        report = {
            "status": "passed",
            "version": "qdrant-recovery-smoke-v1",
            "contract": contract,
            "reencoding": reencoding,
            "collections": checks,
            "code_sha256": file_hash(Path(__file__)),
            "benchmark_comparable": False,
            "note": "Read-only checks; does not create backups or restore collections.",
        }
        write_json(output / "recovery-verification.json", report)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error": str(exc)})
        parser.exit(1, f"Recovery verification failed: {exc}\n")


if __name__ == "__main__":
    main()
