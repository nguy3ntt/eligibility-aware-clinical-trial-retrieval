"""Inspect evidence-backed synthetic screening, with optional non-promoted NLI advisories."""

import argparse
import json
from pathlib import Path

from backend.app.services.eligibility.rules import verify
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.artifacts import load_parses, local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import DEFAULT_FIXTURE, load_pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--pair-id", default="demo-match")
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--cases", type=Path)
    sources.add_argument("--topics", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--source-id", type=local_id)
    parser.add_argument("--trial-id")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--output-id", type=local_id)
    args = parser.parse_args()
    external = bool(args.cases or args.topics)
    if (external and not all((args.case_id, args.source_id, args.trial_id))) or (
        not external and any((args.case_id, args.source_id, args.trial_id))
    ):
        parser.error(
            "source screening requires cases/topics, case-id, source-id and trial-id together"
        )
    output = Path("evaluation/reports") / args.output_id if args.output_id else None
    if output:
        try:
            output.mkdir(parents=True, exist_ok=False)
        except OSError:
            parser.exit(1, "Use a fresh output ID.\n")
    try:
        if external:
            cases = load_cases(args.cases or args.topics, topics=bool(args.topics))
            case = next((c for c in cases if c.case_id == args.case_id), None)
            _, documents = load_parses(Path("data/processed") / args.source_id)
            parsed = next((p for p in documents if p.source.trial_id == args.trial_id), None)
            if case is None or parsed is None:
                raise ValueError("unknown synthetic case or source trial ID")
        else:
            selected = next(
                (r for r in load_pairs(args.fixture) if r[0]["id"] == args.pair_id), None
            )
            if selected is None:
                raise ValueError("unknown invented pair ID")
            _, case, source = selected
            parsed = parse_eligibility(source)
        assessment = verify(extract_profile(case), parsed)
        result = {"screening": assessment.model_dump(mode="json"), "semantic": None}
        if args.semantic:
            from backend.app.services.eligibility.semantic import LocalNLI, advise

            result["semantic"] = advise(assessment, LocalNLI())
        if output:
            write_json(output / "screening.json", result)
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        if output:
            write_json(
                output / "failure.json", {"status": "failed", "error_type": type(exc).__name__}
            )
        parser.exit(
            1, f"Screening failed ({type(exc).__name__}); check sources and model contracts.\n"
        )


if __name__ == "__main__":
    main()
