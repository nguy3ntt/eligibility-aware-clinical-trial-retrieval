"""Bounded HTTP reads and write-once, checksummed source snapshots."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

MAX_RESPONSE_BYTES = 25 * 1024 * 1024


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def fetch_bytes(client: httpx.Client, url: str, params: dict | None = None) -> tuple[bytes, dict]:
    """Retry transient errors at most three times; cap body size and waits."""
    for attempt in range(3):
        try:
            with client.stream("GET", url, params=params) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("source response exceeds 25 MiB bound")
                return bytes(body), {
                    "url": str(response.url),
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "attempts": attempt + 1,
                }
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = isinstance(exc, httpx.TransportError) or exc.response.status_code in {
                429,
                500,
                502,
                503,
                504,
            }
            if not retryable or attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


class Snapshot:
    """An existing directory is never reused, including after interrupted acquisition."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=False)
        self.root = root
        self.files: list[dict] = []

    def capture(
        self, client: httpx.Client, name: str, url: str, params: dict | None = None
    ) -> bytes:
        raw, metadata = fetch_bytes(client, url, params)
        with (self.root / name).open("xb") as handle:
            handle.write(raw)
        self.files.append({"path": name, "sha256": sha256(raw), "bytes": len(raw), **metadata})
        # Sidecars survive interruption before the final manifest is written.
        write_json(self.root / f"{name}.source.json", self.files[-1])
        return raw


def verify_snapshot(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("status") != "complete":
        raise ValueError("snapshot is incomplete; inspect its acquisition issues")
    names = set()
    for source in manifest["files"]:
        path = (root / source["path"]).resolve()
        if path.parent != root.resolve() or source["path"] in names:
            raise ValueError("invalid or duplicate source path in manifest")
        names.add(source["path"])
        raw = path.read_bytes()
        if len(raw) != source["bytes"] or sha256(raw) != source["sha256"]:
            raise ValueError(f"snapshot checksum mismatch: {source['path']}")
    return manifest
