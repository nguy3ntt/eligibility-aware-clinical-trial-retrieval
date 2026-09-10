"""Inspect bounded relevance reranking and source-backed research explanations."""

import argparse
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.app.schemas.patient import SyntheticCase, text_hash
from backend.app.services.eligibility.rules import verify
from backend.app.services.explanations.evidence import explain_result
from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.retrieval.reranker import LocalReranker, reorder
from evaluation.baselines.filters import extract_topic_demographics
from evaluation.qdrant_smoke import reference_compatible
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.artifacts import local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.render_trials import render_trial
from pipelines.reranking_data import eligibility_source, from_xml, load_evidence, prepare

INDEX_ID = "dense-m3-minilm-v1"
EVIDENCE_ID = "reranking-evidence-v1"
TOPICS = Path("data/raw/m1-20260831-500-v2/topics2022.xml")


def candidates(rows, scores, facts, depth=100):
    if len(rows) != len(scores) or len({r["trial_id"] for r in rows}) != len(rows):
        raise ValueError("candidate rows/scores must align uniquely")
    if not 1 <= depth <= 100 or any(not math.isfinite(float(s)) for s in scores):
        raise ValueError("invalid candidate depth or score")
    selected = [
        {"trial_id": r["trial_id"], "score": float(s), "method": "exact_dense"}
        for r, s in zip(rows, scores, strict=True)
        if reference_compatible(facts, r["filter_metadata"])
    ]
    selected.sort(key=lambda r: (-r["score"], r["trial_id"]))
    return selected[:depth]


def explain(case, ranking, records, top_k):
    profile = extract_profile(case)
    return [
        explain_result(
            case,
            r,
            records[r["trial_id"]],
            verify(profile, parse_eligibility(eligibility_source(records[r["trial_id"]]))),
        )
        for r in ranking[:top_k]
    ]


def demo_data():
    """Explicitly invented code-native fixtures, unrelated to benchmark labels."""
    text = "40-year-old man with asthma. Hemoglobin 12 g/dL."
    case = SyntheticCase(
        case_id="reranking-demo",
        synthetic=True,
        text=text,
        source="invented-fixture:reranking-demo-v1",
        source_sha256=text_hash(text),
        source_locator="/demo/patient",
    )
    examples = [
        (
            "NCT90009001",
            "Study of knee rehabilitation",
            "Knee injury",
            "This study compares rehabilitation exercises for knee injuries.",
            "Inclusion Criteria:\n- Age >= 18 years.\n- Creatinine <= 1.5 mg/dL.",
        ),
        (
            "NCT90009002",
            "Study of adult asthma",
            "Asthma",
            "This study examines inhaled therapies for adults with asthma.",
            "Inclusion Criteria:\n- Age >= 18 years.\n- Male.\n- Hemoglobin >= 10 g/dL.",
        ),
        (
            "NCT90009003",
            "Asthma study for older adults",
            "Asthma",
            "This study examines asthma symptoms in older adults.",
            "Inclusion Criteria:\nAge >= 65 years.",
        ),
    ]
    records, ranking = {}, []
    for trial_id, title, condition, summary, criteria in examples:
        element = ET.Element("clinical_study")
        ET.SubElement(ET.SubElement(element, "id_info"), "nct_id").text = trial_id
        ET.SubElement(element, "brief_title").text = title
        ET.SubElement(element, "condition").text = condition
        ET.SubElement(ET.SubElement(element, "brief_summary"), "textblock").text = summary
        eligibility = ET.SubElement(element, "eligibility")
        ET.SubElement(ET.SubElement(eligibility, "criteria"), "textblock").text = criteria
        raw = ET.tostring(element, encoding="utf-8")
        row = render_trial(
            element,
            {
                "archive": "invented",
                "archive_sha256": text_hash(raw.decode()),
                "member": trial_id + ".xml",
                "crc32": "00000000",
            },
        )
        records[trial_id] = from_xml(raw, row, invented=True)
        ranking.append({"trial_id": trial_id, "score": 0.0, "method": "invented_demo_order"})
    return case, ranking, records


