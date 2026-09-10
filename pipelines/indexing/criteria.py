"""Bounded dense/sparse criterion artifact with independent source and vector verification."""

import json
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from backend.app.repositories.criteria import DENSE, INDEXES, SPARSE
from backend.app.schemas.criteria import ParsedEligibility
from backend.app.services.retrieval.sparse import SparseBM25
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash, load_parses
from pipelines.criteria.parser import parse_eligibility, parser_hash
from pipelines.embeddings import MODELS, validate_vectors

VERSION = "criterion-vectors-v1"
TEMPLATE = "criterion-section-ancestors-verbatim-v1"


def criterion_lexical(records):
    lexical = SparseBM25([r["input_text"] for r in records])
    lexical.manifest = {**lexical.manifest, "representation": TEMPLATE}
    return lexical


def records_from_parses(parsed):
    records = []
    for document in parsed:
        if parse_eligibility(document.source) != document:
            raise ValueError("parsed evidence changed")
        by_id = {c.criterion_id: c for c in document.criteria}
        for criterion in document.criteria:
            ancestors, parent = [], criterion.parent_id
            while parent:
                ancestors.insert(0, by_id[parent].evidence.text)
                parent = by_id[parent].parent_id
            text = "\n".join([f"Section: {criterion.section}", *ancestors, criterion.evidence.text])
            records.append(
                {
                    "criterion_id": criterion.criterion_id,
                    "trial_id": document.source.trial_id,
                    "section": criterion.section,
                    "ordinal": criterion.ordinal,
                    "parser_sha256": document.parser_sha256,
                    "criterion": criterion.model_dump(mode="json"),
                    "ancestor_texts": ancestors,
                    "input_text": text,
                    "source": document.source.model_dump(exclude={"text"}),
                    "text_sha256": document.text_sha256,
                    "eligibility_assessment": "not_performed",
                }
            )
    if not 1 <= len(records) <= 512:
        raise ValueError(
            "criterion diagnostic requires 1..512 criteria; choose a smaller trial sample"
        )
    if len({r["criterion_id"] for r in records}) != len(records):
        raise ValueError("duplicate criterion identity")
    return records


def build_artifact(source: Path, output: Path, encoder):
    _, parsed = load_parses(source)
    if encoder.metadata["model"] != asdict(MODELS["minilm"]):
        raise ValueError("pinned MiniLM required")
    records = records_from_parses(parsed)
    vectors, audits = [], []
    for start in range(0, len(records), 16):
        batch = records[start : start + 16]
        encoded = encoder.encode([r["input_text"] for r in batch])
        vectors.extend(encoded.vectors)
        for row, count in zip(batch, encoded.token_counts, strict=True):
            audits.append(
                {
                    "criterion_id": row["criterion_id"],
                    "tokens": count,
                    "truncated": count > encoder.spec.max_tokens,
                }
            )
    vectors = np.asarray(vectors, dtype=np.float32)
    validate_vectors(vectors, len(records), encoder.spec.dimension)
    lexical = criterion_lexical(records)
    write_json(output / "parsed.json", [p.model_dump(mode="json") for p in parsed])
    write_json(output / "records.json", records)
    write_json(output / "encoding-audit.json", audits)
    np.save(output / "vectors.npy", vectors, allow_pickle=False)
    result = {
        "status": "complete",
        "version": VERSION,
        "template": TEMPLATE,
        "parser_sha256": parser_hash(),
        "encoder": encoder.metadata,
        "source_manifest_sha256": file_hash(source / "manifest.json"),
        "documents": len(records),
        "trials": len(parsed),
        "dimension": encoder.spec.dimension,
        "lexical": lexical.manifest,
        "truncations": sum(a["truncated"] for a in audits),
        "files": {
            name: file_hash(output / name)
            for name in ("parsed.json", "records.json", "encoding-audit.json", "vectors.npy")
        },
    }
    write_json(output / "manifest.json", result)
    return result


