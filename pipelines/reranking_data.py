"""Bounded field evidence reconstructed from verified immutable trial XML."""

import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from backend.app.schemas.criteria import EligibilitySource
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash
from pipelines.render_trials import FIELD_PATHS, REPRESENTATIONS, render_trial

VERSION = "reranking-field-evidence-v1"


def from_xml(raw: bytes, row: dict, *, invented: bool = False) -> dict:
    if len(raw) > 2 * 1024**2 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsafe trial XML")
    element = ET.fromstring(raw)
    if render_trial(element, row["source"]) != row:
        raise ValueError("original XML does not reproduce saved retrieval row")
    fields = {}
    for name, path in FIELD_PATHS.items():
        items = element.findall(path)
        if any(len(item) for item in items):
            raise ValueError("nested trial field requires explicit handling")
        texts = [item.text or "" for item in items]
        fields[name] = {
            "locator": "/clinical_study/" + path,
            "original_texts": texts,
            "normalized": " ".join(" ".join(t.split()) for t in texts if t.strip()),
        }
    criteria = fields["eligibility_text"]["original_texts"]
    if len(criteria) > 1:
        raise ValueError("ambiguous eligibility field")
    record = {
        "trial_id": row["trial_id"],
        "row": row,
        "fields": fields,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_kind": "invented_trial_fixture" if invented else "public_historical_xml",
    }
    validate_record(record)
    return record


def validate_record(record: dict) -> None:
    from pipelines.dense_artifacts import validate_document

    row = record["row"]
    validate_document(row, 0)
    if record["trial_id"] != row["trial_id"] or set(record["fields"]) != set(FIELD_PATHS):
        raise ValueError("field evidence identity mismatch")
    for name, field in record["fields"].items():
        if (
            field["locator"] != "/clinical_study/" + FIELD_PATHS[name]
            or not all(isinstance(t, str) for t in field["original_texts"])
            or field["normalized"]
            != " ".join(" ".join(t.split()) for t in field["original_texts"] if t.strip())
        ):
            raise ValueError("field evidence normalization mismatch")
    for name, selected in REPRESENTATIONS.items():
        text = "\n".join(
            record["fields"][f]["normalized"] for f in selected if record["fields"][f]["normalized"]
        )
        if text != row["representations"][name]:
            raise ValueError("field evidence does not reproduce representation")
    eligibility_source(record)


def eligibility_source(record: dict) -> EligibilitySource:
    texts = record["fields"]["eligibility_text"]["original_texts"]
    if len(texts) > 1:
        raise ValueError("ambiguous eligibility text")
    return EligibilitySource(
        trial_id=record["trial_id"],
        text=texts[0] if texts else "",
        source_kind=record["source_kind"],
        source_sha256=record["source_sha256"],
        source_locator=record["fields"]["eligibility_text"]["locator"],
        provenance=record["row"]["source"],
    )


def prepare(index: Path, snapshot: Path, output: Path) -> dict:
    from pipelines.indexing.qdrant import artifact_contract

    contract, rows, _ = artifact_contract(index)
    manifest = json.loads((snapshot / "manifest.json").read_bytes())
    if manifest.get("status") != "complete":
        raise ValueError("completed historical snapshot required")
    archives = {a["name"]: a for a in manifest["archives"]}
    verified, records = set(), []
    for row in rows:
        source = row["source"]
        path = (snapshot / source["archive"]).resolve()
        entry = archives[source["archive"]]
        if path.parent != snapshot.resolve() or entry["sha256"] != source["archive_sha256"]:
            raise ValueError("unsafe or mismatched archive")
        if path.name not in verified:
            if path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
                raise ValueError("archive checksum mismatch")
            verified.add(path.name)
        member = PurePosixPath(source["member"])
        if member.is_absolute() or ".." in member.parts:
            raise ValueError("unsafe archive member")
        with zipfile.ZipFile(path) as bundle:
            info = bundle.getinfo(str(member))
            if info.file_size > 2 * 1024**2 or f"{info.CRC:08x}" != source["crc32"]:
                raise ValueError("trial member CRC/size mismatch")
            records.append(from_xml(bundle.read(info), row))
    write_json(output / "evidence.json", records)
    result = {
        "status": "complete",
        "version": VERSION,
        "trials": len(records),
        "artifact_sha256": contract["artifact_sha256"],
        "snapshot_manifest_sha256": file_hash(snapshot / "manifest.json"),
        "files": {"evidence.json": file_hash(output / "evidence.json")},
    }
    write_json(output / "manifest.json", result)
    return result


def load_evidence(root: Path, rows: list[dict], artifact_sha256: str) -> dict[str, dict]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != VERSION
        or manifest.get("artifact_sha256") != artifact_sha256
        or manifest.get("files") != {"evidence.json": file_hash(root / "evidence.json")}
    ):
        raise ValueError("incompatible or corrupted field-evidence artifact")
    records = json.loads((root / "evidence.json").read_bytes())
    if len(records) != len(rows) or manifest["trials"] != len(rows):
        raise ValueError("field-evidence count mismatch")
    for record, row in zip(records, rows, strict=True):
        validate_record(record)
        if record["row"] != row:
            raise ValueError("field evidence is not aligned with retrieval artifact")
    return {r["trial_id"]: r for r in records}
