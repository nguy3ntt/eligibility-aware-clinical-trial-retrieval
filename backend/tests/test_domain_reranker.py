"""Safe head artifacts, real pinned features and bounded training behaviour."""

import json
import os

import numpy as np
import pytest

from backend.app.services.retrieval import domain_reranker as dr
from pipelines.embeddings import file_record
from pipelines.train_domain_reranker import fit_head


@pytest.fixture
def adapter(tmp_path):
    head = {
        "weight": [0.0] * 384,
        "bias": 0.0,
        "selected_epoch": 0,
        "sampler": "hard",
        "feature_contract": "pinned_classifier_input_eval_v1",
    }
    (tmp_path / "head.json").write_text(json.dumps(head))
    (tmp_path / "training.json").write_text(json.dumps({"history": []}))
    manifest = {
        "version": dr.VERSION,
        "status": "complete",
        "training": dr.TRAINING,
        "runtime": dr.runtime_identity(),
        "code_identity": dr.code_identity(),
        "promoted": False,
        "base_model": {"fixture": "base"},
        "source_artifact_sha256": "source",
        "files": [file_record(tmp_path / n, tmp_path) for n in ("head.json", "training.json")],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


@pytest.mark.parametrize(
    "damage", ["nan", "dimension", "promoted", "runtime", "source", "base", "checksum"]
)
def test_adapter_fails_closed_on_tampering_or_incompatible_identity(adapter, damage):
    if damage in {"nan", "dimension"}:
        p = json.loads((adapter / "head.json").read_bytes())
        if damage == "nan":
            p["weight"][0] = float("nan")
        else:
            p["weight"] = [0.0]
        (adapter / "head.json").write_text(json.dumps(p))
        m = json.loads((adapter / "manifest.json").read_bytes())
        m["files"] = [file_record(adapter / n, adapter) for n in ("head.json", "training.json")]
        (adapter / "manifest.json").write_text(json.dumps(m))
    elif damage in {"promoted", "runtime"}:
        m = json.loads((adapter / "manifest.json").read_bytes())
        if damage == "promoted":
            m["promoted"] = True
        else:
            m["runtime"] = {}
        (adapter / "manifest.json").write_text(json.dumps(m))
    elif damage == "checksum":
        (adapter / "head.json").write_text("damaged")
    with pytest.raises(ValueError):
        dr.validate_adapter(
            adapter,
            base_metadata={"fixture": "different" if damage == "base" else "base"},
            source_artifact_sha256="different" if damage == "source" else "source",
        )


def test_training_changes_only_a_cloned_head_and_is_reproducible():
    pytest.importorskip("torch")
    features = np.zeros((2, 384), dtype=np.float32)
    features[0, 0], features[1, 0] = 1.0, -1.0
    initial = np.zeros(384, dtype=np.float32)
    pairs = [{"case_id": "invented", "positive_id": "pos", "negative_id": "neg"}]
    indexed = {("invented", "pos"): 0, ("invented", "neg"): 1}

    def measure(weight):
        return float(weight[0])

    first = fit_head(pairs, indexed, features, initial, 0.5, measure)
    second = fit_head(pairs, indexed, features, initial, 0.5, measure)
    assert first == second
    assert first["weight"][0] > 0 and first["bias"] == 0.5
    assert initial.tolist() == [0.0] * 384
    assert (
        first["history"][-1]["train_pair_loss_before_update"]
        < first["history"][1]["train_pair_loss_before_update"]
    )


def test_checkpoint_ties_select_unmodified_baseline():
    pytest.importorskip("torch")
    features = np.zeros((2, 384), dtype=np.float32)
    features[0, 0] = 1
    result = fit_head(
        [{"case_id": "invented", "positive_id": "p", "negative_id": "n"}],
        {("invented", "p"): 0, ("invented", "n"): 1},
        features,
        np.zeros(384, dtype=np.float32),
        0.0,
        lambda _: 0.5,
    )
    assert result["selected_epoch"] == 0 and result["weight"] == [0.0] * 384
    assert result["final_delta_l2_norm"] > 0


def test_fit_source_verification_does_not_parse_test_grades(tmp_path, monkeypatch):
    from pipelines import train_domain_reranker as training
    from pipelines.tests.test_hard_negatives import case

    cases = [case("trec-ct-2022:" + str(i)) for i in (1, 2, 3)]
    monkeypatch.setattr(training, "load_cases", lambda *_args, **_kw: cases)
    qrels = tmp_path / "invented-qrels.txt"
    qrels.write_text(
        "1 0 train-positive 1\n1 0 train-negative 0\n"
        "2 0 dev-positive 2\n3 0 test-positive NOT-A-GRADE\n"
    )
    monkeypatch.setattr(training, "QRELS", qrels)
    split = {
        "cases": {c.case_id: p for c, p in zip(cases, ("train", "dev", "test"), strict=True)},
        "trials": {
            "train-positive": "train",
            "train-negative": "train",
            "dev-positive": "dev",
            "test-positive": "test",
        },
    }
    data = {
        "split": split,
        "cases-train": [cases[0].model_dump(mode="json")],
        "cases-dev": [cases[1].model_dump(mode="json")],
        "labels-train": {cases[0].case_id: {"train-positive": 1, "train-negative": 0}},
        "labels-dev": {cases[1].case_id: {"dev-positive": 2}},
    }
    rows = [{"trial_id": tid} for tid in split["trials"]]
    training.verify_fit_sources(data, rows)
    data["labels-train"][cases[0].case_id]["train-positive"] = 0
    with pytest.raises(ValueError, match="external judgments"):
        training.verify_fit_sources(data, rows)


@pytest.mark.skipif(
    os.environ.get("RUN_RERANKER_TESTS") != "1", reason="explicit local model opt-in"
)
def test_actual_frozen_features_reproduce_pinned_logits_without_parameter_updates():
    from pipelines.rerank import demo_data

    case, _, records = demo_data()
    model = dr.FeatureReranker()
    before = model.base_weight.copy()
    docs = [r["row"]["representations"]["summary"] for r in records.values()]
    features, scored = model.features(case, docs)
    assert features.shape == (3, 384)
    assert np.allclose(features @ before + model.base_bias, [r["score"] for r in scored], atol=1e-5)
    assert all(not parameter.requires_grad for parameter in model.model.parameters())
    assert np.array_equal(model.base_weight, before)
