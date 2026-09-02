"""Acquire and validate the frozen TREC Clinical Trials 2021 XML corpus."""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import httpx

from pipelines.connectors.snapshots import sha256, write_json
from pipelines.connectors.trec import NCT_ID

SOURCE_PAGE = "https://www.trec-cds.org/2021.html"
SOURCE_ROOT = "https://www.trec-cds.org/2021_data"
CORPUS_DATE = "2021-04-27"
EXPECTED_TRIALS = 375_580
MAX_XML_BYTES = 10 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
VERSION = "trec-ct-2021-corpus-v1"
CONTENTS_MEMBER = "ClinicalTrials.2021-04-27.part5/Contents.txt"
CONTENTS_SHA256 = "d4ea614c5a596ce5451cd37825c9bb3b3f0d1928d8149c4cde28a376f6c8c512"


@dataclass(frozen=True)
class ArchiveSpec:
    name: str
    bytes: int
    last_modified: str

    @property
    def url(self) -> str:
        return f"{SOURCE_ROOT}/{self.name}"


ARCHIVES = (
    ArchiveSpec(
        "ClinicalTrials.2021-04-27.part1.zip",
        382_792_518,
        "Wed, 28 Apr 2021 20:55:58 GMT",
    ),
    ArchiveSpec(
        "ClinicalTrials.2021-04-27.part2.zip",
        378_478_271,
        "Wed, 28 Apr 2021 20:56:04 GMT",
    ),
    ArchiveSpec(
        "ClinicalTrials.2021-04-27.part3.zip",
        375_998_752,
        "Wed, 28 Apr 2021 20:57:24 GMT",
    ),
    ArchiveSpec(
        "ClinicalTrials.2021-04-27.part4.zip",
        360_825_058,
        "Wed, 28 Apr 2021 21:40:04 GMT",
    ),
    ArchiveSpec(
        "ClinicalTrials.2021-04-27.part5.zip",
        296_625_845,
        "Wed, 28 Apr 2021 21:42:17 GMT",
    ),
)

