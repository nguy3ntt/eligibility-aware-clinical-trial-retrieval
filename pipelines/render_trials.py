"""Render validated historical trial XML into versioned retrieval documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from pipelines.connectors.snapshots import sha256, write_json
from pipelines.connectors.trec import NCT_ID
from pipelines.connectors.trec_corpus import CONTENTS_MEMBER, verify_archive_snapshot
from pipelines.connectors.trec_corpus import VERSION as CORPUS_VERSION

VERSION = "trial-renderer-v1"
REPRESENTATIONS = {
    "title_conditions": (
        "brief_title",
        "official_title",
        "conditions",
    ),
    "summary": (
        "brief_title",
        "official_title",
        "conditions",
        "brief_summary",
        "detailed_description",
        "interventions",
    ),
    "eligibility": (
        "brief_title",
        "official_title",
        "conditions",
        "brief_summary",
        "detailed_description",
        "interventions",
        "eligibility_text",
    ),
}
FIELD_PATHS = {
    "brief_title": "brief_title",
    "official_title": "official_title",
    "conditions": "condition",
    "brief_summary": "brief_summary/textblock",
    "detailed_description": "detailed_description/textblock",
    "interventions": "intervention/intervention_name",
    "eligibility_text": "eligibility/criteria/textblock",
}


def _text(element: ET.Element, path: str) -> str:
    return " ".join(
        " ".join((item.text or "").split())
        for item in element.findall(path)
        if (item.text or "").strip()
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_trial(element: ET.Element, source: dict[str, object]) -> dict[str, object]:
    trial_id = (element.findtext("id_info/nct_id") or "").strip()
    if element.tag != "clinical_study" or not NCT_ID.fullmatch(trial_id):
        raise ValueError("renderer received an invalid historical trial")
    fields = {name: _text(element, path) for name, path in FIELD_PATHS.items()}
    representations = {
        name: "\n".join(fields[field] for field in selected if fields[field])
        for name, selected in REPRESENTATIONS.items()
    }
    row: dict[str, object] = {
        "trial_id": trial_id,
        "renderer_version": VERSION,
        "representations": representations,
        "filter_metadata": {
            "sex": _text(element, "eligibility/gender") or None,
            "minimum_age": _text(element, "eligibility/minimum_age") or None,
            "maximum_age": _text(element, "eligibility/maximum_age") or None,
        },
        "source": source,
    }
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row["content_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return row


def render_corpus(snapshot: Path, validation: Path, output: Path) -> dict[str, object]:
    source_manifest = verify_archive_snapshot(snapshot)
    validation_manifest = json.loads((validation / "manifest.json").read_bytes())
    profile = json.loads((validation / "corpus-profile.json").read_bytes())
    if (
        source_manifest.get("pipeline_version") != CORPUS_VERSION
        or validation_manifest.get("status") != "complete"
        or profile.get("status") != "complete"
        or not profile.get("benchmark_metrics_permitted")
    ):
        raise ValueError("historical corpus validation gate has not passed")
    if validation_manifest.get("input_manifest_sha256") != sha256(
        (snapshot / "manifest.json").read_bytes()
    ):
        raise ValueError("validation output does not match the corpus snapshot")
    output.mkdir(parents=True, exist_ok=False)
    count = 0
    documents = output / "documents.jsonl"
    with documents.open("x", encoding="utf-8", newline="\n") as handle:
        for archive in source_manifest["archives"]:
            archive_name = str(archive["name"])
            with zipfile.ZipFile(snapshot / archive_name) as bundle:
                for info in bundle.infolist():
                    if info.is_dir() or info.filename == CONTENTS_MEMBER:
                        continue
                    if PurePosixPath(info.filename).suffix.lower() != ".xml":
                        raise ValueError("unexpected non-XML archive member reached renderer")
                    element = ET.fromstring(bundle.read(info))
                    row = render_trial(
                        element,
                        {
                            "archive": archive_name,
                            "archive_sha256": archive["sha256"],
                            "member": info.filename,
                            "crc32": f"{info.CRC:08x}",
                        },
                    )
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    count += 1
    if count != profile["trial_records"]:
        raise ValueError("rendered trial count differs from the validated corpus")
    manifest = {
        "status": "complete",
        "renderer_version": VERSION,
        "representations": {name: list(fields) for name, fields in REPRESENTATIONS.items()},
        "documents": count,
        "source_manifest_sha256": sha256((snapshot / "manifest.json").read_bytes()),
        "validation_manifest_sha256": sha256((validation / "manifest.json").read_bytes()),
        "files": [
            {
                "path": documents.name,
                "bytes": documents.stat().st_size,
                "sha256": _file_sha256(documents),
            }
        ],
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def _safe_id(parser: argparse.ArgumentParser, value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        parser.error("IDs must contain only letters, digits, hyphens, or underscores")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--validation-id", required=True)
    parser.add_argument("--output-id", required=True)
    args = parser.parse_args()
    run_id = _safe_id(parser, args.run_id)
    validation_id = _safe_id(parser, args.validation_id)
    output_id = _safe_id(parser, args.output_id)
    result = render_corpus(
        Path("data/raw") / run_id,
        Path("data/interim") / validation_id,
        Path("data/processed") / output_id,
    )
    print(json.dumps({"status": result["status"], "documents": result["documents"]}))


if __name__ == "__main__":
    main()
