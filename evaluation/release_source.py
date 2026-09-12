"""Export Git-visible working files without staging, committing or including ignored state."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from pipelines.connectors.snapshots import write_json
from pipelines.embeddings import file_hash, file_record


def safe_source(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    source = root / relative
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or source.is_symlink()
        or not source.resolve().is_relative_to(root.resolve())
        or not source.is_file()
    ):
        raise ValueError("release requires contained regular files")
    return source


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def export(root: Path, output: Path) -> dict:
    root = root.resolve()
    names = sorted(
        set(
            git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
            .decode("utf-8")
            .strip("\0")
            .split("\0")
        )
    )
    if not names or not names[0] or output.exists():
        raise ValueError("nonempty Git inventory and fresh export directory required")
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--no-index", "--stdin", "-z"],
        input="\0".join(names).encode() + b"\0",
        capture_output=True,
    )
    if ignored.returncode not in (0, 1) or ignored.stdout:
        raise ValueError("Git-visible inventory contains ignored paths; review before release")
    # Validate the complete inventory before writing any copy. Git deletions require user review.
    sources = [(name, safe_source(root, name)) for name in names]
    output.mkdir(parents=True)
    source_root = output / "source"
    files = []
    for name, source in sources:
        destination = source_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        record = file_record(destination, source_root)
        if record["sha256"] != file_hash(source):
            raise ValueError("source changed during export; use a fresh export")
        files.append(record)
    manifest = {
        "version": "working-source-export-v1",
        "status": "complete",
        "base_commit": git(root, "rev-parse", "HEAD").decode().strip(),
        "working_tree_changed": bool(git(root, "status", "--porcelain")),
        "identity": "SHA256 of sorted path, bytes and SHA256 inventory; not a Git release tag",
        "source_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "files": files,
        "scope": "Git-visible source only; no ignored data, models, credentials or tracking",
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(Path.cwd(), args.output)
    print(json.dumps({k: result[k] for k in ("status", "source_sha256", "base_commit")}))


if __name__ == "__main__":
    main()
