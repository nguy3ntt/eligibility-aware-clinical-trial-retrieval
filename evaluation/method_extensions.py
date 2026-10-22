"""Fixed development diagnostics for grouped screening and field/passage retrieval."""

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.app.services.eligibility.grouped import verify_grouped, walk
from backend.app.services.eligibility.rules import verify
from backend.app.services.patient_extraction.extractor import extract_profile
from evaluation.baselines.filters import extract_topic_demographics
from evaluation.metrics.retrieval import aggregate_metrics, query_metrics
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.embeddings import file_hash, file_record
from pipelines.screening_data import load_pairs

VERSION = "method-extensions-development-v1"
FIXTURE = Path("evaluation/data/fixtures/grouped_screening.json")


def grouped_report(baseline, output):
    from backend.app.schemas.eligibility import TrialAssessment
    from evaluation.screening_coverage import VERSION as COVERAGE_VERSION
    from pipelines.embeddings import verify_files

    source = json.loads((baseline / "report.json").read_bytes())
    if source["version"] != COVERAGE_VERSION:
        raise ValueError("versioned paired screening source required")
    # after-v2 exposes assessments via its sealed inventory, not a new case source.
    verify_files(baseline, source["files"], {r["path"] for r in source["files"]})
    saved = json.loads((baseline / "assessments.json").read_bytes())
    public, fixtures = [], []
    for row in saved:
        original = TrialAssessment.model_validate(row)
        profile, parsed = (
            extract_profile(original.profile.case),
            parse_eligibility(original.parsed.source),
        )
        if verify(profile, parsed) != original:
            raise ValueError("v2 baseline cannot be reproduced")
        public.append(
            {"baseline_status": original.status, "grouped": verify_grouped(profile, parsed)}
        )
    if len(public) != 150:
        raise ValueError("all 150 historical pairs required")
    for row, case, source in load_pairs(FIXTURE):
        profile, parsed = extract_profile(case), parse_eligibility(source)
        result = verify_grouped(profile, parsed)
        fixtures.append(
            {
                "id": row["id"],
                "expected_status": row["status"],
                "grouped": result,
                "case": case.model_dump(mode="json"),
                "source": source.model_dump(mode="json"),
            }
        )
    metrics = {
        "fixture_pairs": len(fixtures),
        "fixture_exact_statuses": sum(
            r["expected_status"] == r["grouped"]["status"] for r in fixtures
        ),
        "public_pairs": len(public),
        "public_statuses": dict(Counter(r["grouped"]["status"] for r in public)),
        "public_transitions": dict(
            Counter(r["baseline_status"] + "->" + r["grouped"]["status"] for r in public)
        ),
        "public_scope_review_pairs": sum(r["grouped"]["scope_review_required"] for r in public),
        "public_node_truths": dict(
            Counter(
                n["truth"]
                for r in public
                for n in walk([s["root"] for s in r["grouped"]["sections"]])
            )
        ),
        "accuracy_measured": False,
        "independent_human_review": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "fixture-assessments.json", fixtures)
    write_json(output / "historical-assessments.json", public)
    result = {
        "version": VERSION,
        "status": "complete",
        "metrics": metrics,
        "fixture_sha256": file_hash(FIXTURE),
        "baseline_manifest_sha256": file_hash(baseline / "report.json"),
        "limitations": "Authored contracts and unlabelled development coverage only; "
        "no independent criterion accuracy.",
        "implementation": fingerprints(),
        "files": [file_record(p, output) for p in sorted(output.iterdir())],
    }
    write_json(output / "experiment.json", result)
    return result


def fingerprints():
    from backend.app.services.application import implementation

    return implementation()


