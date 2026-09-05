"""Checked local snapshots and rebuilds; existing target collections are never replaced."""

import json
from pathlib import Path

from backend.app.repositories.qdrant import QdrantRepository
from pipelines.connectors.snapshots import write_json
from pipelines.embeddings import file_hash
from pipelines.indexing.qdrant import artifact_contract, import_index, make_point, verify_import

BACKUP_VERSION = "qdrant-backup-v1"


def verify_artifact_collection(repo: QdrantRepository, index: Path) -> tuple[dict, dict]:
    contract, rows, vectors = artifact_contract(index)
    points = [make_point(row, v, contract) for row, v in zip(rows, vectors, strict=True)]
    return contract, verify_import(repo, points, contract)


def create_backup(repo: QdrantRepository, index: Path, output: Path) -> dict:
    # Reserve a fresh directory; never overwrite a previous good or failed backup.
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "started.json", {"status": "running", "version": BACKUP_VERSION})
    try:
        contract, verification = verify_artifact_collection(repo, index)
        info = repo.hnsw_ready(contract)
        path = output / "collection.snapshot"
        snapshot = repo.download_snapshot(path)
        digest = file_hash(path)
        if snapshot.get("checksum") != digest or snapshot.get("size") != path.stat().st_size:
            raise ValueError("downloaded snapshot checksum or size differs from server")
        # No concurrent writers are supported; verify both sides of snapshot creation.
        verify_artifact_collection(repo, index)
        if repo.hnsw_ready(contract)["config"] != info["config"]:
            raise ValueError("collection configuration changed while creating snapshot")
        result = {
            "status": "complete",
            "version": BACKUP_VERSION,
            "server_version": repo.version(),
            "source_collection": repo.collection,
            "contract": contract,
            "collection_config": info["config"],
            "verification": verification,
            "server_snapshot": snapshot,
            "file": "collection.snapshot",
            "bytes": path.stat().st_size,
            "sha256": digest,
            "benchmark_comparable": False,
        }
        write_json(output / "manifest.json", result)
        return result
    except Exception as exc:
        write_json(
            output / "manifest.json",
            {"status": "failed", "version": BACKUP_VERSION, "error": str(exc)},
        )
        raise


def validate_backup(backup: Path, contract: dict) -> dict:
    manifest = json.loads((backup / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != BACKUP_VERSION
        or manifest.get("server_version") != "1.19.0"
        or manifest.get("contract") != contract
        or manifest.get("file") != "collection.snapshot"
    ):
        raise ValueError("backup is incomplete or incompatible with the artifact/server")
    path = backup / "collection.snapshot"
    if path.is_symlink() or path.stat().st_size != manifest.get("bytes"):
        raise ValueError("snapshot size or file type mismatch")
    if file_hash(path) != manifest.get("sha256"):
        raise ValueError("snapshot checksum mismatch; no recovery was attempted")
    return manifest


def restore_backup(repo: QdrantRepository, index: Path, backup: Path) -> dict:
    contract, _, _ = artifact_contract(index)
    manifest = validate_backup(backup, contract)
    repo.upload_snapshot(backup / "collection.snapshot", manifest["sha256"])
    _, verification = verify_artifact_collection(repo, index)
    info = repo.wait_hnsw(contract)
    if info["config"] != manifest["collection_config"]:
        raise ValueError("restored collection configuration differs from backup")
    return {
        "status": "verified",
        "operation": "restore",
        "verification": verification,
        "backup_manifest_sha256": file_hash(backup / "manifest.json"),
        "indexed_vectors": info["indexed_vectors_count"],
        "benchmark_comparable": False,
    }


def rebuild_index(repo: QdrantRepository, index: Path) -> dict:
    # Rebuild uses source artifacts only, never a snapshot or another collection.
    artifact_contract(index)
    repo.version()
    repo.require_absent()
    verification = import_index(repo, index)
    info = repo.configure_hnsw(artifact_contract(index)[0])
    return {
        "status": "verified",
        "operation": "rebuild",
        "verification": verification,
        "indexed_vectors": info["indexed_vectors_count"],
        "benchmark_comparable": False,
    }
