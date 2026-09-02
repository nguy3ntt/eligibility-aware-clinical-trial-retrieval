"""Acquire or validate the frozen April 27, 2021 TREC trial corpus."""

import argparse
import json
from pathlib import Path

import httpx

from pipelines.connectors.trec_corpus import VERSION, acquire_archives, validate_corpus


def _safe_id(parser: argparse.ArgumentParser, value: str) -> str:
    if not value or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for char in value
    ):
        parser.error("run/output IDs must contain only letters, digits, hyphens, or underscores")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Download the five official historical archives")
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--resume", action="store_true")
    validate = commands.add_parser("validate", help="Validate a downloaded corpus offline")
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--output-id", required=True)
    validate.add_argument("--qrels", type=Path, required=True)
    args = parser.parse_args()
    run_id = _safe_id(parser, args.run_id)
    if args.command == "fetch":
        with httpx.Client(
            timeout=httpx.Timeout(60, read=120),
            follow_redirects=True,
            headers={"User-Agent": f"eligibility-aware-research/{VERSION}"},
        ) as client:
            result = acquire_archives(
                Path("data/raw") / run_id,
                client,
                resume=args.resume,
            )
        print(json.dumps({"status": result["status"], "archives": len(result["archives"])}))
        return
    output_id = _safe_id(parser, args.output_id)
    result = validate_corpus(
        Path("data/raw") / run_id,
        Path("data/interim") / output_id,
        args.qrels,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "trials": result["trial_records"],
                "missing_judged_ids": result["qrels"]["missing_from_corpus"],
                "issues": len(result["issues"]),
            }
        )
    )
    if result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
