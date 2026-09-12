"""Frozen full-corpus retrieval protocol; never tunes or promotes on these topics."""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path, PurePosixPath

import bm25s
import numpy as np
from threadpoolctl import threadpool_limits

from backend.app.services.retrieval.hybrid import reciprocal_rank_fusion
from backend.app.services.retrieval.reranker import LocalReranker, reorder
from backend.app.services.retrieval.sparse import PARAMETERS, tokenize
from evaluation.baselines.bm25 import _evaluate, _write_run
from evaluation.baselines.filters import (
    extract_topic_demographics,
    not_deterministically_incompatible,
)
from evaluation.reranking import comparison, fingerprints
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.connectors.trec import load_qrels
from pipelines.embeddings import MODELS, LocalSentenceEncoder, file_hash, file_record
from pipelines.release_index import (
    FROZEN_DOCUMENT_COUNT,
    FROZEN_DOCUMENTS_SHA256,
    read_chunk,
    source_contract,
    verify_index,
)
from pipelines.rerank import explain
from pipelines.reranking_data import from_xml

VERSION = "full-trec-release-v1"
DEPTH = 100


def top_indices(
    scores: np.ndarray, ids: np.ndarray, allowed: np.ndarray, *, depth=DEPTH, positive=False
) -> np.ndarray:
    if (
        scores.shape != ids.shape
        or allowed.shape != ids.shape
        or not np.isfinite(scores).all()
        or depth < 1
    ):
        raise ValueError("aligned finite scores and valid depth required")
    candidates = np.flatnonzero(allowed & (scores > 0 if positive else True))
    # Select the cutoff by score, then include all ties before stable NCT-ID ordering.
    if len(candidates) > depth:
        threshold = np.partition(scores[candidates], -depth)[-depth]
        candidates = candidates[scores[candidates] >= threshold]
    return candidates[np.lexsort((ids[candidates], -scores[candidates]))][:depth]


def paired_interval(base: dict, candidate: dict, *, seed=0, repeats=10000) -> dict:
    if set(base) != set(candidate) or not base:
        raise ValueError("paired identical nonempty topic sets required")
    delta = np.array([candidate[k]["ndcg_at_10"] - base[k]["ndcg_at_10"] for k in sorted(base)])
    if not np.isfinite(delta).all():
        raise ValueError("finite paired metrics required")
    rng = np.random.default_rng(seed)
    means = delta[rng.integers(0, len(delta), size=(repeats, len(delta)))].mean(axis=1)
    return {
        "method": "paired_topic_percentile_bootstrap",
        "seed": seed,
        "resamples": repeats,
        "mean_delta": float(delta.mean()),
        "ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "held_out": False,
        "multiple_comparison_adjustment": "none; exploratory intervals only",
    }


def original_records(selected: dict, snapshot: Path) -> dict:
    records, verified = {}, set()
    for trial_id, row in selected.items():
        source = row["source"]
        archive = (snapshot / source["archive"]).resolve()
        member = PurePosixPath(source["member"])
        if archive.parent != snapshot.resolve() or member.is_absolute() or ".." in member.parts:
            raise ValueError("unsafe original-source path")
        if archive not in verified:
            if file_hash(archive) != source["archive_sha256"]:
                raise ValueError("original archive checksum mismatch")
            verified.add(archive)
        with zipfile.ZipFile(archive) as bundle:
            info = bundle.getinfo(str(member))
            if info.file_size > 2 * 1024**2 or f"{info.CRC:08x}" != source["crc32"]:
                raise ValueError("source CRC or size mismatch")
            records[trial_id] = from_xml(bundle.read(info), row)
    return records


