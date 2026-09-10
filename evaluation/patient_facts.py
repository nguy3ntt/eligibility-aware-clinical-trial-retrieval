"""Labelled development-contract metrics and optional unlabelled synthetic-topic audit."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from collections import Counter
from pathlib import Path

from backend.app.schemas.patient import KINDS
from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.patient_extraction.filters import build_filter_plan
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases

DEFAULT_FIXTURE = Path("evaluation/data/fixtures/synthetic_patient_facts.json")


def report_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise argparse.ArgumentTypeError(
            "report ID must be 1..80 letters, digits, hyphens or underscores"
        )
    return value


def fact_key(fact) -> tuple:
    return (
        fact.kind,
        fact.name,
        fact.value,
        fact.unit,
        fact.evidence.start,
        fact.evidence.end,
        fact.assertion,
        fact.temporality,
        fact.experiencer,
        fact.certainty,
        fact.operator,
    )


def evaluate_fixture(path: Path) -> dict:
    cases = load_cases(path)
    labels = json.loads(path.read_text(encoding="utf-8"))["cases"]
    counts = {kind: Counter() for kind in KINDS}
    per_case, profiles = [], []
    for case, labelled in zip(cases, labels, strict=True):
        expected = []
        for label in labelled["expected"]:
            kind, name, value, unit, quote, *context = label
            if kind not in KINDS or not quote or case.text.count(quote) != 1:
                raise ValueError("gold annotations require an unambiguous exact source quote")
            assertion, temporal, experiencer = (
                context + ["present", "current", "patient"][len(context) :]
            )
            start = case.text.index(quote)
            expected.append(
                (
                    kind,
                    name,
                    value,
                    unit,
                    start,
                    start + len(quote),
                    assertion,
                    temporal,
                    experiencer,
                    "uncertain" if assertion == "uncertain" else "asserted",
                    labelled.get("expected_operators", {}).get(name, "eq"),
                )
            )
        profile = extract_profile(case)
        plan = build_filter_plan(profile)
        actual = Counter(fact_key(f) for f in profile.facts)
        target = Counter(expected)
        correct, extra, missed = actual & target, actual - target, target - actual
        for kind in KINDS:
            counts[kind].update(
                tp=sum(n for key, n in correct.items() if key[0] == kind),
                fp=sum(n for key, n in extra.items() if key[0] == kind),
                fn=sum(n for key, n in missed.items() if key[0] == kind),
            )
        wanted_filters = labelled["expected_filters"]
        obtained = plan["demographics"]
        filter_match = set(obtained) == set(wanted_filters) and all(
            abs(obtained[k] - v) < 1e-8 if isinstance(v, int | float) else obtained[k] == v
            for k, v in wanted_filters.items()
        )
        per_case.append(
            {
                "case_id": case.case_id,
                "exact_match": actual == target,
                "filter_match": filter_match,
                "extra": list(extra.elements()),
                "missed": list(missed.elements()),
                "expected_filters": wanted_filters,
                "actual_filters": obtained,
            }
        )
        profiles.append({"profile": profile.model_dump(mode="json"), "filter_plan": plan})

    def metrics(c):
        precision = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        recall = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        return {
            **dict(c),
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }

    total = Counter()
    for counter in counts.values():
        total.update(counter)
    return {
        "cases": len(cases),
        "fact_metrics": metrics(total),
        "by_kind": {k: metrics(v) for k, v in counts.items()},
        "exact_cases": sum(c["exact_match"] for c in per_case),
        "correct_filter_cases": sum(c["filter_match"] for c in per_case),
        "per_case": per_case,
        "profiles": profiles,
        "limitation": "Manually labelled development contracts, not held-out clinical accuracy.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--topics", type=Path)
    parser.add_argument("--output-id", type=report_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output ID.\n")
    write_json(output / "started.json", {"status": "running"})
    try:
        result = evaluate_fixture(args.fixture)
        write_json(output / "labelled-results.json", result)
        summary = {k: v for k, v in result.items() if k not in {"profiles", "per_case"}}
        if args.topics:
            audit = []
            for case in load_cases(args.topics, topics=True):
                profile = extract_profile(case)
                audit.append(
                    {
                        "profile": profile.model_dump(mode="json"),
                        "filter_plan": build_filter_plan(profile),
                    }
                )
            write_json(output / "unlabelled-topics.json", audit)
            summary["unlabelled_audit"] = {
                "topics": len(audit),
                "facts": sum(len(x["profile"]["facts"]) for x in audit),
                "issues": dict(Counter(i["code"] for x in audit for i in x["profile"]["issues"])),
                "accuracy_measured": False,
            }
        passed = result["exact_cases"] == result["correct_filter_cases"] == result["cases"]
        summary.update(
            status="passed" if passed else "failed",
            eligibility_assessments_performed=0,
            profiles_exhaustive=False,
        )
        summary["runtime"] = {
            "python": platform.python_version(),
            "pydantic": importlib.metadata.version("pydantic"),
        }
        source_files = [args.fixture] + ([args.topics] if args.topics else [])
        code_files = [
            Path(__file__),
            Path("backend/app/schemas/patient.py"),
            *Path("backend/app/services/patient_extraction").glob("*.py"),
            Path("pipelines/connectors/synthetic_cases.py"),
            Path("pipelines/patient_facts.py"),
            Path("pipelines/hybrid_index.py"),
            Path("backend/app/repositories/qdrant.py"),
            Path("pipelines/connectors/trec.py"),
        ]
        summary["sha256"] = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files + code_files
        }
        summary["files"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.iterdir()
            if p.is_file()
        }
        write_json(output / "experiment.json", summary)
        print(json.dumps(summary, indent=2))
        if not passed:
            parser.exit(1, "Labelled extraction contract checks failed; inspect per-case errors.\n")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        write_json(
            output / "failure.json",
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "issues": getattr(exc, "issues", []),
            },
        )
        parser.exit(
            1, "Fact evaluation failed; inspect the source format and local failure report.\n"
        )


if __name__ == "__main__":
    main()
