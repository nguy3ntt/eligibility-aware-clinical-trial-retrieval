"""Immutable evidence, passage coverage and independent trial-level fusion checks."""

import copy
import json
import re
from types import SimpleNamespace

import numpy as np
import pytest

from pipelines import field_passages as fp
from pipelines.embeddings import EncodedBatch, file_record
from pipelines.rerank import demo_data


class Tokenizer:
    def __call__(self, text, **_):
        return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}


class Encoder:
    spec = SimpleNamespace(dimension=3, max_tokens=256)
    metadata = {"snapshot_sha256": "fixture", "model": {"dimension": 3, "max_tokens": 256}}
    model = SimpleNamespace(tokenizer=Tokenizer())

    def encode(self, texts):
        vectors = []
        for text in texts:
            words = text.lower().split()[:254]
            v = np.array([1 + words.count("asthma"), 1 + words.count("knee"), 1], dtype=np.float32)
            vectors.append(v / np.linalg.norm(v))
        return EncodedBatch(np.stack(vectors), [len(t.split()) + 2 for t in texts])


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    _, _, records = demo_data()
    rows = [r["row"] for r in records.values()]
    encoder = Encoder()
    baseline = encoder.encode([r["representations"]["title_conditions"] for r in rows]).vectors
    contract = {
        "artifact_sha256": "invented",
        "snapshot_sha256": "fixture",
        "dimension": 3,
        "model": encoder.metadata["model"],
    }
    monkeypatch.setattr(fp, "artifact_contract", lambda _: (contract, rows, baseline))
    monkeypatch.setattr(fp, "load_evidence", lambda *_: records)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "manifest.json").write_text("invented source manifest")
    root = tmp_path / "passages"
    fp.build(tmp_path, evidence, root, encoder, batch_size=2)
    return root, tmp_path, evidence


def reseal(root):
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["files"] = [file_record(root / r["path"], root) for r in manifest["files"]]
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_roundtrip_and_independent_fusion(artifact):
    loaded = fp.load(*artifact)
    query = Encoder().encode(["asthma"]).vectors[0]
    ranking = fp.rank(loaded, query)
    assert len(ranking) == 3 and len({r["trial_id"] for r in ranking}) == 3
    for result in ranking:
        expected = sum(1 / (60 + b["rank"]) for b in result["branches"].values())
        assert result["score"] == expected
        assert all(b["segment"]["source_sha256"] for b in result["branches"].values())
    assert [r["trial_id"] for r in ranking] == [r["trial_id"] for r in fp.rank(loaded, query)]
    # One trial with multiple matching passages cannot multiply its field contribution.
    duplicate = copy.deepcopy(loaded)
    duplicate[3]["passages"] *= 2
    duplicate[4]["passages"] = np.tile(duplicate[4]["passages"], (2, 1))
    assert fp.rank(duplicate, query) == ranking


def test_filter_argument_order_and_unknown_demographics(artifact):
    loaded = fp.load(*artifact)
    query = Encoder().encode(["asthma"]).vectors[0]
    for row in loaded[1]:
        row["filter_metadata"]["minimum_age"] = "65 Years"
    assert fp.rank(loaded, query, demographics={"age_days": 40 * 365.2425}) == []
    assert len(fp.rank(loaded, query, demographics={"age_days": None, "sex": None})) == 3


def test_windows_preserve_all_nonwhitespace_source_and_overlap():
    original = " αβ " + " ".join(f"word{i}" for i in range(650)) + "  "
    windows = fp.windows(original, Tokenizer())
    covered = {i for w in windows for i in range(w["start"], w["end"])}
    assert all(c.isspace() or i in covered for i, c in enumerate(original))
    assert len(windows) > 3
    assert all(w["text"] == original[w["start"] : w["end"]] for w in windows)
    assert all(
        b["token_start"] == a["token_end"] - 32 for a, b in zip(windows, windows[1:], strict=False)
    )