def retrieval_report(root, index, evidence, topics_path, qrels_path, output, encoder):
    from backend.app.services.retrieval.sparse import SparseBM25
    from evaluation.baselines.filters import not_deterministically_incompatible
    from evaluation.release_benchmark import paired_interval
    from pipelines.connectors.trec import load_qrels, load_topics
    from pipelines.field_passages import PARAMETERS, load, rank

    loaded = load(root, index, evidence)
    if encoder.metadata != loaded[0]["encoder"]:
        raise ValueError("document/query runtime differs")
    topics = load_topics(topics_path.read_bytes())
    judgments = load_qrels(qrels_path.read_bytes(), {t["topic_id"] for t in topics})
    ids = {r["trial_id"] for r in loaded[1]}
    # This pool was selected using judgments. Use its same pooled labels for every method.
    pooled = {t["topic_id"]: {} for t in topics}
    for row in judgments:
        if row["trial_id"] in ids:
            pooled[row["topic_id"]][row["trial_id"]] = row["grade"]
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "version": VERSION,
        "status": "frozen_development_protocol",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "parameters": PARAMETERS,
        "systems": ["bm25-title", "bm25-summary", "baseline", "summary", "fields", "passages"],
        "filter": "legacy_age_sex",
        "depth": 100,
        "input_hashes": {
            "artifact_manifest": file_hash(root / "manifest.json"),
            "topics": file_hash(topics_path),
            "qrels": file_hash(qrels_path),
        },
        "encoder": encoder.metadata,
        "implementation": fingerprints(),
        "held_out": False,
        "promotion_enabled": False,
        "limits": "443-trial judgment-selected development pool; not full corpus, "
        "unseen cases or criterion accuracy. No 2021 holdout reuse.",
    }
    write_json(output / "protocol.json", protocol)
    rankings, all_metrics, timing = {}, {}, {}
    queries = [t["text"] for t in topics]
    facts = {t["topic_id"]: extract_topic_demographics(t["text"]) for t in topics}
    rows = loaded[1]
    # Save both lexical baselines before measuring the dense candidates.
    for system, representation in (("bm25-title", "title_conditions"), ("bm25-summary", "summary")):
        started = time.perf_counter()
        model = SparseBM25([r["representations"][representation] for r in rows])
        document_vectors = [
            dict(zip(v["indices"], v["values"], strict=True)) for v in model.document_vectors
        ]
        rankings[system] = {}
        for topic in topics:
            q, _ = model.query(topic["text"])
            scores = [
                sum(
                    value * document.get(term, 0.0)
                    for term, value in zip(q["indices"], q["values"], strict=True)
                )
                for document in document_vectors
            ]
            pairs = [
                (r["trial_id"], float(s))
                for r, s in zip(rows, scores, strict=True)
                if not_deterministically_incompatible(
                    facts[topic["topic_id"]], r["filter_metadata"]
                )
            ]
            rankings[system][topic["topic_id"]] = [
                {"trial_id": tid, "score": score}
                for tid, score in sorted(pairs, key=lambda v: (-v[1], v[0]))[:100]
            ]
        timing[system] = {"index_and_all_queries_seconds": time.perf_counter() - started}
        write_json(output / f"{system}-rankings.json", rankings[system])
    encoded = encoder.encode(queries)
    np.save(output / "query-vectors.npy", encoded.vectors, allow_pickle=False)
    query_audit = [
        {"topic_id": t["topic_id"], "tokens": count, "truncated": count > encoder.spec.max_tokens}
        for t, count in zip(topics, encoded.token_counts, strict=True)
    ]
    for variant in ("baseline", "summary", "fields", "passages"):
        rankings[variant], durations = {}, []
        with threadpool_limits(limits=1):
            for i, topic in enumerate(topics):
                started = time.perf_counter()
                ranking = rank(
                    loaded,
                    encoded.vectors[i],
                    variant=variant,
                    demographics=facts[topic["topic_id"]],
                )
                durations.append(time.perf_counter() - started)
                rankings[variant][topic["topic_id"]] = ranking
                if variant == "baseline":
                    # Independent complete dot-product reference, including the same filters.
                    scores = np.clip(loaded[4]["baseline"] @ encoded.vectors[i], -1, 1)
                    reference = sorted(
                        [
                            (r["trial_id"], float(s))
                            for r, s in zip(rows, scores, strict=True)
                            if not_deterministically_incompatible(
                                facts[topic["topic_id"]], r["filter_metadata"]
                            )
                        ],
                        key=lambda v: (-v[1], v[0]),
                    )[:100]
                    if [r["trial_id"] for r in ranking] != [tid for tid, _ in reference]:
                        raise ValueError("baseline exact ranking differs")
        timing[variant] = {
            "warm_rank_only_median_seconds": float(np.median(durations)),
            "warm_rank_only_p95_seconds": float(np.quantile(durations, 0.95)),
            "query_encoding_and_artifact_load_excluded": True,
        }
        write_json(output / f"{variant}-rankings.json", rankings[variant])
    for system, runs in rankings.items():
        per_topic = {
            tid: query_metrics([r["trial_id"] for r in run], pooled[tid])
            for tid, run in runs.items()
        }
        all_metrics[system] = {"aggregate": aggregate_metrics(per_topic), "per_topic": per_topic}
    comparisons = {
        name: paired_interval(all_metrics["baseline"]["per_topic"], all_metrics[name]["per_topic"])
        for name in ("summary", "fields", "passages")
    }
    write_json(output / "metrics.json", all_metrics)
    write_json(output / "query-audit.json", query_audit)
    result = {
        "version": VERSION,
        "status": "complete",
        "protocol_sha256": file_hash(output / "protocol.json"),
        "documents": len(rows),
        "topics": len(topics),
        "pooled_judgments": sum(map(len, pooled.values())),
        "metrics": {k: v["aggregate"] for k, v in all_metrics.items()},
        "comparisons": comparisons,
        "timing": timing,
        "artifact_statistics": loaded[0]["statistics"],
        "artifact_bytes": sum(r["bytes"] for r in loaded[0]["files"]),
        "promotion": {"enabled": False, "reason": "development_only"},
        "implementation": fingerprints(),
        "files": [file_record(p, output) for p in sorted(output.iterdir())],
    }
    write_json(output / "experiment.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["grouped", "retrieval"])
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    if args.command == "grouped":
        result = grouped_report(Path("evaluation/reports/screening-coverage-after-v2"), output)
        print(json.dumps(result["metrics"]))
    else:
        from pipelines.embeddings import MODELS, LocalSentenceEncoder

        result = retrieval_report(
            Path("data/processed/field-passages-v2"),
            Path("data/processed/dense-m3-minilm-v1"),
            Path("data/processed/reranking-evidence-v1"),
            Path("data/raw/m1-20260831-500-v2/topics2022.xml"),
            Path("data/raw/m1-20260831-500-v2/qrels2022.txt"),
            output,
            LocalSentenceEncoder(MODELS["minilm"], Path("models")),
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "metrics": result["metrics"],
                    "comparisons": result["comparisons"],
                }
            )
        )


if __name__ == "__main__":
    main()
