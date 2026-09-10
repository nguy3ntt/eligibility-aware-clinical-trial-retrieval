"""Extract evidence-backed facts from explicit synthetic fixtures or TREC topics."""

import argparse
import json
from pathlib import Path

from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.patient_extraction.filters import build_filter_plan
from pipelines.connectors.synthetic_cases import load_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--topics", type=Path)
    source.add_argument("--cases", type=Path)
    parser.add_argument("--case-id", required=True, help="Full case ID, e.g. trec-ct-2022:29")
    args = parser.parse_args()
    try:
        cases = load_cases(args.topics or args.cases, topics=args.topics is not None)
        case = next((c for c in cases if c.case_id == args.case_id), None)
        if case is None:
            raise ValueError("unknown synthetic case ID")
        profile = extract_profile(case)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "profile": profile.model_dump(mode="json"),
                    "filter_plan": build_filter_plan(profile),
                },
                indent=2,
            )
        )
    except (ValueError, OSError) as exc:
        # Do not print validation exceptions that could echo rejected input text.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "issues": getattr(exc, "issues", []),
                }
            )
        )
        parser.exit(
            1, f"Fact extraction failed ({type(exc).__name__}); check source format and case ID.\n"
        )


if __name__ == "__main__":
    main()
