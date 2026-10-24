"""Authored review contracts and an unlabelled, outcome-invariant historical audit."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from backend.app.schemas.eligibility import TrialAssessment
from backend.app.services.eligibility.grouped import verify_grouped
from backend.app.services.eligibility.review import fingerprint, prioritise_missing, validate_review
from backend.app.services.eligibility.rules import validate_assessment
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.embeddings import file_hash, file_record, verify_files
from pipelines.screening_data import load_pairs

VERSION = "missing-information-review-audit-v1"
FIXTURE = Path("evaluation/data/fixtures/missing_information_review.json")
BASELINE = Path("evaluation/reports/screening-coverage-after-v2")


def read(path):
    return json.loads(path.read_bytes())


def identity():
    return {
        "review_implementation_sha256": fingerprint(),
        "evaluation_sha256": file_hash(Path(__file__)),
        "fixture_sha256": file_hash(FIXTURE),
    }


def fixture_report():
    from backend.app.services.eligibility.rules import verify
    from backend.app.services.patient_extraction.extractor import extract_profile

    rows = []
    for row, case, source in load_pairs(FIXTURE):
        a = verify(extract_profile(case), parse_eligibility(source))
        g = {source.trial_id: verify_grouped(a.profile, a.parsed)} if row["grouped"] else None
        p = prioritise_missing([a], grouped=g)
        passed = (
            [[i.fact_name, i.requested_unit] for i in p.items] == row["review_keys"]
            and [i.criterion_count for i in p.items] == row["review_criteria"]
            and len(p.interpretation_reviews) == row["interpretations"]
            and len(p.settled_branch_reviews) == row["settled"]
            and p.basis[0].status == row["status"]
        )
        validate_review(p, [a], grouped=g)
        rows.append({"id": row["id"], "passed": passed, "plan": p.model_dump(mode="json")})
    return rows


def plan_summary(plans):
    return {
        "plans": len(plans),
        "plans_with_fact_items": sum(bool(p.items) for p in plans),
        "fact_items": sum(len(p.items) for p in plans),
        "active_fact_references": sum(len(i.references) for p in plans for i in p.items),
        "interpretation_references": sum(len(p.interpretation_reviews) for p in plans),
        "settled_branch_references": sum(len(p.settled_branch_reviews) for p in plans),
        "fact_names": dict(Counter(i.fact_name for p in plans for i in p.items)),
    }


def reproduce(assessments):
    plans, by_case = [], defaultdict(list)
    for a in assessments:
        before = a.model_dump(mode="json")
        validate_assessment(a)
        g = {a.parsed.source.trial_id: verify_grouped(a.profile, a.parsed)}
        ordinary = prioritise_missing([a])
        grouped = prioritise_missing([a], grouped=g)
        validate_review(ordinary, [a])
        validate_review(grouped, [a], grouped=g)
        if a.model_dump(mode="json") != before:
            raise ValueError("review changed original screening evidence")
        plans.append({"ordinary": ordinary, "grouped": grouped})
        by_case[a.profile.case.case_id].append(a)
    case_plans = []
    for case_id in sorted(by_case):
        cohort = by_case[case_id]
        case_plans.append(
            {
                "ordinary": prioritise_missing(cohort),
                "grouped": prioritise_missing(
                    cohort,
                    grouped={
                        a.parsed.source.trial_id: verify_grouped(a.profile, a.parsed)
                        for a in cohort
                    },
                ),
            }
        )

    def encoded(rows):
        return [{mode: plan.model_dump(mode="json") for mode, plan in row.items()} for row in rows]

    metrics = {
        "original_pairs": len(assessments),
        "unchanged_assessments": len(assessments),
        "unchanged_statuses": len(assessments),
        "original_statuses": dict(Counter(a.status for a in assessments)),
        "original_unknown_criteria": sum(len(a.unknown_criterion_ids) for a in assessments),
        "pair_plans": {m: plan_summary([p[m] for p in plans]) for m in ("ordinary", "grouped")},
        "case_plans": {
            m: plan_summary([p[m] for p in case_plans]) for m in ("ordinary", "grouped")
        },
        "clinical_accuracy_measured": False,
        "review_utility_measured": False,
    }
    return encoded(plans), encoded(case_plans), metrics


def evaluate(output, baseline=BASELINE):
    if output.exists():
        raise ValueError("fresh audit output required; preserve existing studies")
    source_report = read(baseline / "report.json")
    verify_files(baseline, source_report["files"], {r["path"] for r in source_report["files"]})
    raw = read(baseline / "assessments.json")
    assessments = [TrialAssessment.model_validate(r) for r in raw]
    pairs = {(a.profile.case.case_id, a.parsed.source.trial_id) for a in assessments}
    if (
        len(pairs) != 150
        or len(assessments) != 150
        or len({c for c, _ in pairs}) != 50
        or any(a.parsed.source.source_kind != "public_historical_xml" for a in assessments)
    ):
        raise ValueError("all original 150 public-trial/synthetic-case pairs required")
    output.mkdir(parents=True)
    write_json(
        output / "protocol.json",
        {
            "version": VERSION,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "identity": identity(),
            "baseline_assessments_sha256": file_hash(baseline / "assessments.json"),
            "clinical_accuracy_measured": False,
            "review_utility_measured": False,
        },
    )
    fixtures = fixture_report()
    plans, case_plans, metrics = reproduce(assessments)
    metrics["authored_contracts"] = len(fixtures)
    metrics["authored_contracts_passed"] = sum(r["passed"] for r in fixtures)
    write_json(output / "assessments.json", raw)
    write_json(output / "fixture-results.json", fixtures)
    write_json(output / "pair-plans.json", plans)
    write_json(output / "case-plans.json", case_plans)
    report = {
        "version": VERSION,
        "status": "complete" if all(r["passed"] for r in fixtures) else "failed",
        "identity": identity(),
        "metrics": metrics,
        "files": [file_record(p, output) for p in sorted(output.iterdir())],
    }
    write_json(output / "report.json", report)
    return report


def verify_report(root):
    report = read(root / "report.json")
    if (
        report["version"] != VERSION
        or report["status"] != "complete"
        or report["identity"] != identity()
    ):
        raise ValueError("review audit implementation/configuration differs")
    verify_files(
        root,
        report["files"],
        {
            "protocol.json",
            "assessments.json",
            "fixture-results.json",
            "pair-plans.json",
            "case-plans.json",
        },
    )
    protocol = read(root / "protocol.json")
    if protocol["identity"] != identity() or protocol["baseline_assessments_sha256"] != file_hash(
        root / "assessments.json"
    ):
        raise ValueError("review audit source/protocol differs")
    fixtures = fixture_report()
    plans, case_plans, metrics = reproduce(
        [TrialAssessment.model_validate(r) for r in read(root / "assessments.json")]
    )
    metrics["authored_contracts"] = len(fixtures)
    metrics["authored_contracts_passed"] = sum(r["passed"] for r in fixtures)
    if (
        metrics != report["metrics"]
        or fixtures != read(root / "fixture-results.json")
        or plans != read(root / "pair-plans.json")
        or case_plans != read(root / "case-plans.json")
    ):
        raise ValueError("review order/evidence/metrics reproduction differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["evaluate", "verify"])
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    root = Path("evaluation/reports") / args.output_id
    try:
        report = evaluate(root) if args.command == "evaluate" else verify_report(root)
        print(json.dumps({"status": report["status"], "metrics": report["metrics"]}))
        if report["status"] != "complete":
            parser.exit(1, "Review contract failures; preserve the report.\n")
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        parser.exit(1, f"Review audit failed ({type(exc).__name__}); preserve evidence.\n")


if __name__ == "__main__":
    main()
