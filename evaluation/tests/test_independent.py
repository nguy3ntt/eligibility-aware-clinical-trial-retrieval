"""Invented fixtures exercise gates; none are research accuracy measurements."""

import json
from pathlib import Path

import pytest

pytest.importorskip("bm25s")

from evaluation import independent as study
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import SourceValidationError, load_qrels
from pipelines.embeddings import file_hash, file_record


def xml(body='<topic number="1">Invented synthetic example.</topic>'):
    return f'<topics task="2021 TREC Clinical Trials">{body}</topics>'.encode()


def test_2021_namespace_retains_text_without_accepting_other_tasks():
    rows = study.load_2021_topics(xml('<topic number="1">  Synthetic text.\n</topic>'))
    assert rows[0]["topic_id"] == "1"
    assert rows[0]["text"] == "  Synthetic text.\n"
    with pytest.raises(ValueError, match="task"):
        study.load_2021_topics(xml().replace(b"2021", b"2022"))


@pytest.mark.parametrize(
    "raw",
    [
        b"<broken",
        xml(""),
        xml('<topic number="0">text</topic>'),
        xml('<topic number="1"><nested>text</nested></topic>'),
        xml('<topic number="1">text</topic><topic number="1">other</topic>'),
        xml('<topic number="1">same text</topic><topic number="2">SAME TEXT.</topic>'),
        b'<!DOCTYPE topics [<!ENTITY x "danger">]>' + xml(),
        xml('<topic number="1" extra="x">text</topic>'),
    ],
)
def test_malformed_or_duplicate_sources_never_silently_drop_records(raw):
    with pytest.raises(ValueError):
        study.load_2021_topics(raw)


def test_development_overlap_uses_text_not_colliding_numeric_ids():
    old = [{"topic_id": "1", "text": "Completely invented synthetic topic description."}]
    near = [{"topic_id": "77", "text": "Completely invented synthetic topic description!"}]
    assert study.overlap_audit(near, old)["passed"] is False
    new = [{"topic_id": "1", "text": "Different words about a fictional case."}]
    audit = study.overlap_audit(new, old)
    assert audit["passed"] is True
    assert "fictional" not in json.dumps(audit)


@pytest.fixture
def rankings():
    return {
        name: {
            "1": [
                {"trial_id": "NCT00000001", "score": -2.0},
                {"trial_id": "NCT00000002", "score": 0.2},
            ]
        }
        for name in study.SYSTEMS
    }


@pytest.mark.parametrize(
    "mutation", ["missing_system", "missing_topic", "duplicate", "nonfinite", "foreign"]
)
def test_invalid_rankings_cannot_be_scored(rankings, mutation):
    hits = rankings["dense"]["1"]
    if mutation == "missing_system":
        del rankings["bm25"]
    elif mutation == "missing_topic":
        rankings["dense"] = {}
    elif mutation == "duplicate":
        hits.append(hits[0])
    elif mutation == "nonfinite":
        hits[0]["score"] = float("nan")
    else:
        hits[0]["trial_id"] = "NCT99999999"
    with pytest.raises(ValueError):
        study.validate_rankings(rankings, {"1"}, {"NCT00000001", "NCT00000002"})


def test_metrics_preserve_sealed_order_and_negative_findings(rankings):
    # Learned logits can be negative; never sort mixed score scales during evaluation.
    judgments = load_qrels(b"1 0 NCT00000001 0\n1 0 NCT00000002 2\n", {"1"})
    rankings["bm25"]["1"].reverse()
    report = study.score_rankings(rankings, judgments, {"1"}, {"NCT00000001", "NCT00000002"})
    primary = report["comparisons"]["dense_vs_bm25"]
    assert report["metrics"]["bm25"]["ndcg_at_10"] == 1.0
    assert report["metrics"]["dense"]["ndcg_at_10"] == pytest.approx(0.6309297536)
    assert primary["mean_delta"] < 0
    assert primary["ci95"][1] < 0
    assert primary["role"] == "primary"
    assert "held_out" not in primary
    assert report["judged_fraction_at_10"]["dense"]["1"] == 0.2


def test_no_qrel_or_corpus_coverage_is_not_a_zero_score(rankings):
    for judgments in ([], [{"topic_id": "1", "trial_id": "NCT00000003", "grade": 2}]):
        with pytest.raises(ValueError, match="judgments"):
            study.score_rankings(rankings, judgments, {"1"}, {"NCT00000001", "NCT00000002"})
    with pytest.raises(SourceValidationError):
        load_qrels(b"1 0 NCT00000001 2\n1 0 NCT00000001 2\n", {"1"})


