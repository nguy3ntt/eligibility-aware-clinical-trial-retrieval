"""Inspect invented criteria or prepare a bounded original-XML parsing artifact."""

import argparse
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import fixture_sources, historical_sources, local_id, save_parses
from pipelines.criteria.parser import parse_eligibility

DEFAULT_FIXTURE = Path("evaluation/data/fixtures/eligibility_criteria.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "prepare"])
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--trial-id", default="NCT00000001")
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--snapshot-id", type=local_id, default="trec-ct-2021-20210427")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output-id", type=local_id)
    args = parser.parse_args()
    output = None
    if args.command == "prepare":
        if not args.output_id:
            parser.error("prepare requires a fresh --output-id")
        output = Path("data/processed") / args.output_id
        try:
            output.mkdir(parents=True, exist_ok=False)
        except OSError:
            parser.exit(1, "Use a fresh output ID.\n")
    try:
        if args.command == "demo":
            sources, _ = fixture_sources(args.fixture)
            source = next((s for s in sources if s.trial_id == args.trial_id), None)
            if source is None:
                raise ValueError("unknown invented trial ID")
            result = parse_eligibility(source).model_dump(mode="json")
        else:
            sources = historical_sources(
                Path("data/processed") / args.index_id,
                Path("data/raw") / args.snapshot_id,
                args.limit,
            )
            result = save_parses(output, sources)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile) as exc:
        if output:
            write_json(
                output / "failure.json", {"status": "failed", "error_type": type(exc).__name__}
            )
        parser.exit(
            1,
            f"Criteria parsing failed ({type(exc).__name__}); inspect source/failure evidence.\n",
        )


if __name__ == "__main__":
    main()
