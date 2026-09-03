"""Bounded corpus sampling and immutable, auditable dense-vector artifacts."""

from __future__ import annotations

import hashlib
import heapq
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from pipelines.connectors.snapshots import sha256, write_json
from pipelines.connectors.trec import NCT_ID
from pipelines.embeddings import Encoder, file_hash, file_record, validate_vectors, verify_files
from pipelines.render_trials import REPRESENTATIONS
from pipelines.render_trials import VERSION as RENDERER_VERSION

SAMPLE_VERSION = "dense-sample-v1"
INDEX_VERSION = "dense-index-v1"
MAX_SAMPLE = 512


def validate_document(row: dict, line: int) -> None:
    trial_id = row.get("trial_id")
    if (
        not isinstance(trial_id, str)
        or not NCT_ID.fullmatch(trial_id)
        or row.get("renderer_version") != RENDERER_VERSION
        or not isinstance(row.get("source"), dict)
        or not {"archive", "archive_sha256", "member", "crc32"} <= row["source"].keys()
        or not isinstance(row.get("representations"), dict)
        or any(not isinstance(row["representations"].get(key), str) for key in REPRESENTATIONS)
    ):
        raise ValueError(f"invalid rendered document at line {line}")
    payload = {key: value for key, value in row.items() if key != "content_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if sha256(canonical.encode()) != row.get("content_sha256"):
        raise ValueError(f"rendered row checksum mismatch at line {line}")


def _failure(output: Path, version: str, exc: Exception) -> None:
    write_json(
        output / "validation-issues.json",
        [
            {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        ],
    )
    write_json(output / "manifest.json", {"status": "failed", "version": version})


def sample_documents(
    source: Path, output: Path, *, limit: int = 256, seed: str = "dense-smoke-v1"
) -> dict:
    """Select by hashed NCT ID, independent of queries and qrels; verify the full input."""
    if not 1 <= limit <= MAX_SAMPLE or not seed.strip():
        raise ValueError(f"sample limit must be 1..{MAX_SAMPLE} and seed must not be empty")
    output.mkdir(parents=True, exist_ok=False)
    try:
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        if (
            manifest.get("status") != "complete"
            or manifest.get("renderer_version") != RENDERER_VERSION
            or manifest.get("representations")
            != {name: list(fields) for name, fields in REPRESENTATIONS.items()}
        ):
            raise ValueError("a completed versioned historical render is required")
        records = manifest["files"]
        if len(records) != 1 or records[0]["path"] != "documents.jsonl":
            raise ValueError("unexpected rendered file inventory")
        digest = hashlib.sha256()
        seen: set[str] = set()
        byte_count = 0

        def rows():
            nonlocal byte_count
            with (source / "documents.jsonl").open("rb") as handle:
                for number, raw in enumerate(handle, 1):
                    digest.update(raw)
                    byte_count += len(raw)
                    row = json.loads(raw)
                    validate_document(row, number)
                    trial_id = row["trial_id"]
                    if trial_id in seen:
                        raise ValueError(f"duplicate trial ID at line {number}")
                    seen.add(trial_id)
                    yield row

        selected = heapq.nsmallest(
            limit,
            rows(),
            key=lambda row: (sha256(f"{seed}:{row['trial_id']}".encode()), row["trial_id"]),
        )
        if (
            digest.hexdigest() != records[0]["sha256"]
            or byte_count != records[0]["bytes"]
            or len(seen) != manifest["documents"]
            or len(selected) != limit
        ):
            raise ValueError("rendered corpus checksum, count, or requested sample size mismatch")
        selected.sort(key=lambda row: row["trial_id"])
        with (output / "documents.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
            for row in selected:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        result = {
            "status": "complete",
            "version": SAMPLE_VERSION,
            "documents": len(selected),
            "source_documents": len(seen),
            "selection": {"method": "lowest_sha256_seed_colon_nct_id", "seed": seed},
            "source_manifest_sha256": file_hash(manifest_path),
            "source_documents_sha256": digest.hexdigest(),
            "benchmark_metrics_permitted": False,
            "files": [file_record(output / "documents.jsonl", output)],
        }
        write_json(output / "manifest.json", result)
        return result
    except Exception as exc:
        _failure(output, SAMPLE_VERSION, exc)
        raise


def load_sample(root: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != SAMPLE_VERSION
        or manifest.get("benchmark_metrics_permitted") is not False
        or not 1 <= manifest.get("documents", 0) <= MAX_SAMPLE
    ):
        raise ValueError("a completed bounded sample is required")
    verify_files(root, manifest["files"], {"documents.jsonl"})
    rows = [json.loads(line) for line in (root / "documents.jsonl").read_bytes().splitlines()]
    for number, row in enumerate(rows, 1):
        validate_document(row, number)
    if len(rows) != manifest["documents"] or len({r["trial_id"] for r in rows}) != len(rows):
        raise ValueError("sample row count or unique-ID check failed")
    return manifest, rows


def _code_provenance() -> dict:
    root = Path(__file__).resolve().parent.parent
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return {
        "base_git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "source_sha256": {
            name: file_hash(root / "pipelines" / name)
            for name in ("embeddings.py", "dense_artifacts.py", "render_trials.py")
        },
        "note": "Source hashes identify working files, including uncommitted changes.",
    }


def encode_sample(
    sample: Path,
    output: Path,
    encoder: Encoder,
    *,
    representation: str = "summary",
    batch_size: int = 16,
) -> dict:
    if representation not in REPRESENTATIONS or not 1 <= batch_size <= 32:
        raise ValueError("unknown representation or batch size outside 1..32")
    _, rows = load_sample(sample)
    output.mkdir(parents=True, exist_ok=False)
    try:
        vectors = np.empty((len(rows), encoder.spec.dimension), dtype=np.float32)
        audits = []
        started = time.perf_counter()
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            texts = [row["representations"][representation] for row in batch]
            if any(not text.strip() for text in texts):
                raise ValueError(f"empty representation in batch starting at row {start + 1}")
            encoded = encoder.encode(texts)
            validate_vectors(encoded.vectors, len(batch), encoder.spec.dimension)
            if len(encoded.token_counts) != len(batch) or any(
                not isinstance(count, int) or count < 1 for count in encoded.token_counts
            ):
                raise ValueError("encoder token-count audit mismatch")
            vectors[start : start + len(batch)] = encoded.vectors
            for row, text, tokens in zip(batch, texts, encoded.token_counts, strict=True):
                audits.append(
                    {
                        "trial_id": row["trial_id"],
                        "input_sha256": sha256(text.encode()),
                        "tokens_before_truncation": tokens,
                        "truncated": tokens > encoder.spec.max_tokens,
                    }
                )
        seconds = time.perf_counter() - started
        validate_vectors(vectors, len(rows), encoder.spec.dimension)
        np.save(output / "vectors.npy", vectors, allow_pickle=False)
        shutil.copyfile(sample / "documents.jsonl", output / "documents.jsonl")
        write_json(output / "encoding-audit.json", audits)
        result = {
            "status": "complete",
            "version": INDEX_VERSION,
            "documents": len(rows),
            "dimension": encoder.spec.dimension,
            "sample_manifest_sha256": file_hash(sample / "manifest.json"),
            "sample_documents_sha256": file_hash(sample / "documents.jsonl"),
            "encoder": encoder.metadata,
            "code": _code_provenance(),
            "template": {
                "version": "rendered-representation-identity-v1",
                "renderer": RENDERER_VERSION,
                "representation": representation,
                "fields": list(REPRESENTATIONS[representation]),
                "prompt": "",
                "chunking": "none",
            },
            "batch_size": batch_size,
            "encoding_seconds": seconds,
            "documents_per_second": len(rows) / seconds,
            "vector_bytes": vectors.nbytes,
            "truncated_documents": sum(row["truncated"] for row in audits),
            "benchmark_metrics_permitted": False,
            "eligibility_assessments_performed": 0,
            "files": [
                file_record(output / name, output)
                for name in (
                    "vectors.npy",
                    "documents.jsonl",
                    "encoding-audit.json",
                )
            ],
        }
        write_json(output / "manifest.json", result)
        return result
    except Exception as exc:
        _failure(output, INDEX_VERSION, exc)
        raise


def load_index(root: Path) -> tuple[dict, list[dict], np.ndarray]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != INDEX_VERSION
        or manifest.get("benchmark_metrics_permitted") is not False
        or not 1 <= manifest.get("documents", 0) <= MAX_SAMPLE
    ):
        raise ValueError("a completed bounded dense index is required")
    verify_files(root, manifest["files"], {"vectors.npy", "documents.jsonl", "encoding-audit.json"})
    rows = [json.loads(line) for line in (root / "documents.jsonl").read_bytes().splitlines()]
    for number, row in enumerate(rows, 1):
        validate_document(row, number)
    if len(rows) != manifest["documents"] or len({r["trial_id"] for r in rows}) != len(rows):
        raise ValueError("index row count or unique-ID check failed")
    vectors = np.load(root / "vectors.npy", allow_pickle=False, mmap_mode="r")
    validate_vectors(vectors, len(rows), manifest["dimension"])
    audits = json.loads((root / "encoding-audit.json").read_bytes())
    if [row["trial_id"] for row in audits] != [row["trial_id"] for row in rows]:
        raise ValueError("encoding audit is not aligned with documents")
    return manifest, rows, vectors