def test_late_query_term_is_present_in_a_passage_not_whole_field_prefix():
    text = "background " * 500 + "asthma"
    encoder = Encoder()
    field = encoder.encode([text]).vectors[0]
    chunks = fp.windows(text, encoder.model.tokenizer)
    passage = encoder.encode([w["text"] for w in chunks]).vectors
    query = encoder.encode(["asthma"]).vectors[0]
    assert max(passage @ query) > float(field @ query)
    assert all(n <= 256 for n in encoder.encode([w["text"] for w in chunks]).token_counts)


@pytest.mark.parametrize(
    "damage",
    ["checksum", "source_span", "source_identity", "omitted_field", "baseline", "implementation"],
)
def test_corruption_and_resealed_semantic_tampering_are_rejected(artifact, damage):
    root, index, evidence = artifact
    if damage == "checksum":
        (root / "segments.json").write_text("damaged")
    elif damage == "baseline":
        v = np.load(root / "baseline.npy")
        v[0] = v[1]
        np.save(root / "baseline.npy", v)
        reseal(root)
    elif damage == "implementation":
        manifest = json.loads((root / "manifest.json").read_bytes())
        manifest["implementation_sha256"] = "wrong"
        (root / "manifest.json").write_text(json.dumps(manifest))
    else:
        parts = json.loads((root / "segments.json").read_bytes())
        if damage == "source_span":
            parts["passages"][0]["text"] = "not original"
        elif damage == "source_identity":
            parts["passages"][0]["source_sha256"] = "wrong"
        else:
            parts["passages"].pop()
            np.save(root / "passages.npy", np.load(root / "passages.npy")[:-1])
        (root / "segments.json").write_text(json.dumps(parts))
        reseal(root)
    with pytest.raises(ValueError):
        fp.load(root, index, evidence)


def test_fresh_destination_and_bad_query_boundaries(artifact):
    root, index, evidence = artifact
    with pytest.raises(FileExistsError):
        fp.build(index, evidence, root, Encoder())
    loaded = fp.load(*artifact)
    with pytest.raises(ValueError):
        fp.rank(loaded, np.array([np.nan, 0, 0], dtype=np.float32))
    with pytest.raises(ValueError):
        fp.rank(loaded, np.ones(3, dtype=np.float32), variant="unsafe")


def test_original_field_evidence_is_not_replaced_by_normalized_text():
    _, _, records = demo_data()
    original = list(records.values())
    segments = fp.segments_for(original, Tokenizer())
    assert "eligibility_text" not in {p["field"] for p in segments["passages"]}
    assert all(p["locator"].startswith("/clinical_study/") for p in segments["passages"])


@pytest.mark.parametrize("variant", ["baseline", "summary", "fields", "passages"])
def test_full_rank_order_matches_independent_scalar_pooling_reference(artifact, variant):
    loaded = fp.load(*artifact)
    _, rows, _, segments, vectors = loaded
    query = Encoder().encode(["asthma"]).vectors[0]
    branches = {}
    if variant in {"baseline", "fields", "passages"}:
        branches["title_conditions"] = [
            (r["trial_id"], v.tolist()) for r, v in zip(rows, vectors["baseline"], strict=True)
        ]
    if variant in {"fields", "passages", "summary"}:
        for part, vector in zip(segments[variant], vectors[variant], strict=True):
            branches.setdefault(part["field"], []).append((part["trial_id"], vector.tolist()))
    scores = {}
    for values in branches.values():
        best = {}
        for tid, vector in values:
            similarity = max(
                -1.0, min(1.0, sum(float(q) * v for q, v in zip(query, vector, strict=True)))
            )
            best[tid] = max(best.get(tid, -2.0), similarity)
        for i, (tid, similarity) in enumerate(sorted(best.items(), key=lambda v: (-v[1], v[0])), 1):
            scores[tid] = scores.get(tid, 0.0) + (
                1 / (60 + i) if variant in {"fields", "passages"} else similarity
            )
    expected = sorted(scores, key=lambda tid: (-scores[tid], tid))
    actual = fp.rank(loaded, query, variant=variant)
    assert [r["trial_id"] for r in actual] == expected
    assert all(abs(r["score"] - scores[r["trial_id"]]) < 1e-6 for r in actual)
