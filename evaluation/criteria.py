"""Exact labelled parsing metrics and optional unlabelled original-trial audit."""

import argparse
import json
import platform
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import (
    file_hash,
    fixture_sources,
    implementation_fingerprints,
    load_parses,
    local_id,
)
from pipelines.criteria.parser import parse_eligibility, parser_hash
from pipelines.criteria_parse import DEFAULT_FIXTURE


def evaluate_fixture(path):
    sources, labels = fixture_sources(path)
    counts = Counter(tp=0, fp=0, fn=0)
    cases = []
    for source, row in zip(sources, labels, strict=True):
        parsed = parse_eligibility(source)
        lookup = {c.criterion_id: c.ordinal for c in parsed.criteria}
        actual = []
        for c in parsed.criteria:
            numeric = tuple((n.name, n.operator, n.value, n.upper, n.unit) for n in c.constraints)
            actual.append(
                (
                    c.evidence.start,
                    c.evidence.end,
                    c.section,
                    c.types,
                    c.logic,
                    numeric,
                    lookup.get(c.parent_id),
                )
            )
        expected = []
        for quote, section, types, logic, numeric, parent in row["expected"]:
            if not quote or source.text.count(quote) != 1:
                raise ValueError("gold quote must identify one source span")
            start = source.text.index(quote)
            expected.append(
                (
                    start,
                    start + len(quote),
                    section,
                    tuple(types),
                    logic,
                    tuple(tuple(n) for n in numeric),
                    parent,
                )
            )
        obtained, wanted = Counter(actual), Counter(expected)
        good, extra, missed = obtained & wanted, obtained - wanted, wanted - obtained
        counts.update(tp=good.total(), fp=extra.total(), fn=missed.total())
        cases.append(
            {
                "trial_id": source.trial_id,
                "exact_match": actual == expected,
                "extra": list(extra.elements()),
                "missed": list(missed.elements()),
                "parsed": parsed.model_dump(mode="json"),
            }
        )
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0
    return {
        "trials": len(cases),
        "exact_trials": sum(c["exact_match"] for c in cases),
        "criterion_metrics": {
            **dict(counts),
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
        },
        "cases": cases,
        "limitation": "Invented labelled development contracts; not held-out parser accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--source-id", type=local_id)
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
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
            _, parsed = load_parses(Path("data/processed") / args.source_id)
            summary["unlabelled_audit"] = {
                "source_id": args.source_id,
                "source_manifest_sha256": file_hash(
                    Path("data/processed") / args.source_id / "manifest.json"
                ),
                "trials": len(parsed),
                "criteria": sum(len(p.criteria) for p in parsed),
                "types": dict(Counter(t for p in parsed for c in p.criteria for t in c.types)),
                "sections": dict(Counter(c.section for p in parsed for c in p.criteria)),
                "review_reasons": dict(
                    Counter(r for p in parsed for c in p.criteria for r in c.review_reasons)
                ),
                "numeric_constraints": sum(len(c.constraints) for p in parsed for c in p.criteria),
                "accuracy_measured": False,
            }
        summary.update(
            status="passed" if result["exact_trials"] == result["trials"] else "failed",
            parser_sha256=parser_hash(),
            fixture_sha256=file_hash(args.fixture),
            evaluator_sha256=file_hash(Path(__file__)),
            implementation_sha256=implementation_fingerprints(),
            runtime={"python": platform.python_version(), "pydantic": version("pydantic")},
            eligibility_assessments_performed=0,
        )
        write_json(output / "experiment.json", summary)
        print(json.dumps(summary, indent=2))
        if summary["status"] != "passed":
            parser.exit(1, "Labelled parsing checks failed; inspect per-trial errors.\n")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(1, "Criterion evaluation failed; inspect the local failure report.\n")


if __name__ == "__main__":
    main()
