"""Grouped split isolation, judged-only relevance targets and deterministic mining."""

import copy
import json
from pathlib import Path

import pytest

from backend.app.schemas.patient import SyntheticCase, text_hash
from pipelines import hard_negatives as hn
from pipelines.embeddings import file_hash, file_record


def case(identity):
    return SyntheticCase(
        case_id=identity,
        synthetic=True,
        text="A 40-year-old man with asthma.",
        source="invented-fixture:hard-negative-unit",
        source_sha256="a" * 64,
        source_locator="/invented",
    )


def group_for(partition, kind):
    return next(
        text_hash(str(i)) for i in range(1000) if hn.partition(text_hash(str(i)), kind) == partition
    )


@pytest.fixture
def dataset(tmp_path):
    split = {"cases": {}, "trials": {}, "case_groups": {}, "trial_groups": {}, "audit": {}}
    payload = {}
    for cohort in hn.PARTITIONS:
        cid, pos, neg = cohort + "-case", cohort + "-positive", cohort + "-negative"
        split["cases"][cid] = cohort
        split["case_groups"][cid] = group_for(cohort, "case")
        for tid in (pos, neg):
            split["trials"][tid] = cohort
            split["trial_groups"][tid] = group_for(cohort, "trial")
        payload[f"cases-{cohort}"] = [case(cid).model_dump(mode="json")]
        payload[f"labels-{cohort}"] = {cid: {pos: 1, neg: 0}}
        payload[f"candidates-{cohort}"] = {
            cid: [{"trial_id": pos, "score": 0.5}, {"trial_id": neg, "score": 0.4}]
        }
    payload["split"] = split
    payload["protocol"] = {
        "parameters": hn.PARAMETERS,
        "sources": {},
        "case_split": split["cases"],
        "trial_split": split["trials"],
    }
    for sampler in ("hard", "random"):
        payload[f"pairs-{sampler}"] = [
            {
                "case_id": "train-case",
                "positive_id": "train-positive",
                "negative_id": "train-negative",
                "positive_grade": 1,
                "negative_grade": 0,
                "sampler": sampler,
                "mining": None,
            }
        ]
    payload["mining-skips"] = []
    for name, data in payload.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(data))
    manifest = {
        "status": "complete",
        "version": hn.VERSION,
        "parameters": hn.PARAMETERS,
        "implementation_sha256": file_hash(Path(hn.__file__)),
        "sources": {},
        "files": [file_record(p, tmp_path) for p in sorted(tmp_path.iterdir())],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def change(root, name, update):
    path = root / (name + ".json")
    payload = json.loads(path.read_bytes())
    update(payload)
    path.write_text(json.dumps(payload))
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["files"] = [file_record(root / r["path"], root) for r in manifest["files"]]
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_near_duplicates_and_exact_title_keys_stay_in_one_family():
    original = " ".join("token" + str(i) for i in range(60))
    groups, audit = hn.group_records(
        {"a": original, "b": original + " extra", "c": "other text"}, threshold=0.8
    )
    assert groups["a"] == groups["b"] != groups["c"]
    assert audit["multi_record_groups"] == 1
    groups, _ = hn.group_records(
        {"a": "text a", "b": "different text"},
        threshold=0.85,
        exact_keys={"a": "same title|condition", "b": "same title|condition"},
    )
    assert groups["a"] == groups["b"]
    assert hn.partition(groups["a"], "trial") == hn.partition(groups["b"], "trial")


def test_mining_never_uses_excluded_relevant_or_unjudged_as_negative():
    labels = {"positive-1": 1, "positive-2": 2, "near-zero": 0, "far-zero": 0}
    dense = [
        ("unjudged", 0.99),
        ("positive-1", 0.9),
        ("near-zero", 0.8),
        ("positive-2", 0.7),
        ("far-zero", 0.1),
    ]
    lexical = list(reversed(dense))
    conditions = {tid: "asthma" if tid == "near-zero" else "unrelated" for tid in labels}
    hard, random, skipped = hn.mine_pairs(case("train-case"), labels, dense, lexical, conditions)
    assert skipped is None and len(hard) == len(random)
    assert {p["positive_grade"] for p in hard} == {1, 2}
    assert {p["negative_grade"] for p in hard + random} == {0}
    assert all(p["negative_id"] != "unjudged" for p in hard + random)
    assert (hard, random, skipped) == hn.mine_pairs(
        case("train-case"), labels, dense, lexical, conditions
    )
    assert any(p["mining"]["source_condition_overlap_terms"] == ["asthma"] for p in hard)


def test_cases_without_supported_training_pairs_are_explicit_skips():
    hard, random, skipped = hn.mine_pairs(
        case("case"), {"negative": 0}, [("negative", 0.8)], [], {"negative": "asthma"}
    )
    assert not hard and not random and skipped["reason"] == "no_positive"


def test_fit_access_never_deserializes_test_files(dataset, monkeypatch):
    original = hn.json.loads
    test_payloads = {
        (dataset / f"{kind}-test.json").read_bytes() for kind in ("cases", "labels", "candidates")
    }

    def guarded(raw, *args, **kwargs):
        assert raw not in test_payloads, "fitter decoded a test file"
        return original(raw, *args, **kwargs)

    monkeypatch.setattr(hn.json, "loads", guarded)
    _, data = hn.load_dataset(dataset, stage="fit")
    assert not any(k.endswith("-test") for k in data)


@pytest.mark.parametrize(
    "damage",
    [
        "test_negative",
        "test_positive",
        "grade_one_negative",
        "duplicate_pair",
        "candidate_leak",
        "bad_split",
        "different_budget",
        "changed_bytes",
    ],
)
def test_resealed_leakage_and_label_failures_are_rejected(dataset, damage):
    if damage == "changed_bytes":
        (dataset / "pairs-hard.json").write_text("damaged")
    elif damage in {"test_negative", "test_positive", "grade_one_negative", "duplicate_pair"}:

        def update(rows):
            if damage == "test_negative":
                rows[0]["negative_id"] = "test-negative"
            elif damage == "test_positive":
                rows[0]["positive_id"] = "test-positive"
            elif damage == "grade_one_negative":
                rows[0]["negative_id"] = "train-positive"
            else:
                rows.append(copy.deepcopy(rows[0]))

        change(dataset, "pairs-hard", update)
    elif damage == "candidate_leak":
        change(
            dataset, "candidates-dev", lambda p: p["dev-case"][0].update(trial_id="train-positive")
        )
    elif damage == "bad_split":
        change(dataset, "split", lambda p: p["cases"].update({"train-case": "test"}))
    else:
        change(dataset, "pairs-random", lambda p: p.clear())
    with pytest.raises(ValueError):
        hn.load_dataset(dataset)


def test_complete_invented_dataset_verifies(dataset):
    manifest, data = hn.load_dataset(dataset)
    assert manifest["version"] == hn.VERSION
    assert set(data["split"]["cases"].values()) == set(hn.PARTITIONS)
