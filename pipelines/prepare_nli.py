"""Download only the pinned public NLI safetensors/tokenizer snapshot; never send case text."""

import argparse
import os
from pathlib import Path

from backend.app.services.eligibility.semantic import (
    FILES,
    MODEL_DIR,
    REPOSITORY,
    REVISION,
    validate_snapshot,
)
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash


def download_directory(root):
    path = str(root.resolve())
    if os.name == "nt":
        path = "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = Path("models") / MODEL_DIR
    if (root / "snapshot.json").exists():
        validate_snapshot(root)
        print("Pinned NLI snapshot verified; no download needed.")
        return
    from huggingface_hub import hf_hub_download

    root.mkdir(parents=True, exist_ok=True)
    try:
        for name in FILES:
            hf_hub_download(
                REPOSITORY, name, revision=REVISION, local_dir=download_directory(root), token=False
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
        # The partial snapshot cannot load without a valid completion manifest.
        parser.exit(1, f"NLI preparation failed ({type(exc).__name__}); no case text was sent.\n")
    print("Pinned NLI snapshot prepared and verified locally.")


if __name__ == "__main__":
    main()
