"""Independent bounded criterion-vector validation, not eligibility/relevance evaluation."""

import argparse
import json
from pathlib import Path

import bm25s
import httpx
import numpy as np

from backend.app.repositories.criteria import CriteriaRepository
from backend.app.services.retrieval.sparse import PARAMETERS
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash, implementation_fingerprints, local_id
from pipelines.embeddings import MODELS, LocalSentenceEncoder
from pipelines.indexing.criteria import load_artifact, verify_collection


def check_scores(hits, ids, scores, *, k=5, tolerance=1e-6, relative=0.0, positive_only=False):
    reference = {
        identity: float(score)
        for identity, score in zip(ids, scores, strict=True)
        if not positive_only or score > 0
    }
    expected = sorted(reference.items(), key=lambda pair: (-pair[1], pair[0]))[:k]
    obtained = [h["payload"]["criterion_id"] for h in hits]
    if len(hits) != len(expected) or len(set(obtained)) != len(obtained):
        raise ValueError("criterion reference count/uniqueness mismatch")
    errors = []
    for hit, (_, score) in zip(hits, expected, strict=True):
        identity = hit["payload"]["criterion_id"]
        if identity not in reference or not np.isfinite(hit["score"]):
            raise ValueError("criterion reference identity/score invalid")
        # Numerically tied candidates may trade places across float32 implementations.
        for target in (score, reference[identity]):
            error = abs(hit["score"] - target)
            errors.append(error)
            if error > tolerance + relative * abs(target):
                raise ValueError("criterion scores/ranking differ from independent reference")
    maximum = max(errors, default=0.0)
    return maximum


def evaluate(repo, index, encoder, output):
    contract, records, vectors, lexical, points = load_artifact(index)
    if any(
        encoder.metadata[key] != contract["encoder"][key]
        for key in ("model", "snapshot_sha256", "normalization", "dtype", "prompt")
    ):
        raise ValueError("criterion verification model mismatch")
    storage = verify_collection(repo, contract, points)
    fresh, counts = [], []
    for start in range(0, len(records), 16):
        encoded = encoder.encode([r["input_text"] for r in records[start : start + 16]])
        fresh.extend(encoded.vectors)
        counts.extend(encoded.token_counts)
    audit = json.loads((index / "encoding-audit.json").read_bytes())
    if counts != [r["tokens"] for r in audit]:
        raise ValueError("criterion token audit differs from tokenizer")
    fresh = np.asarray(fresh, dtype=np.float32)
    embedding_error = float(np.max(np.abs(fresh - vectors)))
    if embedding_error > 1e-6 or not np.isfinite(embedding_error):
        raise ValueError("criterion vectors differ from freshly encoded source text")
    reference = bm25s.BM25(k1=PARAMETERS["k1"], b=PARAMETERS["b"], method="lucene")
    tokenize_options = {
        "lower": True,
        "token_pattern": PARAMETERS["token_pattern"],
        "stopwords": "english",
        "show_progress": False,
    }
    texts = [r["input_text"] for r in records]
    reference.index(bm25s.tokenize(texts, **tokenize_options), show_progress=False)
    ids = [r["criterion_id"] for r in records]
    checks = []
    for row in sorted(set(np.linspace(0, len(records) - 1, min(16, len(records)), dtype=int))):
        tokens = bm25s.tokenize([texts[row]], return_ids=False, **tokenize_options)[0]
        bm25_scores = reference.get_scores(tokens) if tokens else np.zeros(len(records))
        for method, query, scores, tolerance in (
            ("dense", fresh[row].tolist(), vectors @ fresh[row], 1e-6),
            ("sparse", lexical.query(texts[row])[0], bm25_scores, 1e-5),
        ):
            hits = repo.query_criteria(query, contract, sparse=method == "sparse")
            error = check_scores(
                hits,
                ids,
                scores,
                tolerance=tolerance,
                relative=1e-6 if method == "sparse" else 0,
                positive_only=method == "sparse",
            )
            repeated = repo.query_criteria(query, contract, sparse=method == "sparse")
            if [(h["id"], h["score"]) for h in hits] != [(h["id"], h["score"]) for h in repeated]:
                raise ValueError("criterion query replay changed")
            checks.append({"row": int(row) + 1, "method": method, "max_error": error})
    if repo.query_criteria(lexical.query("zzzzunseentokenxxxx")[0], contract, sparse=True):
        raise ValueError("empty lexical query must abstain")
    verify_collection(repo, contract, points)
    write_json(output / "checks.json", checks)
    return {
        "status": "passed",
        "artifact_sha256": contract["artifact_sha256"],
        "parser_sha256": contract["parser_sha256"],
        "encoder": encoder.metadata,
        "storage": storage,
        "config": repo.info()["config"],
        "criteria_reencoded": len(records),
        "embedding_max_error": embedding_error,
        "truncations": sum(r["truncated"] for r in audit),
        "query_checks": len(checks),
        "query_replays_identical": True,
        "dense_max_error": max(c["max_error"] for c in checks if c["method"] == "dense"),
        "sparse_max_error": max(c["max_error"] for c in checks if c["method"] == "sparse"),
        "tolerances": {"dense_absolute": 1e-6, "sparse_absolute": 1e-5, "sparse_relative": 1e-6},
        "query_selection": "up to 16 evenly spaced source-criterion rows; top 5; exact search",
        "checks_sha256": file_hash(output / "checks.json"),
        "evaluator_sha256": file_hash(Path(__file__)),
        "implementation_sha256": implementation_fingerprints(),
        "eligibility_assessments_performed": 0,
        "limitation": "Storage/scoring correctness only; no relevance or clinical accuracy claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-id", type=local_id, default="criterion-vectors-m7-v3")
    parser.add_argument("--collection", type=local_id, default="criteria_v1")
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output ID.\n")
    try:
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        with CriteriaRepository(args.url, args.collection) as repo:
            result = evaluate(repo, Path("data/processed") / args.index_id, encoder, output)
        write_json(output / "experiment.json", result)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in {"config", "encoder"}}, indent=2
            )
        )
    except (ValueError, OSError, KeyError, TypeError, httpx.HTTPError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(
            1, f"Criterion verification failed ({type(exc).__name__}); inspect local artifacts.\n"
        )


if __name__ == "__main__":
    main()