FIELD_PATHS = {
    "brief_title": "brief_title",
    "official_title": "official_title",
    "brief_summary": "brief_summary/textblock",
    "detailed_description": "detailed_description/textblock",
    "overall_status": "overall_status",
    "study_type": "study_type",
    "phase": "phase",
    "conditions": "condition",
    "interventions": "intervention/intervention_name",
    "eligibility_text": "eligibility/criteria/textblock",
    "sex": "eligibility/gender",
    "minimum_age": "eligibility/minimum_age",
    "maximum_age": "eligibility/maximum_age",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _code_hash() -> str:
    return sha256(Path(__file__).read_bytes())


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_range_start(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes (\d+)-\d+/\d+", value)
    return int(match.group(1)) if match else None


def _stream_response(response: httpx.Response, handle: BinaryIO, maximum: int) -> int:
    written = handle.tell()
    for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
        handle.write(chunk)
        written += len(chunk)
        if written > maximum:
            raise ValueError("archive response exceeds its recorded byte size")
    handle.flush()
    os.fsync(handle.fileno())
    return written


def _download_one(staging: Path, spec: ArchiveSpec, client: httpx.Client) -> dict[str, object]:
    final = staging / spec.name
    partial = staging / f"{spec.name}.part"
    if final.exists():
        if final.stat().st_size != spec.bytes:
            raise ValueError(f"completed archive has unexpected size: {spec.name}")
        return {
            **asdict(spec),
            "url": spec.url,
            "sha256": _file_sha256(final),
            "retrieved_at_utc": None,
            "resumed_from_bytes": spec.bytes,
        }

    offset = partial.stat().st_size if partial.exists() else 0
    if offset > spec.bytes:
        raise ValueError(f"partial archive exceeds expected size: {spec.name}")
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", spec.url, headers=headers) as response:
        response.raise_for_status()
        mode = "ab" if offset else "xb"
        if offset:
            range_start = _content_range_start(response.headers.get("content-range"))
            if response.status_code == 206 and range_start == offset:
                pass
            elif response.status_code == 200:
                partial.unlink()
                offset = 0
                mode = "xb"
            else:
                raise ValueError(f"server did not honor archive resume range: {spec.name}")
        modified = response.headers.get("last-modified")
        if modified != spec.last_modified:
            raise ValueError(f"official archive timestamp changed: {spec.name}")
        with partial.open(mode) as handle:
            total = _stream_response(response, handle, spec.bytes)
    if total != spec.bytes:
        raise ValueError(f"archive byte size mismatch: {spec.name}")
    partial.replace(final)
    return {
        **asdict(spec),
        "url": spec.url,
        "sha256": _file_sha256(final),
        "retrieved_at_utc": _utc_now(),
        "resumed_from_bytes": offset,
    }


def acquire_archives(
    destination: Path,
    client: httpx.Client,
    *,
    resume: bool = False,
    archives: tuple[ArchiveSpec, ...] = ARCHIVES,
) -> dict[str, object]:
    """Download into mutable staging, then atomically publish an immutable snapshot."""
    staging = destination.with_name(destination.name + ".incomplete")
    if destination.exists():
        raise FileExistsError(f"snapshot already exists: {destination}")
    if staging.exists() and not resume:
        raise FileExistsError(f"incomplete snapshot exists; use --resume: {staging}")
    staging.mkdir(parents=True, exist_ok=resume)
    state: dict[str, object] = {
        "status": "downloading",
        "pipeline_version": VERSION,
        "code_sha256": _code_hash(),
        "source_page": SOURCE_PAGE,
        "corpus_date": CORPUS_DATE,
        "source_checksum_published": False,
        "checksum_note": (
            "The source page publishes archive names and approximate sizes but no hashes; "
            "SHA-256 values below were computed after transport."
        ),
        "expected_trials": EXPECTED_TRIALS,
        "archives": [],
        "issues": [],
    }
    _atomic_json(staging / "manifest.json", state)
    try:
        completed = []
        for spec in archives:
            completed.append(_download_one(staging, spec, client))
            state["archives"] = completed
            _atomic_json(staging / "manifest.json", state)
        state["status"] = "complete"
        state["completed_at_utc"] = _utc_now()
        _atomic_json(staging / "manifest.json", state)
        staging.replace(destination)
    except Exception as exc:
        state["status"] = "failed"
        state["issues"] = [{"reason": type(exc).__name__, "message": str(exc)}]
        _atomic_json(staging / "manifest.json", state)
        raise
    return state


def verify_archive_snapshot(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("status") != "complete" or manifest.get("pipeline_version") != VERSION:
        raise ValueError("historical corpus snapshot is incomplete or unsupported")
    expected_names = {entry["name"] for entry in manifest.get("archives", [])}
    if len(expected_names) != len(manifest.get("archives", [])):
        raise ValueError("duplicate archive in historical corpus manifest")
    for entry in manifest["archives"]:
        path = (root / entry["name"]).resolve()
        if path.parent != root.resolve() or not path.is_file():
            raise ValueError("invalid archive path in historical corpus manifest")
        if path.stat().st_size != entry["bytes"] or _file_sha256(path) != entry["sha256"]:
            raise ValueError(f"historical archive checksum mismatch: {entry['name']}")
    return manifest


def _safe_member(info: zipfile.ZipInfo) -> bool:
    path = PurePosixPath(info.filename)
    return (
        not info.is_dir()
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in info.filename
        and path.suffix.lower() == ".xml"
        and not (info.flag_bits & 1)
        and 0 < info.file_size <= MAX_XML_BYTES
    )


def _field_state(root: ET.Element, path: str) -> str:
    elements = root.findall(path)
    if not elements:
        return "absent"
    return "present" if any((element.text or "").strip() for element in elements) else "empty"


def _qrel_ids(raw: bytes) -> set[str]:
    ids: set[str] = set()
    issues = []
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("qrels are not valid UTF-8") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        parts = line.split()
        if (
            len(parts) != 4
            or not parts[0].isdigit()
            or parts[1] != "0"
            or not NCT_ID.fullmatch(parts[2])
            or parts[3] not in {"0", "1", "2"}
        ):
            issues.append({"source": "qrels", "line": line_number, "reason": "invalid row"})
        else:
            ids.add(parts[2])
    if issues:
        raise ValueError(f"qrel validation failed with {len(issues)} issue(s)")
    return ids


def validate_corpus(
    snapshot: Path,
    output: Path,
    qrels_path: Path,
    *,
    expected_trials: int = EXPECTED_TRIALS,
) -> dict[str, object]:
    """Verify all archive bytes, CRCs, XML IDs, fields, uniqueness, and qrel coverage."""
    manifest = verify_archive_snapshot(snapshot)
    output.mkdir(parents=True, exist_ok=False)
    qrels_raw = qrels_path.read_bytes()
    judged_ids = _qrel_ids(qrels_raw)
    issues: list[dict[str, object]] = []
    field_counts = {field: Counter() for field in FIELD_PATHS}
    part_counts: dict[str, int] = {}
    trial_ids: set[str] = set()
    official_layout = {entry["name"] for entry in manifest["archives"]} == {
        archive.name for archive in ARCHIVES
    }
    contents_verified = False
    index_path = output / "trial-index.jsonl"
    with index_path.open("x", encoding="utf-8", newline="\n") as index:
        for archive in manifest["archives"]:
            archive_name = str(archive["name"])
            part_count = 0
            try:
                bundle = zipfile.ZipFile(snapshot / archive_name)
            except zipfile.BadZipFile:
                issues.append({"archive": archive_name, "reason": "invalid ZIP archive"})
                continue
            with bundle:
                for position, info in enumerate(bundle.infolist(), 1):
                    if info.is_dir():
                        continue
                    if official_layout and info.filename == CONTENTS_MEMBER:
                        try:
                            contents = bundle.read(info)
                        except (OSError, RuntimeError, zipfile.BadZipFile):
                            issues.append(
                                {
                                    "archive": archive_name,
                                    "member": info.filename,
                                    "reason": "metadata member CRC/read failure",
                                }
                            )
                            continue
                        if sha256(contents) != CONTENTS_SHA256:
                            issues.append(
                                {
                                    "archive": archive_name,
                                    "member": info.filename,
                                    "reason": "unexpected archive metadata content",
                                }
                            )
                        else:
                            contents_verified = True
                        continue
                    if not _safe_member(info):
                        issues.append(
                            {
                                "archive": archive_name,
                                "member": info.filename,
                                "position": position,
                                "reason": "unsafe or unsupported archive member",
                            }
                        )
                        continue
                    try:
                        raw = bundle.read(info)
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        issues.append(
                            {
                                "archive": archive_name,
                                "member": info.filename,
                                "reason": "member CRC/read failure",
                            }
                        )
                        continue
                    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                        issues.append(
                            {
                                "archive": archive_name,
                                "member": info.filename,
                                "reason": "DTD/entity forbidden",
                            }
                        )
                        continue
                    try:
                        trial = ET.fromstring(raw)
                    except ET.ParseError:
                        issues.append(
                            {
                                "archive": archive_name,
                                "member": info.filename,
                                "reason": "invalid XML",
                            }
                        )
                        continue
                    trial_id = (trial.findtext("id_info/nct_id") or "").strip()
                    filename_id = PurePosixPath(info.filename).stem
                    reason = None
                    if trial.tag != "clinical_study":
                        reason = "unexpected XML root"
                    elif not NCT_ID.fullmatch(trial_id):
                        reason = "missing or invalid NCT ID"
                    elif filename_id != trial_id:
                        reason = "filename/NCT ID mismatch"
                    elif trial_id in trial_ids:
                        reason = "duplicate NCT ID"
                    if reason:
                        issues.append(
                            {
                                "archive": archive_name,
                                "member": info.filename,
                                "reason": reason,
                            }
                        )
                        continue
                    trial_ids.add(trial_id)
                    part_count += 1
                    for field, path in FIELD_PATHS.items():
                        field_counts[field][_field_state(trial, path)] += 1
                    index.write(
                        json.dumps(
                            {
                                "trial_id": trial_id,
                                "archive": archive_name,
                                "member": info.filename,
                                "crc32": f"{info.CRC:08x}",
                                "uncompressed_bytes": info.file_size,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
            part_counts[archive_name] = part_count
    if official_layout and not contents_verified:
        issues.append({"reason": "expected archive metadata file was not verified"})
    missing_judged = sorted(judged_ids - trial_ids)
    if len(trial_ids) != expected_trials:
        issues.append(
            {
                "reason": "trial count mismatch",
                "expected": expected_trials,
                "observed": len(trial_ids),
            }
        )
    if missing_judged:
        issues.append(
            {
                "reason": "judged trial IDs missing from corpus",
                "count": len(missing_judged),
            }
        )
    report: dict[str, object] = {
        "status": "complete" if not issues else "failed",
        "pipeline_version": VERSION,
        "code_sha256": _code_hash(),
        "corpus_date": CORPUS_DATE,
        "trial_records": len(trial_ids),
        "unique_trial_ids": len(trial_ids),
        "expected_trial_records": expected_trials,
        "part_counts": part_counts,
        "archive_contents_metadata": {
            "member": CONTENTS_MEMBER if official_layout else None,
            "sha256": CONTENTS_SHA256 if official_layout else None,
            "verified": contents_verified if official_layout else None,
            "declared_trial_records": EXPECTED_TRIALS if official_layout else None,
        },
        "field_states": {field: dict(counts) for field, counts in field_counts.items()},
        "qrels": {
            "path": qrels_path.name,
            "sha256": sha256(qrels_raw),
            "unique_judged_trial_ids": len(judged_ids),
            "missing_from_corpus": len(missing_judged),
            "missing_trial_ids": missing_judged,
        },
        "issues": issues,
        "eligibility_assessments_performed": 0,
        "benchmark_metrics_permitted": not issues,
    }
    write_json(output / "corpus-profile.json", report)
    write_json(output / "validation-issues.json", issues)
    files = [
        {"path": path.name, "bytes": path.stat().st_size, "sha256": _file_sha256(path)}
        for path in sorted(output.iterdir())
    ]
    write_json(
        output / "manifest.json",
        {
            "status": report["status"],
            "pipeline_version": VERSION,
            "input_manifest_sha256": sha256((snapshot / "manifest.json").read_bytes()),
            "files": files,
        },
    )
    return report
