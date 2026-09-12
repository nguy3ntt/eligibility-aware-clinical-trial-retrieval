"""Bounded, resumable registry updates; never merge current data into TREC evidence."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

from pipelines.connectors.clinicaltrials import API_ROOT, study_id
from pipelines.connectors.snapshots import fetch_bytes, sha256, write_json
from pipelines.connectors.trec import NCT_ID, SourceValidationError
from pipelines.criteria.artifacts import file_hash, local_id

VERSION = "registry-incremental-v1"


def capture(client: httpx.Client, root: Path, url: str, params=None) -> dict:
    raw, metadata = fetch_bytes(client, url, params)
    name = f"response-{uuid.uuid4().hex}.json"
    with (root / name).open("xb") as handle:
        handle.write(raw)
    record = {"path": name, "sha256": sha256(raw), "bytes": len(raw), **metadata}
    write_json(root / f"{name}.source.json", record)
    return record


def read_record(root: Path, record: dict):
    path = (root / record["path"]).resolve()
    if path.parent != root.resolve() or path.stat().st_size != record["bytes"]:
        raise ValueError("invalid source path or byte count")
    if file_hash(path) != record["sha256"]:
        raise ValueError("registry snapshot checksum mismatch")
    return json.loads(path.read_bytes())


def version_identity(value) -> dict:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(k), str) or not value[k] for k in ("apiVersion", "dataTimestamp")
    ):
        raise ValueError("API version and data timestamp required")
    return {k: value[k] for k in ("apiVersion", "dataTimestamp")}


def validate_page(
    payload, scope: list[str], start: date, until: date, seen: set[str]
) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
        raise ValueError("expected a studies page")
    issues = []
    for i, study in enumerate(payload["studies"]):
        trial_id = study_id(study)
        reason = None
        if trial_id is None or (scope and trial_id not in scope) or trial_id in seen:
            reason = "invalid, unrequested or duplicate trial ID"
        else:
            try:
                protocol = study["protocolSection"]
                updated = date.fromisoformat(
                    protocol["statusModule"]["lastUpdatePostDateStruct"]["date"]
                )
                title = protocol["identificationModule"]["briefTitle"]
                if not start <= updated <= until or not isinstance(title, str) or not title.strip():
                    raise ValueError("invalid window or title")
            except (KeyError, TypeError, ValueError):
                reason = "missing/invalid update date, title or out-of-window record"
        if reason:
            issues.append({"locator": f"/studies/{i}", "reason": reason})
        else:
            seen.add(trial_id)
    return issues


def acquire(
    client: httpx.Client,
    root: Path,
    *,
    start: date,
    until: date,
    scope: list[str],
    max_pages: int = 100,
    page_size: int = 100,
    resume: bool = False,
) -> dict:
    if (
        start > until
        or until > date.today()
        or not 1 <= max_pages <= 1000
        or not 1 <= page_size <= 100
    ):
        raise ValueError("invalid bounded date window or page limits")
    if (
        len(scope) > 1000
        or len(scope) != len(set(scope))
        or any(not NCT_ID.fullmatch(i) for i in scope)
    ):
        raise ValueError("scope must contain at most 1000 unique NCT IDs")
    intent = {
        "version": VERSION,
        "start": start.isoformat(),
        "until": until.isoformat(),
        "scope": sorted(scope),
        "max_pages": max_pages,
        "page_size": page_size,
        "code_sha256": file_hash(Path(__file__)),
    }
    if root.exists():
        if not resume or json.loads((root / "intent.json").read_bytes()) != intent:
            raise ValueError("resume requires identical acquisition configuration")
        if (root / "manifest.json").exists():
            return verify_acquisition(root)
    else:
        root.mkdir(parents=True)
        write_json(root / "intent.json", intent)
    try:
        version_file = root / "version.json"
        if not version_file.exists():
            write_json(version_file, capture(client, root, f"{API_ROOT}/version"))
        before = json.loads(version_file.read_bytes())
        identity = version_identity(read_record(root, before))
        if resume:
            fresh = capture(client, root, f"{API_ROOT}/version")
            if version_identity(read_record(root, fresh)) != identity:
                raise ValueError(
                    "registry changed; start a fresh snapshot from the previous watermark"
                )
        pages, seen, tokens = [], set(), set()
        token = None
        for number in range(max_pages):
            params = {
                "format": "json",
                "pageSize": page_size,
                "query.term": f"AREA[LastUpdatePostDate]RANGE[{start},{until}]",
                "sort": "LastUpdatePostDate:asc",
            }
            if scope:
                params["filter.ids"] = ",".join(sorted(scope))
            if token:
                params["pageToken"] = token
            checkpoint = root / f"page-{number:05d}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_bytes())
                if saved["params"] != params:
                    raise ValueError("checkpoint cursor or query mismatch")
            else:
                saved = {
                    "params": params,
                    "source": capture(client, root, f"{API_ROOT}/studies", params),
                }
                write_json(checkpoint, saved)
            payload = read_record(root, saved["source"])
            issues = validate_page(payload, scope, start, until, seen)
            if len(payload["studies"]) > page_size:
                issues.append({"reason": "page exceeded requested size"})
            if issues:
                write_json(
                    root / f"validation-{uuid.uuid4().hex}.json", {"page": number, "issues": issues}
                )
                raise SourceValidationError(issues)
            pages.append(saved)
            token = payload.get("nextPageToken")
            if token is None:
                break
            if not isinstance(token, str) or not token or token in tokens or not payload["studies"]:
                raise ValueError("invalid, repeated or empty-page cursor")
            tokens.add(token)
        else:
            raise ValueError(
                "page budget exhausted; watermark not advanced; use a smaller date window"
            )
        after = capture(client, root, f"{API_ROOT}/version")
        if version_identity(read_record(root, after)) != identity:
            raise ValueError("registry changed during acquisition; watermark not advanced")
        result = {
            **intent,
            "status": "complete",
            "version_before": before,
            "version_after": after,
            "api_identity": identity,
            "pages": pages,
            "records": len(seen),
            "benchmark_comparable": False,
        }
        write_json(root / "manifest.json", result)
        return verify_acquisition(root)
    except Exception as exc:
        write_json(
            root / f"failure-{uuid.uuid4().hex}.json",
            {"status": "failed", "error_type": type(exc).__name__, "watermark_advanced": False},
        )
        raise


def verify_acquisition(root: Path) -> dict:
    m = json.loads((root / "manifest.json").read_bytes())
    intent = json.loads((root / "intent.json").read_bytes())
    if any(m.get(key) != value for key, value in intent.items()):
        raise ValueError("snapshot acquisition intent mismatch")
    if (
        m.get("status") != "complete"
        or m.get("version") != VERSION
        or m.get("benchmark_comparable") is not False
    ):
        raise ValueError("completed current-registry snapshot required")
    if (
        version_identity(read_record(root, m["version_before"])) != m["api_identity"]
        or version_identity(read_record(root, m["version_after"])) != m["api_identity"]
    ):
        raise ValueError("snapshot API identity mismatch")
    if not 1 <= len(m["pages"]) <= m["max_pages"]:
        raise ValueError("snapshot page budget mismatch")
    seen, previous, tokens = set(), None, set()
    for page in m["pages"]:
        expected = {
            "format": "json",
            "pageSize": m["page_size"],
            "query.term": f"AREA[LastUpdatePostDate]RANGE[{m['start']},{m['until']}]",
            "sort": "LastUpdatePostDate:asc",
        }
        if m["scope"]:
            expected["filter.ids"] = ",".join(m["scope"])
        if previous:
            expected["pageToken"] = previous
        if page["params"] != expected:
            raise ValueError("snapshot cursor chain mismatch")
        payload = read_record(root, page["source"])
        issues = validate_page(
            payload,
            m["scope"],
            date.fromisoformat(m["start"]),
            date.fromisoformat(m["until"]),
            seen,
        )
        if issues:
            raise SourceValidationError(issues)
        if len(payload["studies"]) > m["page_size"]:
            raise ValueError("snapshot page size mismatch")
        previous = payload.get("nextPageToken")
        if previous is not None:
            if (
                not isinstance(previous, str)
                or not previous
                or previous in tokens
                or not payload["studies"]
            ):
                raise ValueError("invalid snapshot cursor")
            tokens.add(previous)
        elif page is not m["pages"][-1]:
            raise ValueError("pages after terminal cursor")
    if previous is not None or len(seen) != m["records"] or not m["pages"]:
        raise ValueError("incomplete cursor chain or record count mismatch")
    return m


def load_registry(root: Path) -> tuple[dict, dict]:
    m = json.loads((root / "manifest.json").read_bytes())
    if (
        m.get("status") != "complete"
        or m.get("version") != VERSION
        or m.get("benchmark_comparable") is not False
    ):
        raise ValueError("completed registry artifact required")
    records = read_record(root, m["file"])
    if not isinstance(records, list) or len(records) != m["records"]:
        raise ValueError("registry count mismatch")
    rows = {}
    for row in records:
        canonical = json.dumps(row["study"], sort_keys=True, separators=(",", ":")).encode()
        if (
            study_id(row["study"]) != row["trial_id"]
            or sha256(canonical) != row["content_sha256"]
            or row["trial_id"] in rows
        ):
            raise ValueError("registry identity, hash or uniqueness mismatch")
        rows[row["trial_id"]] = row
    return m, rows


def materialize(snapshot: Path, output: Path, previous: Path | None = None) -> dict:
    acquired = verify_acquisition(snapshot)
    old, rows = load_registry(previous) if previous else (None, {})
    if old and (
        old["scope"] != acquired["scope"]
        or date.fromisoformat(acquired["start"]) > date.fromisoformat(old["watermark"])
        or date.fromisoformat(acquired["until"]) < date.fromisoformat(old["watermark"])
    ):
        raise ValueError(
            "incremental chain requires identical scope and overlapping non-regressing window"
        )
    output.mkdir(parents=True, exist_ok=False)
    counts = {"added": 0, "changed": 0, "unchanged": 0}
    for page in acquired["pages"]:
        for i, study in enumerate(read_record(snapshot, page["source"])["studies"]):
            trial_id = study_id(study)
            digest = sha256(json.dumps(study, sort_keys=True, separators=(",", ":")).encode())
            previous_row = rows.get(trial_id)
            if previous_row:
                old_date = previous_row["study"]["protocolSection"]["statusModule"][
                    "lastUpdatePostDateStruct"
                ]["date"]
                new_date = study["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"][
                    "date"
                ]
                if date.fromisoformat(new_date) < date.fromisoformat(old_date):
                    raise ValueError("record update date regressed; registry not published")
            state = (
                "added"
                if previous_row is None
                else "unchanged"
                if digest == previous_row["content_sha256"]
                else "changed"
            )
            counts[state] += 1
            rows[trial_id] = {
                "trial_id": trial_id,
                "content_sha256": digest,
                "study": study,
                "source": {
                    "snapshot_manifest_sha256": file_hash(snapshot / "manifest.json"),
                    "response_sha256": page["source"]["sha256"],
                    "response_file": page["source"]["path"],
                    "locator": f"/studies/{i}",
                },
            }
    write_json(output / "registry.json", [rows[key] for key in sorted(rows)])
    result = {
        "version": VERSION,
        "status": "complete",
        "scope": acquired["scope"],
        "watermark": acquired["until"],
        "next_start_with_overlap": (
            date.fromisoformat(acquired["until"]) - timedelta(days=1)
        ).isoformat(),
        "records": len(rows),
        "counts": counts,
        "snapshot_manifest_sha256": file_hash(snapshot / "manifest.json"),
        "previous_manifest_sha256": file_hash(previous / "manifest.json") if previous else None,
        "file": {
            "path": "registry.json",
            "bytes": (output / "registry.json").stat().st_size,
            "sha256": file_hash(output / "registry.json"),
        },
        "benchmark_comparable": False,
        "deletion_inference": "never; absent records retained",
        "active_catalog_changed": False,
    }
    write_json(output / "manifest.json", result)
    load_registry(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "apply", "verify"])
    parser.add_argument("--snapshot-id", required=True, type=local_id)
    parser.add_argument("--output-id", type=local_id)
    parser.add_argument("--previous-id", type=local_id)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--ids", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    root = Path("data/raw") / args.snapshot_id
    if args.action == "fetch":
        if not args.start or not args.until:
            parser.error("fetch requires explicit start and until dates")
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            result = acquire(
                client,
                root,
                start=args.start,
                until=args.until,
                scope=args.ids.split(",") if args.ids else [],
                resume=args.resume,
                max_pages=args.max_pages,
                page_size=args.page_size,
            )
    elif args.action == "apply":
        if not args.output_id:
            parser.error("apply requires a fresh output ID")
        result = materialize(
            root,
            Path("data/processed") / args.output_id,
            Path("data/processed") / args.previous_id if args.previous_id else None,
        )
    else:
        result = verify_acquisition(root)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "records", "counts", "watermark")
                if key in result
            }
        )
    )


if __name__ == "__main__":
    main()
