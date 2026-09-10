"""Prepare the pinned public relevance model; no synthetic case text is uploaded."""

import argparse
from pathlib import Path

from backend.app.services.retrieval.reranker import (
    FILES,
    MODEL_DIR,
    REPOSITORY,
    REVISION,
    validate_snapshot,
)
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash
from pipelines.prepare_nli import download_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = Path("models") / MODEL_DIR
    try:
        if (root / "snapshot.json").exists():
            validate_snapshot(root)
        else:
            from huggingface_hub import hf_hub_download

            root.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                hf_hub_download(
                    REPOSITORY,
                    name,
                    revision=REVISION,
                    local_dir=download_directory(root),
                    token=False,
                )
            write_json(
                root / "snapshot.json",
                {
                    "status": "complete",
                    "repository": REPOSITORY,
                    "revision": REVISION,
                    "files": {name: file_hash(root / name) for name in FILES},
                    "license": "apache-2.0",
                    "format": "safetensors",
                    "remote_code": False,
                },
            )
            validate_snapshot(root)
    except Exception as exc:
        parser.exit(1, f"Reranker preparation failed ({type(exc).__name__}); no case text sent.\n")
    print("Pinned reranker snapshot verified locally.")


if __name__ == "__main__":
    main()
