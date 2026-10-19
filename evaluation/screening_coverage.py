"""Paired, unlabelled screening coverage audit; never interprets fewer unknowns as accuracy."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from backend.app.schemas.eligibility import TrialAssessment
from backend.app.services.eligibility.rules import verifier_hash, verify
from backend.app.services.patient_extraction.extractor import extract_profile
from evaluation.screening import code_fingerprints
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.parser import parse_eligibility
from pipelines.embeddings import file_hash, file_record, verify_files

VERSION = "screening-coverage-audit-v1"


def summary(assessments):
    criteria = [c for a in assessments for c in a.criteria]
    decided = sum(c.outcome != "unknown" for c in criteria)
    return {
        "pairs": len(assessments),
        "criteria": len(criteria),
        "statuses": dict(Counter(a.status for a in assessments)),
        "outcomes": dict(Counter(c.outcome for c in criteria)),
        "reasons": dict(Counter(c.reason for c in criteria)),
        "supported_criteria": decided,
        "supported_criterion_fraction": decided / len(criteria) if criteria else 0.0,
        "accuracy_measured": False,
    }


def capture(release: Path, topics: Path, output: Path):
    experiment = json.loads((release / "experiment.json").read_bytes())
    if experiment["status"] != "complete":
        raise ValueError("completed research release required")
    records = [r for r in experiment["files"] if r["path"] == "explanations.json"]
    verify_files(release, records, {"explanations.json"})
    cases = {c.case_id: c for c in load_cases(topics, topics=True)}
    explanations = json.loads((release / "explanations.json").read_bytes())
    assessments, seen = [], set()
    for row in explanations:
        a = TrialAssessment.model_validate(row["screening"]["assessment"])
        identity = (a.profile.case.case_id, a.parsed.source.trial_id)
        if (
            identity in seen
            or cases.get(identity[0]) != a.profile.case
            or a.parsed.source.source_kind != "public_historical_xml"
            or row["trial_id"] != identity[1]
        ):
            raise ValueError("invalid or duplicate source pair")
        if verify(extract_profile(a.profile.case), parse_eligibility(a.parsed.source)) != a:
            raise ValueError("baseline implementation does not reproduce original assessment")
        seen.add(identity)
        assessments.append(a)
    if len(assessments) != 150 or len({a.profile.case.case_id for a in assessments}) != 50:
        raise ValueError("all 150 original pairs and 50 synthetic cases required")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "assessments.json", [a.model_dump(mode="json") for a in assessments])
    manifest = {
        "version": VERSION,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "release_explanations_sha256": file_hash(release / "explanations.json"),
        "release_experiment_sha256": file_hash(release / "experiment.json"),
        "topics_sha256": file_hash(topics),
        "verifier_sha256": verifier_hash(),
        "implementation": code_fingerprints(),
        "summary": summary(assessments),
        "files": [file_record(output / "assessments.json", output)],
    }
    write_json(output / "manifest.json", manifest)
    return manifest["summary"]


def compare(before, after):
    """Align complete criterion/source identities; count gains and regressions explicitly."""
    transitions, changed, regressions = Counter(), [], []
    if len(before) != len(after):
        raise ValueError("paired assessments must have equal length")
    for old, new in zip(before, after, strict=True):
        if old.profile.case != new.profile.case or old.parsed != new.parsed:
            raise ValueError("case, source, parser or criterion identity changed")
        for a, b in zip(old.criteria, new.criteria, strict=True):
            transitions[f"{a.outcome}->{b.outcome}"] += 1
            if a.outcome == b.outcome:
                continue
            change = {
                "case_id": old.profile.case.case_id,
                "trial_id": old.parsed.source.trial_id,
                "criterion_id": a.criterion_id,
                "before": a.outcome,
                "after": b.outcome,
                "decision": b.model_dump(mode="json"),
                "facts": [
                    f.model_dump(mode="json") for f in new.profile.facts if f.fact_id in b.fact_ids
                ],
                "source": new.parsed.source.model_dump(mode="json"),
                "accuracy_measured": False,
            }
            changed.append(change)
            if a.outcome != "unknown":
                regressions.append(change)
    return {
        "before": summary(before),
        "after": summary(after),
        "criterion_transitions": dict(transitions),
        "trial_transitions": dict(
            Counter(f"{a.status}->{b.status}" for a, b in zip(before, after, strict=True))
        ),
        "changed_decisions": changed,
        "changed_previous_supported_outcomes": len(regressions),
        "accuracy_measured": False,
    }


def evaluate(baseline: Path, output: Path):
    manifest = json.loads((baseline / "manifest.json").read_bytes())
    if manifest["version"] != VERSION:
        raise ValueError("unsupported baseline")
    verify_files(baseline, manifest["files"], {"assessments.json"})
    before = [
        TrialAssessment.model_validate(a)
        for a in json.loads((baseline / "assessments.json").read_bytes())
    ]
    after = [
        verify(extract_profile(a.profile.case), parse_eligibility(a.parsed.source)) for a in before
    ]
    report = compare(before, after)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "assessments.json", [a.model_dump(mode="json") for a in after])
    write_json(output / "changed-decisions.json", report.pop("changed_decisions"))
    report.update(
        {
            "version": VERSION,
            "status": "complete",
            "accuracy_measured": False,
            "baseline_manifest_sha256": file_hash(baseline / "manifest.json"),
            "verifier_sha256": verifier_hash(),
            "implementation": code_fingerprints(),
            "limitations": (
                "Development coverage audit from verified historical evidence packets. "
                "No new labels or clinical accuracy."
            ),
            "files": [file_record(p, output) for p in sorted(output.iterdir())],
        }
    )
    write_json(output / "report.json", report)
    return report


def validate_report(baseline: Path, output: Path):
    manifest = json.loads((baseline / "manifest.json").read_bytes())
    report = json.loads((output / "report.json").read_bytes())
    if (
        manifest["version"] != VERSION
        or report["version"] != VERSION
        or report["status"] != "complete"
        or report["accuracy_measured"] is not False
        or report["baseline_manifest_sha256"] != file_hash(baseline / "manifest.json")
        or report["verifier_sha256"] != verifier_hash()
        or report["implementation"] != code_fingerprints()
    ):
        raise ValueError("coverage report identity mismatch")
    verify_files(baseline, manifest["files"], {"assessments.json"})
    verify_files(output, report["files"], {"assessments.json", "changed-decisions.json"})
    before = [
        TrialAssessment.model_validate(a)
        for a in json.loads((baseline / "assessments.json").read_bytes())
    ]
    after = [
        TrialAssessment.model_validate(a)
        for a in json.loads((output / "assessments.json").read_bytes())
    ]
    if any(
        verify(extract_profile(a.profile.case), parse_eligibility(a.parsed.source)) != a
        for a in after
    ):
        raise ValueError("coverage decisions do not reproduce")
    reproduced = compare(before, after)
    if (
        any(report[k] != v for k, v in reproduced.items() if k != "changed_decisions")
        or json.loads((output / "changed-decisions.json").read_bytes())
        != reproduced["changed_decisions"]
    ):
        raise ValueError("coverage summary mismatch")
    return {"status": "verified", "pairs": len(after), "criteria": report["after"]["criteria"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "evaluate", "verify"])
    parser.add_argument(
        "--release", type=Path, default=Path("evaluation/reports/release-full-benchmark-v1")
    )
    parser.add_argument(
        "--topics", type=Path, default=Path("data/raw/m1-20260831-500-v2/topics2022.xml")
    )
    parser.add_argument(
        "--baseline", type=Path, default=Path("evaluation/reports/screening-coverage-before-v1")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "capture":
        result = capture(args.release, args.topics, args.output)
    elif args.action == "evaluate":
        result = evaluate(args.baseline, args.output)
    else:
        result = validate_report(args.baseline, args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in {"implementation", "files"}}))


if __name__ == "__main__":
    main()