def run(
    index: Path, rendered: Path, topics: Path, qrels: Path, snapshot: Path, output: Path
) -> dict:
    manifest = verify_index(index)
    if (
        manifest["documents"] != FROZEN_DOCUMENT_COUNT
        or manifest["source"]["documents_sha256"] != FROZEN_DOCUMENTS_SHA256
    ):
        raise ValueError("full frozen corpus required; diagnostic subsets are forbidden")
    if source_contract(rendered) != manifest["source"]:
        raise ValueError("rendered source differs from encoded corpus")
    cases = load_cases(topics, topics=True)
    if (
        len(cases) != 50
        or file_hash(topics) != "c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91"
        or file_hash(qrels) != "e569a531489e03f7b1fab03fe169c8ea66f4a59e8180fa9858b1a6e4bdcb0c5c"
    ):
        raise ValueError("frozen official 2022 topics and qrels required")
    judgments = load_qrels(qrels.read_bytes(), {c.case_id.rsplit(":", 1)[1] for c in cases})
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "version": VERSION,
        "index_manifest_sha256": file_hash(index / "manifest.json"),
        "topics_sha256": file_hash(topics),
        "qrels_sha256": file_hash(qrels),
        "documents_sha256": FROZEN_DOCUMENTS_SHA256,
        "documents": FROZEN_DOCUMENT_COUNT,
        "topics": 50,
        "run_depth": DEPTH,
        "representation": "title_conditions",
        "lexical": PARAMETERS,
        "bm25s_version": bm25s.__version__,
        "fusion": {"rrf_k": 60, "branch_depth": 100, "weights": "equal"},
        "rerank_depths": [10, 20],
        "reranker_input": "summary; additional text compared with title-only baseline",
        "reranked_run_file_scores": "rank surrogate; original scores retained separately in JSON",
        "selection": "fixed_before_metrics; no tuning or default promotion",
        "code_sha256": {
            **fingerprints(),
            "evaluation/release_benchmark.py": file_hash(Path(__file__)),
            "pipelines/release_index.py": file_hash(Path("pipelines/release_index.py")),
        },
    }
    write_json(output / "protocol.json", protocol)
    try:
        rows, arrays = [], []
        for chunk in manifest["chunks"]:
            part, vectors = read_chunk(index / chunk["directory"], chunk)
            rows.extend(part)
            arrays.append(vectors)
        matrix = np.concatenate(arrays)
        del arrays
        ids = np.array([r["trial_id"] for r in rows])
        if {j["trial_id"] for j in judgments} - set(ids):
            raise ValueError("judged records absent from full corpus")
        encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        if encoder.metadata != manifest["encoder"]:
            raise ValueError("query encoder runtime or configuration differs from document encoder")
        query_vectors, query_tokens = [], []
        for case in cases:
            batch = encoder.encode([case.text])
            query_vectors.append(batch.vectors[0])
            query_tokens.append(batch.token_counts[0])
        print(
            json.dumps({"stage": "building_matched_full_corpus_BM25", "documents": len(rows)}),
            flush=True,
        )
        started = time.perf_counter()
        corpus = bm25s.tokenize(
            [r["text"] for r in rows],
            lower=True,
            stopwords="english",
            return_ids=True,
            show_progress=False,
        )
        lexical = bm25s.BM25(k1=1.2, b=0.75, method="lucene")
        lexical.index(corpus, show_progress=False)
        del corpus
        lexical.save(output / "lexical-index", corpus=ids.tolist(), show_progress=False)
        lexical_seconds = time.perf_counter() - started
        rankings = {
            f"{method}-{filter_name}": {}
            for method in ("dense", "bm25", "hybrid")
            for filter_name in ("none", "age_sex")
        }
        timings, branches_saved = [], {}
        for case, vector in zip(cases, query_vectors, strict=True):
            topic_id = case.case_id.rsplit(":", 1)[1]
            started = time.perf_counter()
            with threadpool_limits(limits=4, user_api="blas"):
                dense = matrix @ vector
            dense_seconds = time.perf_counter() - started
            # Independent blocked dot product must preserve the full reference within tolerance.
            with threadpool_limits(limits=4, user_api="blas"):
                reference = np.concatenate(
                    [matrix[i : i + 4096] @ vector for i in range(0, len(rows), 4096)]
                )
            if not np.allclose(dense, reference, atol=1e-6, rtol=0):
                raise ValueError("blocked exact reference mismatch")
            started = time.perf_counter()
            sparse = lexical.get_scores(tokenize([case.text])[0])
            sparse_seconds = time.perf_counter() - started
            demographics = extract_topic_demographics(case.text)
            for filter_name in ("none", "age_sex"):
                allowed = np.array(
                    [
                        True
                        if filter_name == "none"
                        else not_deterministically_incompatible(
                            demographics, row["filter_metadata"]
                        )
                        for row in rows
                    ]
                )
                branches = {}
                for name, scores in (("dense", dense), ("sparse", sparse)):
                    selected = top_indices(scores, ids, allowed, positive=name == "sparse")
                    hits = [
                        {"payload": {"trial_id": str(ids[i])}, "score": float(scores[i])}
                        for i in selected
                    ]
                    branches[name] = hits
                    method = "bm25" if name == "sparse" else name
                    rankings[f"{method}-{filter_name}"][topic_id] = [
                        {"trial_id": h["payload"]["trial_id"], "score": h["score"]} for h in hits
                    ]
                fused = reciprocal_rank_fusion(branches, k=100)
                rankings[f"hybrid-{filter_name}"][topic_id] = fused
                branches_saved[f"{topic_id}-{filter_name}"] = branches
            timings.append(
                {
                    "topic_id": topic_id,
                    "dense_dot_seconds": dense_seconds,
                    "bm25_score_seconds": sparse_seconds,
                }
            )
            print(json.dumps({"stage": "retrieved", "topic": topic_id}), flush=True)
        needed = {
            r["trial_id"] for results in rankings["hybrid-age_sex"].values() for r in results[:20]
        }
        selected_rows = {}
        with (rendered / "documents.jsonl").open("rb") as handle:
            for raw in handle:
                row = json.loads(raw)
                if row["trial_id"] in needed:
                    selected_rows[row["trial_id"]] = row
        if set(selected_rows) != needed:
            raise ValueError("reranker source coverage mismatch")
        reranker = LocalReranker()
        rerank_timings = []
        for depth in (10, 20):
            rankings[f"hybrid-rerank-{depth}"] = {}
            for case in cases:
                topic_id = case.case_id.rsplit(":", 1)[1]
                base = rankings["hybrid-age_sex"][topic_id]
                started = time.perf_counter()
                scores = reranker.score(
                    case,
                    [
                        selected_rows[r["trial_id"]]["representations"]["summary"]
                        for r in base[:depth]
                    ],
                )
                rerank_timings.append(
                    {"topic_id": topic_id, "depth": depth, "seconds": time.perf_counter() - started}
                )
                rankings[f"hybrid-rerank-{depth}"][topic_id] = reorder(base, scores)
        metrics, per_topic = {}, {}
        for name, results in rankings.items():
            pairs = {
                t: [
                    (r["trial_id"], float(len(hits) - i) if "rerank" in name else r["score"])
                    for i, r in enumerate(hits)
                ]
                for t, hits in results.items()
            }
            # TREC readers may sort by score: rank surrogates preserve prefix/tail order.
            # Raw learned logits and fusion scores remain separate in rankings.json.
            _write_run(output / f"{name}.run", pairs, name)
            metrics[name], per_topic[name] = _evaluate(pairs, judgments)
        write_json(output / "rankings.json", rankings)
        write_json(output / "branch-evidence.json", branches_saved)
        write_json(output / "per-topic.json", per_topic)
        write_json(
            output / "timings.json",
            {
                "retrieval": timings,
                "reranker": rerank_timings,
                "lexical_build_seconds": lexical_seconds,
                "limitations": (
                    "single measured pass; query encoding, filtering and sorting excluded "
                    "from kernel times; no server or ANN speed claim"
                ),
            },
        )
        comparisons = {
            name: {
                **comparison(per_topic["dense-age_sex"], result),
                **paired_interval(per_topic["dense-age_sex"], result),
            }
            for name, result in per_topic.items()
            if name != "dense-age_sex"
        }
        # Reconstruct original XML and retain screening for every displayed top-3 pair.
        displayed = {
            r["trial_id"] for hits in rankings["hybrid-rerank-20"].values() for r in hits[:3]
        }
        records = original_records({i: selected_rows[i] for i in displayed}, snapshot)
        explanations = []
        for case in cases:
            topic_id = case.case_id.rsplit(":", 1)[1]
            explanations.extend(explain(case, rankings["hybrid-rerank-20"][topic_id], records, 3))
        write_json(output / "explanations.json", explanations)
        result = {
            "status": "complete",
            "version": VERSION,
            "protocol": protocol,
            "metrics": metrics,
            "comparisons": comparisons,
            "encoder": encoder.metadata,
            "model": reranker.metadata,
            "query_truncated": sum(n > encoder.spec.max_tokens for n in query_tokens),
            "document_truncated": manifest["truncated"],
            "explained_pairs": len(explanations),
            "promotion": {
                "enabled": False,
                "reason": "previously_inspected_topics_no_held_out_validation",
            },
            "limitations": (
                "Full frozen corpus, all 50 previously inspected synthetic topics. "
                "Pooled qrels: unjudged is zero gain, not confirmed irrelevance. "
                "MRR is truncated at 100. Title-only lexical/dense inputs; reranking adds "
                "summary text with explicit truncation. No full-corpus ANN measurement, "
                "clinical validation, semantic promotion or default change."
            ),
            "files": [file_record(p, output) for p in sorted(output.rglob("*")) if p.is_file()],
        }
        write_json(output / "experiment.json", result)
        return result
    except Exception as exc:
        write_json(
            output / "failure.json",
            {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)},
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/processed/release-full-minilm-v2"))
    parser.add_argument(
        "--rendered", type=Path, default=Path("data/processed/trec-ct-2021-render-v1")
    )
    parser.add_argument(
        "--topics", type=Path, default=Path("data/raw/m1-20260831-500-v2/topics2022.xml")
    )
    parser.add_argument(
        "--qrels", type=Path, default=Path("data/raw/m1-20260831-500-v2/qrels2022.txt")
    )
    parser.add_argument("--snapshot", type=Path, default=Path("data/raw/trec-ct-2021-20210427"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.index, args.rendered, args.topics, args.qrels, args.snapshot, args.output)
    print(json.dumps({"status": result["status"], "metrics": result["metrics"]}))


if __name__ == "__main__":
    main()
