"""Immutable bounded eligibility artifacts, rebuilt from original historical XML."""

import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from backend.app.schemas.criteria import EligibilitySource, ParsedEligibility
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.parser import parse_eligibility, parser_hash

VERSION = "criteria-source-artifact-v1"


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def implementation_fingerprints() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    names = (
        "backend/app/schemas/criteria.py",
        "backend/app/schemas/patient.py",
        "backend/app/repositories/criteria.py",
        "backend/app/repositories/qdrant.py",
        "backend/app/services/retrieval/sparse.py",
        "pipelines/embeddings.py",
        "pipelines/criteria/parser.py",
        "pipelines/criteria/artifacts.py",
        "pipelines/criteria_parse.py",
        "pipelines/criteria_index.py",
        "pipelines/indexing/criteria.py",
        "evaluation/criteria.py",
        "evaluation/criteria_index.py",
    )
    return {name: file_hash(root / name) for name in names}


def local_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("local ID must contain 1..80 letters, digits, hyphens or underscores")
    return value


def fixture_sources(path: Path) -> tuple[list[EligibilitySource], list[dict]]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("fixture exceeds 1 MiB")
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != "eligibility-fixtures-v1" or data.get("invented") is not True:
        raise ValueError("only explicitly invented trial fixtures are accepted")
    if not 1 <= len(data["trials"]) <= 32:
        raise ValueError("fixture requires 1..32 trials")
    result, seen = [], set()
    for i, row in enumerate(data["trials"]):
        source = EligibilitySource(
            trial_id=row["trial_id"],
            text=row["text"],
            source_kind="invented_trial_fixture",
            source_sha256=hashlib.sha256(raw).hexdigest(),
            source_locator=f"/trials/{i}/text",
            provenance={"dataset_id": data["dataset_id"]},
        )
        if source.trial_id in seen:
            raise ValueError(f"duplicate fixture trial at position {i}")
        seen.add(source.trial_id)
        result.append(source)
    return result, data["trials"]


def historical_sources(index: Path, snapshot: Path, limit: int) -> list[EligibilitySource]:
    # Lazy dependency: standalone parsing/evaluation does not require ML packages.
    from pipelines.indexing.qdrant import artifact_contract

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16:
        raise ValueError("historical parsing sample requires 1..16 trials")
    _, rows, _ = artifact_contract(index)
    selected = sorted(rows, key=lambda r: r["trial_id"])[:limit]
    manifest = json.loads((snapshot / "manifest.json").read_bytes())
    if manifest.get("status") != "complete":
        raise ValueError("incomplete historical snapshot")
    archives = {entry["name"]: entry for entry in manifest["archives"]}
    verified, result = set(), []
    for row in selected:
        provenance = row["source"]
        name = provenance["archive"]
        path = (snapshot / name).resolve()
        entry = archives[name]
        if path.parent != snapshot.resolve() or entry["sha256"] != provenance["archive_sha256"]:
            raise ValueError("archive provenance mismatch or unsafe archive path")
        if name not in verified:
            if path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
                raise ValueError("raw archive checksum mismatch")
            verified.add(name)
        member = provenance["member"]
        if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts:
            raise ValueError("unsafe archive member")
        with zipfile.ZipFile(path) as bundle:
            info = bundle.getinfo(member)
            if info.file_size > 2 * 1024 * 1024 or f"{info.CRC:08x}" != provenance["crc32"]:
                raise ValueError("XML member size/CRC mismatch")
            raw = bundle.read(info)
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("XML entities forbidden")
        element = ET.fromstring(raw)
        if element.tag != "clinical_study" or element.findtext("id_info/nct_id") != row["trial_id"]:
            raise ValueError("XML trial identity mismatch")
        fields = element.findall("eligibility/criteria/textblock")
        if len(fields) > 1 or any(len(f) for f in fields):
            raise ValueError("ambiguous eligibility field structure")
        text = fields[0].text or "" if fields else ""
        result.append(
            EligibilitySource(
                trial_id=row["trial_id"],
                text=text,
                source_kind="public_historical_xml",
                source_sha256=hashlib.sha256(raw).hexdigest(),
                source_locator="/clinical_study/eligibility/criteria/textblock",
                provenance={
                    **provenance,
                    "snapshot_manifest_sha256": file_hash(snapshot / "manifest.json"),
                    "selection_artifact_sha256": file_hash(index / "manifest.json"),
                    "field_present": str(bool(fields)).lower(),
                },
            )
        )
    return result


def save_parses(output: Path, sources: list[EligibilitySource]) -> dict:
    if not sources or len({s.trial_id for s in sources}) != len(sources):
        raise ValueError("parse artifact requires unique source trials")
    parsed = [parse_eligibility(s) for s in sources]
    write_json(output / "parsed.json", [p.model_dump(mode="json") for p in parsed])
    result = {
        "status": "complete",
        "version": VERSION,
        "parser_sha256": parser_hash(),
        "trials": len(parsed),
        "criteria": sum(len(p.criteria) for p in parsed),
        "files": {"parsed.json": file_hash(output / "parsed.json")},
        "selection": "ordered NCT IDs from bounded dense diagnostic; not a held-out sample",
        "eligibility_assessments_performed": 0,
    }
    write_json(output / "manifest.json", result)
    return result


def load_parses(root: Path) -> tuple[dict, list[ParsedEligibility]]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != VERSION
        or manifest.get("parser_sha256") != parser_hash()
    ):
        raise ValueError("incomplete or incompatible parser artifact")
    if manifest.get("files") != {"parsed.json": file_hash(root / "parsed.json")}:
        raise ValueError("parsed artifact checksum mismatch")
    parsed = [
        ParsedEligibility.model_validate(p) for p in json.loads((root / "parsed.json").read_bytes())
    ]
    if (
        len(parsed) != manifest["trials"]
        or len({p.source.trial_id for p in parsed}) != len(parsed)
        or sum(len(p.criteria) for p in parsed) != manifest["criteria"]
    ):
        raise ValueError("parsed artifact counts/IDs mismatch")
    if any(parse_eligibility(p.source) != p for p in parsed):
        raise ValueError("stored parse differs from deterministic source parsing")
    return manifest, parsed