def load_artifact(root: Path):
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != VERSION
        or manifest.get("template") != TEMPLATE
        or manifest.get("parser_sha256") != parser_hash()
    ):
        raise ValueError("incomplete/incompatible criterion artifact")
    names = ("parsed.json", "records.json", "encoding-audit.json", "vectors.npy")
    if manifest.get("files") != {name: file_hash(root / name) for name in names}:
        raise ValueError("criterion artifact checksum mismatch")
    encoder = manifest["encoder"]
    if (
        encoder["model"] != asdict(MODELS["minilm"])
        or encoder["normalization"] != "l2"
        or encoder["dtype"] != "float32"
        or encoder["prompt"] != ""
    ):
        raise ValueError("criterion model contract mismatch")
    parsed = [
        ParsedEligibility.model_validate(p) for p in json.loads((root / "parsed.json").read_bytes())
    ]
    records = records_from_parses(parsed)
    if json.loads((root / "records.json").read_bytes()) != records:
        raise ValueError("criterion records differ from source evidence")
    if (
        manifest["documents"] != len(records)
        or manifest["trials"] != len(parsed)
        or manifest["dimension"] != MODELS["minilm"].dimension
    ):
        raise ValueError("criterion artifact counts/dimension mismatch")
    vectors = np.load(root / "vectors.npy", allow_pickle=False)
    validate_vectors(vectors, len(records), manifest["dimension"])
    lexical = criterion_lexical(records)
    if lexical.manifest != manifest["lexical"]:
        raise ValueError("criterion lexical model mismatch")
    audit = json.loads((root / "encoding-audit.json").read_bytes())
    if any(
        type(r["tokens"]) is not int
        or r["tokens"] < 0
        or type(r["truncated"]) is not bool
        or r["truncated"] != (r["tokens"] > MODELS["minilm"].max_tokens)
        for r in audit
    ):
        raise ValueError("criterion encoding audit values invalid")
    if [r["criterion_id"] for r in audit] != [r["criterion_id"] for r in records] or sum(
        r["truncated"] for r in audit
    ) != manifest["truncations"]:
        raise ValueError("criterion encoding audit mismatch")
    contract = {
        "version": VERSION,
        "artifact_sha256": file_hash(root / "manifest.json"),
        "documents": len(records),
        "dimension": manifest["dimension"],
        "parser_sha256": parser_hash(),
        "encoder": encoder,
        "template": TEMPLATE,
        "lexical": lexical.manifest,
    }
    points = [
        {
            "id": str(uuid5(NAMESPACE_URL, "criterion:" + r["criterion_id"])),
            "vector": {DENSE: v.tolist(), SPARSE: s},
            "payload": {**r, "artifact_sha256": contract["artifact_sha256"]},
        }
        for r, v, s in zip(records, vectors, lexical.document_vectors, strict=True)
    ]
    return contract, records, vectors, lexical, points


def verify_collection(repo, contract, points):
    repo.version()
    repo.check_contract(contract)
    if repo.count() != len(points):
        raise ValueError("criterion count mismatch")
    for start in range(0, len(points), 64):
        expected = {p["id"]: p for p in points[start : start + 64]}
        actual = repo.retrieve(list(expected))
        if len(actual) != len(expected) or {p["id"] for p in actual} != set(expected):
            raise ValueError("criterion IDs missing or duplicated")
        for point in actual:
            reference = expected[point["id"]]
            if point["payload"] != reference["payload"]:
                raise ValueError("criterion payload/evidence mismatch")
            for name in (DENSE, SPARSE):
                got, wanted = point["vector"].get(name), reference["vector"][name]
                if got is None:
                    raise ValueError("criterion vector missing")
                if name == SPARSE:
                    if got["indices"] != wanted["indices"]:
                        raise ValueError("criterion sparse dimensions mismatch")
                    got, wanted = got["values"], wanted["values"]
                if np.shape(got) != np.shape(wanted) or not np.allclose(
                    got, wanted, atol=1e-6, rtol=0
                ):
                    raise ValueError("criterion vector values mismatch")
    schema = repo.info().get("payload_schema", {})
    if any(schema.get(k, {}).get("data_type") != v for k, v in INDEXES.items()):
        raise ValueError("criterion payload indexes missing")
    return {
        "status": "verified",
        "collection": repo.collection,
        "criteria": len(points),
        "vector_types": [DENSE, SPARSE],
        "payload_indexes": len(INDEXES),
        "eligibility_assessment": "not_performed",
    }
