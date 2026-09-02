"""Run the full-corpus BM25 field and conservative-filter experiment."""

import argparse
import json
import re
from pathlib import Path

from evaluation.baselines.bm25 import run_experiment


def _id(parser: argparse.ArgumentParser, value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        parser.error("IDs must contain only letters, digits, hyphens, or underscores")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents-id", required=True)
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output-id", required=True)
    args = parser.parse_args()
    result = run_experiment(
        Path("data/processed") / _id(parser, args.documents_id),
        args.topics,
        args.qrels,
        Path("evaluation/reports") / _id(parser, args.output_id),
    )
    selected = result["selected_run"]
    representation, filter_name = selected.rsplit("-", 1)
    metrics = result["representations"][representation]["runs"][filter_name]["metrics"]
    print(json.dumps({"status": result["status"], "selected_run": selected, **metrics}))


if __name__ == "__main__":
    main()