def run_search(args):
    from pipelines.embeddings import MODELS, LocalSentenceEncoder
    from pipelines.indexing.qdrant import artifact_contract

    case = next(
        (c for c in load_cases(args.topics, topics=True) if c.case_id == args.case_id), None
    )
    if case is None:
        raise ValueError("unknown synthetic case ID")
    contract, rows, vectors = artifact_contract(Path("data/processed") / args.index_id)
    records = load_evidence(
        Path("data/processed") / args.evidence_id, rows, contract["artifact_sha256"]
    )
    encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("dense query model differs from artifact")
    started = time.perf_counter()
    encoded = encoder.encode([case.text])
    facts = extract_topic_demographics(case.text)
    ranking = candidates(rows, vectors @ encoded.vectors[0], facts)
    return (
        case,
        ranking,
        records,
        {
            "contract": contract,
            "filter_facts": facts,
            "encoder": encoder.metadata,
            "query_token_count": encoded.token_counts[0],
            "query_truncated": encoded.token_counts[0] > encoder.spec.max_tokens,
            "retrieval_seconds": time.perf_counter() - started,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare-evidence", "demo", "search"))
    parser.add_argument("--index-id", type=local_id, default=INDEX_ID)
    parser.add_argument("--evidence-id", type=local_id, default=EVIDENCE_ID)
    parser.add_argument("--snapshot-id", type=local_id, default="trec-ct-2021-20210427")
    parser.add_argument("--topics", type=Path, default=TOPICS)
    parser.add_argument("--case-id", default="trec-ct-2022:29")
    parser.add_argument("--depth", type=int, choices=range(1, 51), default=20)
    parser.add_argument("--top-k", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--output-id", type=local_id)
    args = parser.parse_args()
    output = None
    try:
        if args.command == "prepare-evidence":
            output = Path("data/processed") / args.evidence_id
        elif args.output_id:
            output = Path("evaluation/reports") / args.output_id
        if output:
            output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output/evidence ID.\n")
    try:
        if args.command == "prepare-evidence":
            result = prepare(
                Path("data/processed") / args.index_id, Path("data/raw") / args.snapshot_id, output
            )
        else:
            if args.command == "demo":
                case, ranking, records = demo_data()
                retrieval = {"method": "invented_demo_order_not_a_retrieval_benchmark"}
            else:
                case, ranking, records, retrieval = run_search(args)
            model, elapsed = None, 0.0
            if ranking and not args.no_rerank:
                model = LocalReranker()
                started = time.perf_counter()
                scored = model.score(
                    case,
                    [
                        records[r["trial_id"]]["row"]["representations"]["summary"]
                        for r in ranking[: args.depth]
                    ],
                )
                elapsed = time.perf_counter() - started
                ranking = reorder(ranking, scored)
            else:
                ranking = [
                    {**r, "rank": i + 1, "original_rank": i + 1, "reranker": None}
                    for i, r in enumerate(ranking)
                ]
            result = {
                "status": "complete",
                "schema_version": "reranked-evidence-results-v1",
                "retrieval": retrieval,
                "reranker": model.metadata if model else None,
                "candidate_count": len(ranking),
                "requested_depth": args.depth,
                "reranking_seconds_excluding_model_load": elapsed,
                "results": explain(case, ranking, records, args.top_k),
                "default_retrieval_changed": False,
                "benchmark_comparable": False,
            }
            if output:
                write_json(output / "results.json", result)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        if output:
            write_json(
                output / "failure.json", {"status": "failed", "error_type": type(exc).__name__}
            )
        parser.exit(
            1, f"Reranking failed ({type(exc).__name__}); check evidence/model contracts.\n"
        )


if __name__ == "__main__":
    main()