def test_labels_cannot_be_requested_before_the_ranking_seal(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "check_protocol", lambda _: {})
    with pytest.raises(FileNotFoundError):
        study.acquire(tmp_path, "qrels")
    assert not (tmp_path / "qrels").exists()


def test_acquisition_uses_official_url_and_write_once_snapshot(monkeypatch, tmp_path):
    protocol = {
        "paths": {"sources": str(tmp_path / "raw"), "development": "unused"},
        "sources": {"topics": study.TOPICS_URL},
    }
    monkeypatch.setattr(study, "check_protocol", lambda _: protocol)
    monkeypatch.setattr(study, "load_topics", lambda _: [{"topic_id": "1", "text": "Other case"}])
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"unused")
    (tmp_path / "protocol.json").write_text("{}")

    def capture(self, client, name, url):
        assert url == study.TOPICS_URL
        raw = xml()
        (self.root / name).write_bytes(raw)
        self.files.append({"path": name, "bytes": len(raw), "sha256": "unused", "url": url})
        return raw

    monkeypatch.setattr(study.Snapshot, "capture", capture)
    assert study.acquire(tmp_path, "topics")["records"] == 1
    with pytest.raises(FileExistsError):
        study.acquire(tmp_path, "topics")


def test_protocol_rejects_changed_implementation_runtime_and_bytes(monkeypatch, tmp_path):
    protocol = {
        "version": study.VERSION,
        "implementation": {"file": "hash"},
        "runtime": {"version": 1},
        "systems": list(study.SYSTEMS),
        "paths": {
            "index": str(tmp_path / "index"),
            "rendered": str(tmp_path / "rendered"),
            "development": str(tmp_path / "development"),
        },
    }
    for folder in ("index", "rendered"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "manifest.json").write_text("{}")
    (tmp_path / "development").write_text("synthetic")
    protocol.update(
        {
            "index_manifest_sha256": file_hash(tmp_path / "index/manifest.json"),
            "rendered_manifest_sha256": file_hash(tmp_path / "rendered/manifest.json"),
            "development_topics_sha256": file_hash(tmp_path / "development"),
        }
    )
    write_json(tmp_path / "protocol.json", protocol)
    (tmp_path / "protocol.sha256").write_text(file_hash(tmp_path / "protocol.json"))
    monkeypatch.setattr(study, "implementation", lambda: {"file": "hash"})
    monkeypatch.setattr(study, "runtime", lambda: {"version": 1})
    assert study.check_protocol(tmp_path) == protocol
    monkeypatch.setattr(study, "implementation", lambda: {"file": "changed"})
    with pytest.raises(ValueError, match="code/runtime"):
        study.check_protocol(tmp_path)
    monkeypatch.setattr(study, "implementation", lambda: {"file": "hash"})
    monkeypatch.setattr(study, "runtime", lambda: {"version": 2})
    with pytest.raises(ValueError, match="code/runtime"):
        study.check_protocol(tmp_path)
    monkeypatch.setattr(study, "runtime", lambda: {"version": 1})
    (tmp_path / "development").write_text("changed")
    with pytest.raises(ValueError, match="input identity"):
        study.check_protocol(tmp_path)


def test_sealed_rank_artifact_tampering_is_rejected(monkeypatch, tmp_path):
    ranked = tmp_path / "ranked"
    ranked.mkdir()
    names = ["rankings.json", "corpus-ids.json", "query-audit.json", "timings.json", "models.json"]
    names.extend(f"{name}.run" for name in study.SYSTEMS)
    for name in names:
        (ranked / name).write_text("{}")
    (tmp_path / "protocol.json").write_text("{}")
    raw = xml()
    monkeypatch.setattr(study, "source_bytes", lambda *_: raw)
    seal = {
        "protocol_sha256": file_hash(tmp_path / "protocol.json"),
        "topics_sha256": study.hashlib.sha256(raw).hexdigest(),
        "systems": list(study.SYSTEMS),
        "files": [file_record(ranked / name, ranked) for name in names],
    }
    write_json(tmp_path / "seal.json", seal)
    assert study.check_seal(tmp_path, {}) == seal
    (ranked / "dense.run").write_text("altered")
    with pytest.raises(ValueError, match="checksum"):
        study.check_seal(tmp_path, {})


def test_freeze_refuses_existing_destinations_before_touching_data(tmp_path):
    with pytest.raises(ValueError, match="fresh"):
        study.freeze(tmp_path, Path("unused"), Path("unused"), Path("unused"), tmp_path / "raw")


def test_complete_evaluation_is_never_replaced(tmp_path):
    (tmp_path / "evaluation.json").write_text("original")
    with pytest.raises(ValueError, match="immutable"):
        study.score(tmp_path)
    assert (tmp_path / "evaluation.json").read_text() == "original"
