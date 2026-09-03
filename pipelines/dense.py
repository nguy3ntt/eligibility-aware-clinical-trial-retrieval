"""Prepare a bounded, reproducible dense retrieval smoke experiment."""

import argparse
import json
import re
from pathlib import Path

from pipelines.dense_artifacts import encode_sample, sample_documents
from pipelines.embeddings import MODELS, LocalSentenceEncoder, prepare_model


def local_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise argparse.ArgumentTypeError(
            "IDs may only contain letters, numbers, hyphens, underscores"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-model", help="Download pinned public model weights")
    prepare.add_argument("--model", choices=MODELS, required=True)
    sample = commands.add_parser("sample", help="Validate corpus and select at most 512 trials")
    sample.add_argument("--documents-id", type=local_id, required=True)
    sample.add_argument("--output-id", type=local_id, required=True)
    sample.add_argument("--limit", type=int, default=256)
    sample.add_argument("--seed", default="dense-smoke-v1")
    encode = commands.add_parser("encode", help="Encode a validated sample offline on CPU")
    encode.add_argument("--sample-id", type=local_id, required=True)
    encode.add_argument("--output-id", type=local_id, required=True)
    encode.add_argument("--model", choices=MODELS, required=True)
    encode.add_argument(
        "--representation",
        choices=["title_conditions", "summary", "eligibility"],
        default="summary",
    )
    encode.add_argument("--batch-size", type=int, default=16)
    encode.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        if args.command == "prepare-model":
            print(prepare_model(MODELS[args.model], Path("models")))
            return
        if args.command == "sample":
            result = sample_documents(
                Path("data/processed") / args.documents_id,
                Path("data/processed") / args.output_id,
                limit=args.limit,
                seed=args.seed,
            )
        else:
            encoder = LocalSentenceEncoder(MODELS[args.model], Path("models"), threads=args.threads)
            result = encode_sample(
                Path("data/processed") / args.sample_id,
                Path("data/processed") / args.output_id,
                encoder,
                representation=args.representation,
                batch_size=args.batch_size,
            )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "documents",
                        "benchmark_metrics_permitted",
                    )
                }
            )
        )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Dense preparation failed: {exc}\n")


if __name__ == "__main__":
    main()
