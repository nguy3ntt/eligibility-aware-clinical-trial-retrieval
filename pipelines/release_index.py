"""Resumable, sharded exact index over every validated rendered trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from pipelines.connectors.snapshots import write_json
from pipelines.dense_artifacts import validate_document
from pipelines.embeddings import (
    MODELS,
    Encoder,
    LocalSentenceEncoder,
    file_hash,
    file_record,
    validate_vectors,
    verify_files,
)
from pipelines.render_trials import REPRESENTATIONS
from pipelines.render_trials import VERSION as RENDERER_VERSION

VERSION = "full-render-exact-index-v1"
REPRESENTATION = "title_conditions"
FROZEN_DOCUMENTS_SHA256 = "a7b133735968d60aa9562bdb8bf8a918345ce7302b12d66393f974cfe80dd84e"
FROZEN_DOCUMENT_COUNT = 375580


def source_contract(source: Path) -> dict:
    manifest = json.loads((source / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("renderer_version") != RENDERER_VERSION
        or manifest.get("representations")
        != {key: list(value) for key, value in REPRESENTATIONS.items()}
        or not isinstance(manifest.get("documents"), int)
        or manifest["documents"] < 1
    ):
        raise ValueError("completed versioned render required")
    verify_files(source, manifest["files"], {"documents.jsonl"})
    return {
        "manifest_sha256": file_hash(source / "manifest.json"),
        "documents_sha256": manifest["files"][0]["sha256"],
        "documents": manifest["documents"],
        "renderer_version": RENDERER_VERSION,
    }


def read_chunk(root: Path, record: dict) -> tuple[list[dict], np.ndarray]:
    verify_files(root, record["files"], {"documents.jsonl", "vectors.npy"})
    rows = [json.loads(line) for line in (root / "documents.jsonl").read_bytes().splitlines()]
    vectors = np.load(root / "vectors.npy", mmap_mode="r", allow_pickle=False)
    validate_vectors(vectors, len(rows), record["dimension"])
    if len(rows) != record["documents"] or len({r["trial_id"] for r in rows}) != len(rows):
        raise ValueError("chunk count or unique-ID mismatch")
    return rows, vectors


def build_index(
    source: Path,
    output: Path,
    encoder: Encoder,
    *,
    batch_size: int = 64,
    chunk_size: int = 4096,
    resume: bool = False,
) -> dict:
    if not 1 <= batch_size <= 256 or not 1 <= chunk_size <= 16384:
        raise ValueError("invalid batch or chunk size")
    contract = source_contract(source)
    intent = {
        "version": VERSION,
        "source": contract,
        "encoder": encoder.metadata,
        "representation": REPRESENTATION,
        "fields": list(REPRESENTATIONS[REPRESENTATION]),
        "batch_size": batch_size,
        "chunk_size": chunk_size,
        "batch_order": "stable_character_length_within_shard_then_restore_source_order",
        "implementation_sha256": file_hash(Path(__file__)),
    }
    if output.exists():
        if not resume or json.loads((output / "intent.json").read_bytes()) != intent:
            raise ValueError(
                "existing output requires explicit resume with identical inputs/config"
            )
        if (output / "manifest.json").exists():
            return verify_index(output)
    else:
        output.mkdir(parents=True)
        write_json(output / "intent.json", intent)
    started = time.perf_counter()
    seen: set[str] = set()
    chunks, pending = [], []
    input_digest = hashlib.sha256()

    def flush() -> None:
        ordinal = len(chunks)
        checkpoint = output / f"chunk-{ordinal:05d}.json"
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_bytes())
            folder = (output / saved["directory"]).resolve()
            if folder.parent != output.resolve():
                raise ValueError("unsafe chunk path")
            old_rows, _ = read_chunk(folder, saved)
            comparable = [{k: v for k, v in row.items() if k != "token_count"} for row in old_rows]
            if comparable != pending:
                raise ValueError("resumed source rows changed")
        else:
            # An interrupted uncommitted attempt remains inspectable. It is never overwritten.
            folder = output / f"part-{ordinal:05d}-{uuid.uuid4().hex[:12]}"
            folder.mkdir()
            if shutil.disk_usage(output).free < len(pending) * encoder.spec.dimension * 8:
                raise ValueError("insufficient free space for the next vector shard")
            values = np.empty((len(pending), encoder.spec.dimension), dtype=np.float32)
            token_counts = [0] * len(pending)
            order = sorted(range(len(pending)), key=lambda i: (len(pending[i]["text"]), i))
            for offset in range(0, len(pending), batch_size):
                selected = order[offset : offset + batch_size]
                batch = encoder.encode([pending[i]["text"] for i in selected])
                validate_vectors(batch.vectors, len(batch.token_counts), encoder.spec.dimension)
                values[selected] = batch.vectors
                for i, count in zip(selected, batch.token_counts, strict=True):
                    token_counts[i] = count
            validate_vectors(values, len(pending), encoder.spec.dimension)
            with (folder / "vectors.npy").open("xb") as handle:
                np.save(handle, values, allow_pickle=False)
            with (folder / "documents.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
                for row, tokens in zip(pending, token_counts, strict=True):
                    handle.write(json.dumps({**row, "token_count": tokens}, sort_keys=True) + "\n")
            saved = {
                "directory": folder.name,
                "documents": len(pending),
                "dimension": encoder.spec.dimension,
                "truncated": sum(n > encoder.spec.max_tokens for n in token_counts),
                "files": [
                    file_record(folder / name, folder)
                    for name in ("documents.jsonl", "vectors.npy")
                ],
            }
            write_json(checkpoint, saved)
        chunks.append({**saved, "checkpoint": file_record(checkpoint, output)})
        print(
            json.dumps({"encoded_or_verified": len(seen), "total": contract["documents"]}),
            flush=True,
        )
        pending.clear()

    try:
        with (source / "documents.jsonl").open("rb") as handle:
            for line, raw in enumerate(handle, 1):
                input_digest.update(raw)
                row = json.loads(raw)
                validate_document(row, line)
                if row["trial_id"] in seen:
                    raise ValueError(f"duplicate trial at line {line}")
                seen.add(row["trial_id"])
                text = row["representations"][REPRESENTATION]
                if not text.strip():
                    raise ValueError(f"empty retrieval representation at line {line}")
                pending.append(
                    {
                        "trial_id": row["trial_id"],
                        "text": text,
                        "content_sha256": row["content_sha256"],
                        "source": row["source"],
                        "filter_metadata": row["filter_metadata"],
                    }
                )
                if len(pending) == chunk_size:
                    flush()
        if pending:
            flush()
        if (
            len(seen) != contract["documents"]
            or input_digest.hexdigest() != contract["documents_sha256"]
        ):
            raise ValueError("source changed or document count mismatch")
        result = {
            **intent,
            "status": "complete",
            "chunks": chunks,
            "documents": len(seen),
            "truncated": sum(c["truncated"] for c in chunks),
            "elapsed_this_invocation_seconds": time.perf_counter() - started,
            "resumed": resume,
            "selection": "all_rendered_documents_no_qrel_selection",
            "eligibility_assessment": "not_performed",
        }
        write_json(output / "manifest.json", result)
        return verify_index(output)
    except Exception as exc:
        write_json(
            output / f"failure-{uuid.uuid4().hex}.json",
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "committed_chunks": len(chunks),
                "resume_requires_identical_intent": True,
            },
        )
        raise


def verify_index(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("status") != "complete" or manifest.get("version") != VERSION:
        raise ValueError("complete full-render index required")
    intent = json.loads((root / "intent.json").read_bytes())
    if any(manifest.get(key) != value for key, value in intent.items()):
        raise ValueError("index intent mismatch")
    ids, directories = set(), set()
    for ordinal, chunk in enumerate(manifest["chunks"]):
        name = f"chunk-{ordinal:05d}.json"
        verify_files(root, [chunk["checkpoint"]], {name})
        saved = json.loads((root / name).read_bytes())
        if saved != {k: v for k, v in chunk.items() if k != "checkpoint"}:
            raise ValueError("chunk checkpoint mismatch")
        folder = (root / chunk["directory"]).resolve()
        if folder.parent != root.resolve() or folder in directories:
            raise ValueError("unsafe or duplicate chunk path")
        directories.add(folder)
        rows, _ = read_chunk(folder, chunk)
        for row in rows:
            if row["trial_id"] in ids:
                raise ValueError("duplicate index trial")
            ids.add(row["trial_id"])
    if len(ids) != manifest["documents"] or len(ids) != manifest["source"]["documents"]:
        raise ValueError("index document count mismatch")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "verify"])
    parser.add_argument(
        "--source", type=Path, default=Path("data/processed/trec-ct-2021-render-v1")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        source = source_contract(args.source)
        if (
            source["documents_sha256"] != FROZEN_DOCUMENTS_SHA256
            or source["documents"] != FROZEN_DOCUMENT_COUNT
        ):
            parser.error("release CLI requires the frozen full TREC render")
        result = build_index(
            args.source,
            args.output,
            LocalSentenceEncoder(MODELS["minilm"], Path("models")),
            resume=args.resume,
        )
    else:
        result = verify_index(args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "documents": result["documents"],
                "truncated": result["truncated"],
            }
        )
    )


if __name__ == "__main__":
    main()
