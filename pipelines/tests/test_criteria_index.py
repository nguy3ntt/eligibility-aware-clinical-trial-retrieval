"""Bounded criterion artifacts, independent scoring, corruption and live storage checks."""

# Optional ML dependencies must be checked before importing the index implementation.
# ruff: noqa: E402

import copy
import json
import os
import zipfile
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("bm25s")

from backend.app.repositories.criteria import DENSE, INDEXES, SPARSE, CriteriaRepository
from evaluation.criteria_index import check_scores
from pipelines.criteria.artifacts import file_hash, save_parses
from pipelines.embeddings import MODELS
from pipelines.indexing.criteria import (
    build_artifact,
    load_artifact,
    records_from_parses,
    verify_collection,
)
from pipelines.tests.test_criteria import source


@pytest.mark.parametrize(
    "damage", [None, "archive_hash", "crc", "identity", "entities", "ambiguous", "missing"]
)
def test_historical_original_field_and_source_guards(tmp_path, monkeypatch, damage):
    from pipelines.criteria.artifacts import historical_sources
    from pipelines.indexing import qdrant

    text = "Inclusion Criteria:&#13;\n- Age >= 18 years."
    fields = f"<textblock>{text}</textblock>"
    if damage == "ambiguous":
        fields += "<textblock>Other</textblock>"
    elif damage == "missing":
        fields = ""
    identity = "NCT00000002" if damage == "identity" else "NCT00000001"
    xml = (
        f"<clinical_study><id_info><nct_id>{identity}</nct_id></id_info>"
        f"<eligibility><criteria>{fields}</criteria></eligibility></clinical_study>"
    )
    if damage == "entities":
        xml = '<!DOCTYPE clinical_study [<!ENTITY x "test">]>' + xml
    archive = tmp_path / "part1.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("trials/NCT00000001.xml", xml)
        crc = bundle.getinfo("trials/NCT00000001.xml").CRC
    digest = file_hash(archive)
    row = {
        "trial_id": "NCT00000001",
        "source": {
            "archive": archive.name,
            "archive_sha256": digest,
            "member": "trials/NCT00000001.xml",
            "crc32": f"{crc:08x}",
        },
    }
    manifest = {
        "status": "complete",
        "archives": [
            {
                "name": archive.name,
                "sha256": digest,
                "bytes": archive.stat().st_size,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    if damage == "archive_hash":
        archive.write_bytes(archive.read_bytes() + b"changed")
    elif damage == "crc":
        row["source"]["crc32"] = "00000000"
    monkeypatch.setattr(qdrant, "artifact_contract", lambda _: ({}, [row], []))
    if damage not in {None, "missing"}:
        with pytest.raises(ValueError):
            historical_sources(tmp_path, tmp_path, 1)
    else:
        [result] = historical_sources(tmp_path, tmp_path, 1)
        assert result.text == (
            "" if damage == "missing" else "Inclusion Criteria:\r\n- Age >= 18 years."
        )
        assert result.provenance["field_present"] == str(damage != "missing").lower()


class FixtureEncoder:
    spec = MODELS["minilm"]
    metadata = {
        "model": asdict(spec),
        "snapshot_sha256": "a" * 64,
        "normalization": "l2",
        "dtype": "float32",
        "prompt": "",
    }

    def encode(self, texts):
        vectors = np.zeros((len(texts), self.spec.dimension), dtype=np.float32)
        vectors[:, 0] = 1
        return SimpleNamespace(vectors=vectors, token_counts=[8] * len(texts))


@pytest.fixture
def artifact(tmp_path):
    sources, output = tmp_path / "sources", tmp_path / "index"
    sources.mkdir()
    output.mkdir()
    save_parses(
        sources,
        [
            source(
                "Inclusion Criteria:\n- Age >= 18 years.\n- Consent.\n"
                "Exclusion Criteria:\n- No chemotherapy."
            )
        ],
    )
    build_artifact(sources, output, FixtureEncoder())
    return output


def test_artifact_stable_identity_many_criteria_per_trial_and_real_representation(artifact):
    contract, records, _, _, points = load_artifact(artifact)
    assert len(points) == len({p["id"] for p in points}) == 3
    assert len({r["trial_id"] for r in records}) == 1
    assert contract["lexical"]["representation"] == contract["template"]
    assert load_artifact(artifact)[-1] == points
    from pipelines.criteria.parser import parse_eligibility

    with pytest.raises(ValueError, match="1..512"):
        records_from_parses(
            [parse_eligibility(source("\n".join(f"- Consent {i}" for i in range(513))))]
        )


@pytest.mark.parametrize("damage", ["evidence", "audit", "model", "lexical", "nan", "shape"])
def test_artifact_rejects_corruption_even_with_updated_file_checksum(artifact, damage):
    manifest_path = artifact / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if damage == "evidence":
        rows = json.loads((artifact / "records.json").read_bytes())
        rows[0]["criterion"]["evidence"]["text"] = "Changed"
        (artifact / "records.json").write_text(json.dumps(rows))
    elif damage == "audit":
        rows = json.loads((artifact / "encoding-audit.json").read_bytes())
        rows[0]["tokens"] = -1
        (artifact / "encoding-audit.json").write_text(json.dumps(rows))
    elif damage == "model":
        manifest["encoder"]["model"]["revision"] = "different"
    elif damage == "lexical":
        manifest["lexical"]["representation"] = "title_conditions"
    else:
        values = np.load(artifact / "vectors.npy")
        if damage == "nan":
            values[0, 0] = np.nan
        else:
            values = values[:, :1]
        np.save(artifact / "vectors.npy", values, allow_pickle=False)
    manifest["files"] = {name: file_hash(artifact / name) for name in manifest["files"]}
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_artifact(artifact)


@pytest.mark.parametrize(
    "damage", ["payload", "dense", "sparse", "broadcast", "missing", "duplicate"]
)
def test_stored_criterion_corruption_is_detected(artifact, damage):
    contract, _, _, _, points = load_artifact(artifact)
    actual = copy.deepcopy(points)
    if damage == "payload":
        actual[0]["payload"]["criterion"]["section"] = "exclusion"
    elif damage == "dense":
        actual[0]["vector"][DENSE][0] = 0.9
    elif damage == "sparse":
        actual[0]["vector"][SPARSE]["values"][0] += 0.1
    elif damage == "broadcast":
        actual[0]["vector"][DENSE] = [[v] for v in actual[0]["vector"][DENSE]]
    elif damage == "missing":
        actual.pop()
    else:
        actual.append(actual[0])

    class Repo:
        collection = "test"

        def version(self):
            return "1.19.0"

        def check_contract(self, contract):
            pass

        def count(self):
            return len(points)

        def retrieve(self, ids):
            return actual

        def info(self):
            return {"payload_schema": {k: {"data_type": v} for k, v in INDEXES.items()}}

    with pytest.raises(ValueError):
        verify_collection(Repo(), contract, points)


@pytest.mark.parametrize("damage", ["contract", "idf", "dimension", "missing_sparse"])
def test_incompatible_collection_refused_before_writes(artifact, damage):
    contract = load_artifact(artifact)[0]
    config = {
        "metadata": {"retrieval_contract": copy.deepcopy(contract)},
        "params": {
            "vectors": {DENSE: {"size": 384, "distance": "Cosine"}},
            "sparse_vectors": {SPARSE: {"index": {"on_disk": False}}},
        },
    }
    if damage == "contract":
        config["metadata"]["retrieval_contract"]["parser_sha256"] = "changed"
    elif damage == "idf":
        config["params"]["sparse_vectors"][SPARSE]["modifier"] = "idf"
    elif damage == "dimension":
        config["params"]["vectors"][DENSE]["size"] = 3
    else:
        config["params"]["sparse_vectors"] = {}
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.url.path == "/":
            return httpx.Response(200, json={"version": "1.19.0"})
        return httpx.Response(200, json={"result": {"config": config}})

    with (
        CriteriaRepository(transport=httpx.MockTransport(handler)) as repo,
        pytest.raises(ValueError),
    ):
        repo.ensure_criteria(contract)
    assert set(methods) == {"GET"}


def test_scoring_oracle_rejects_bad_ranks_scores_and_duplicate_ids():
    good = [
        {"score": 2.0, "payload": {"criterion_id": "a"}},
        {"score": 1.0, "payload": {"criterion_id": "b"}},
    ]
    assert check_scores(good, ["a", "b"], [2, 1]) == 0
    for wrong in (good[:1], good[::-1], [good[0], good[0]], [{**good[0], "score": 9}, good[1]]):
        with pytest.raises(ValueError):
            check_scores(wrong, ["a", "b"], [2, 1])


def test_live_criterion_resume_idempotency_ties_empty_query_and_corruption(artifact):
    url = os.environ.get("QDRANT_TEST_URL")
    if not url:
        pytest.skip("set QDRANT_TEST_URL for isolated criterion storage integration")
    contract, _, vectors, lexical, points = load_artifact(artifact)
    with CriteriaRepository(url, "test_criteria_" + uuid4().hex[:12]) as repo:
        try:
            repo.ensure_criteria(contract)
            repo.upsert(points[:1])
            with pytest.raises(ValueError, match="count"):
                verify_collection(repo, contract, points)
            repo.upsert(points)
            repo.upsert(points)
            assert verify_collection(repo, contract, points)["criteria"] == 3
            hits = repo.query_criteria(vectors[0].tolist(), contract)
            assert [h["payload"]["criterion_id"] for h in hits] == sorted(
                p["payload"]["criterion_id"] for p in points
            )
            assert (
                repo.query_criteria(lexical.query("zzzzunseenxxxx")[0], contract, sparse=True) == []
            )
            with pytest.raises(ValueError, match="sparse query"):
                repo.query_criteria({"indices": [0, 0], "values": [1, 1]}, contract, sparse=True)
            changed = copy.deepcopy(points[0])
            changed["payload"]["criterion"]["section"] = "exclusion"
            repo.upsert([changed])
            with pytest.raises(ValueError, match="payload"):
                verify_collection(repo, contract, points)
            repo.upsert(points)
            assert verify_collection(repo, contract, points)["criteria"] == 3
        finally:
            repo.request("DELETE", repo.path)  # Only this test's unique disposable collection.


def test_bm25_sum_tolerance_scales_with_score_but_rejects_material_changes():
    hit = {"score": 100.00003, "payload": {"criterion_id": "a"}}
    with pytest.raises(ValueError):
        check_scores([hit], ["a"], [100], tolerance=1e-5)
    assert check_scores([hit], ["a"], [100], tolerance=1e-5, relative=1e-6) < 1e-4
    hit["score"] = 100.01
    with pytest.raises(ValueError):
        check_scores([hit], ["a"], [100], tolerance=1e-5, relative=1e-6)
