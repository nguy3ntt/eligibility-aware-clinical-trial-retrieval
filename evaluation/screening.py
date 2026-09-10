"""Exact deterministic criterion/trial metrics plus a separate historical coverage audit."""

import argparse
import json
import platform
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from backend.app.services.eligibility.rules import verifier_hash, verify
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.artifacts import file_hash, load_parses, local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import DEFAULT_FIXTURE, load_pairs


def evaluate_fixture(path=DEFAULT_FIXTURE):
    cases, confusion = [], Counter()
    for row, case, source in load_pairs(path):
        assessment = verify(extract_profile(case), parse_eligibility(source))
        outcomes = [c.outcome for c in assessment.criteria]
        # Missing/extra parsed criteria are errors, not silently omitted by zip.
        for index in range(max(len(outcomes), len(row["expected"]))):
            expected = row["expected"][index] if index < len(row["expected"]) else "unexpected"
            actual = outcomes[index] if index < len(outcomes) else "missing"
            confusion[(expected, actual)] += 1
        cases.append(
            {
                "id": row["id"],
                "exact": outcomes == row["expected"] and assessment.status == row["status"],
                "expected": row["expected"],
                "expected_status": row["status"],
                "assessment": assessment.model_dump(mode="json"),
            }
        )
    total = sum(confusion.values())
    correct = sum(n for (a, b), n in confusion.items() if a == b)
    decided = sum(
        n for (_, b), n in confusion.items() if b in {"satisfied", "violated", "not_applicable"}
    )
    decided_correct = sum(n for (a, b), n in confusion.items() if a == b and b != "unknown")
    return {
        "pairs": len(cases),
        "exact_pairs": sum(c["exact"] for c in cases),
        "criterion_count": total,
        "criterion_accuracy": correct / total if total else None,
        "supported_outcome_coverage": decided / total if total else 0,
        "supported_outcome_precision": decided_correct / decided if decided else None,
        "confusion": [
            {"expected": a, "actual": b, "count": n} for (a, b), n in sorted(confusion.items())
        ],
        "confidence": "Rules emit no probability; calibration is evaluated only for NLI.",
        "cases": cases,
    }


def code_fingerprints():
    root = Path(__file__).resolve().parents[1]
    names = (
        "pyproject.toml",
        "pipelines/prepare_nli.py",
        "backend/app/schemas/patient.py",
        "backend/app/schemas/criteria.py",
        "backend/app/schemas/eligibility.py",
        "backend/app/services/eligibility/rules.py",
        "backend/app/services/eligibility/semantic.py",
        "pipelines/screening.py",
        "pipelines/screening_data.py",
        "evaluation/screening.py",
        "evaluation/semantic_screening.py",
        "backend/app/services/patient_extraction/extractor.py",
        "backend/app/services/patient_extraction/rules.py",
        "pipelines/criteria/parser.py",
    )
    return {name: file_hash(root / name) for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-id", type=local_id, required=True)
    parser.add_argument("--source-id", type=local_id)
    parser.add_argument("--cases", type=Path)
    args = parser.parse_args()
    if bool(args.source_id) != bool(args.cases):
        parser.error("historical audit requires both source-id and explicit synthetic cases")
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output ID.\n")
    try:
        result = evaluate_fixture(args.fixture)
        write_json(output / "labelled-results.json", result)
        summary = {k: v for k, v in result.items() if k != "cases"}
        if args.source_id:
            _, documents = load_parses(Path("data/processed") / args.source_id)
            cases = load_cases(args.cases)
            if len(cases) * len(documents) > 200:
                raise ValueError("historical audit limited to 200 synthetic case-trial pairs")
            assessments = [
                verify(extract_profile(case), p).model_dump(mode="json")
                for case in cases
                for p in documents
            ]
            write_json(output / "unlabelled-assessments.json", assessments)
            summary["unlabelled_audit"] = {
                "pairs": len(assessments),
                "statuses": dict(Counter(a["status"] for a in assessments)),
                "outcomes": dict(Counter(c["outcome"] for a in assessments for c in a["criteria"])),
                "accuracy_measured": False,
                "cases_sha256": file_hash(args.cases),
                "source_sha256": file_hash(
                    Path("data/processed") / args.source_id / "manifest.json"
                ),
            }
        summary.update(
            status="passed" if result["exact_pairs"] == result["pairs"] else "failed",
            verifier_sha256=verifier_hash(),
            fixture_sha256=file_hash(args.fixture),
            implementation_sha256=code_fingerprints(),
            runtime={"python": platform.python_version(), "pydantic": version("pydantic")},
            limitation="Authored synthetic development contracts, not clinical validation.",
        )
        write_json(output / "experiment.json", summary)
        print(json.dumps(summary, indent=2))
        if summary["status"] != "passed":
            parser.exit(1, "Screening checks failed; inspect local labelled results.\n")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(1, "Screening evaluation failed; inspect local evidence.\n")


if __name__ == "__main__":
    main()
