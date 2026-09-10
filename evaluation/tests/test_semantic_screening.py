"""Independent calibration arithmetic, split integrity, model guards and advisory separation."""

# ruff: noqa: E402
import copy
import json
import os

import pytest

np = pytest.importorskip("numpy")

from backend.app.services.eligibility.rules import verify
from backend.app.services.eligibility.semantic import (
    FILES,
    MODEL_DIR,
    REPOSITORY,
    REVISION,
    LocalNLI,
    advise,
    probabilities,
    proposal,
    validate_snapshot,
)
from backend.tests.test_screening import example
from evaluation.semantic_screening import DEFAULT_FIXTURE, choose_temperature, load_pairs, metrics
from pipelines.criteria.artifacts import file_hash
from pipelines.prepare_nli import download_directory


def test_probability_and_calibration_metrics_against_hand_computation():
    assert probabilities([0, 0, 0]) == pytest.approx([1 / 3] * 3)
    row = {
        "label": "entailment",
        "logits": [0, 0, 0],
        "section": "inclusion",
        "split": "calibration",
    }
    result = metrics([row])
    assert result["nll"] == pytest.approx(np.log(3))
    assert result["brier"] == pytest.approx(2 / 3)
    assert result["high_confidence_precision"] is None
    assert result["high_confidence_decisions"] == 0
    assert result["decision_coverage"] == 0
    high = {**row, "logits": [0, 20, 0]}
    assert metrics([high])["high_confidence_precision"] == 1
    assert metrics([{**high, "label": "contradiction"}])["high_confidence_precision"] == 0


@pytest.mark.parametrize(
    "logits,temperature",
    [([1, 2], 1), ([1, float("nan"), 2], 1), ([1, 2, 3], 0), ([1, 2, 3], float("nan"))],
)
def test_invalid_model_values_fail_closed(logits, temperature):
    with pytest.raises(ValueError):
        probabilities(logits, temperature)


def test_section_polarity_neutral_abstention_and_probability_validation():
    assert proposal([0.01, 0.98, 0.01], "inclusion") == "satisfied"
    assert proposal([0.01, 0.98, 0.01], "exclusion") == "violated"
    assert proposal([0.98, 0.01, 0.01], "exclusion") == "satisfied"
    assert proposal([0.01, 0.01, 0.98], "inclusion") == "unknown"
    assert proposal([0.2, 0.7, 0.1], "inclusion") == "unknown"
    for bad in ([0.1, 0.2, 0.3], [float("nan"), 0, 1]):
        with pytest.raises(ValueError):
            proposal(bad, "inclusion")


def test_temperature_selection_cannot_accept_test_labels():
    row = {
        "label": "entailment",
        "logits": [5, 0, 0],
        "section": "inclusion",
        "split": "calibration",
    }
    assert choose_temperature([row]) == 5
    with pytest.raises(ValueError, match="calibration"):
        choose_temperature([{**row, "split": "test"}])


def test_fixture_duplicates_across_splits_are_rejected(tmp_path):
    data = json.loads(DEFAULT_FIXTURE.read_bytes())
    assert len(load_pairs(DEFAULT_FIXTURE)) == 54
    row = copy.deepcopy(data["pairs"][0])
    row.update(id="duplicated-test", split="test")
    data["pairs"].append(row)
    fixture = tmp_path / "data.json"
    fixture.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="duplicate"):
        load_pairs(fixture)


def test_semantic_advice_never_changes_rule_outcome_or_promotes_itself():
    class Model:
        metadata = {"version": "fake-test-only"}
        calls = 0

        def score(self, case, hypothesis):
            self.calls += 1
            return {
                "status": "scored",
                "probabilities": {"contradiction": 0.01, "entailment": 0.98, "neutral": 0.01},
            }

    model = Model()
    result = verify(*example("The patient has asthma.", "The patient has asthma."))
    raw = result.model_dump_json()
    advice = advise(result, model)
    assert advice["advisories"][0]["proposed_outcome"] == "satisfied"
    assert advice["advisories"][0]["promoted"] is False
    assert advice["screening_status_unchanged"] == "insufficient_information"
    assert result.model_dump_json() == raw
    guarded = verify(*example("17-year-old man.", "Age >= 18 years unless waived."))
    assert advise(guarded, model)["advisories"][0]["status"] == "abstained"
    decided = verify(*example("17-year-old man.", "Age >= 18 years."))
    assert advise(decided, model)["advisories"][0]["status"] == "not_run"
    assert model.calls == 1


def test_snapshot_hashes_revision_and_long_path_guard(tmp_path):
    for name in FILES:
        (tmp_path / name).write_text("fake test data")
    manifest = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "status": "complete",
        "files": {name: file_hash(tmp_path / name) for name in FILES},
    }
    (tmp_path / "snapshot.json").write_text(json.dumps(manifest))
    assert validate_snapshot(tmp_path) == manifest
    (tmp_path / "model.safetensors").write_text("changed")
    with pytest.raises(ValueError):
        validate_snapshot(tmp_path)
    path = download_directory(tmp_path)
    assert path.startswith("\\\\?\\") if os.name == "nt" else path == str(tmp_path.resolve())


def test_real_nli_replay_negation_and_no_truncation():
    if os.environ.get("RUN_NLI_TESTS") != "1":
        pytest.skip("set RUN_NLI_TESTS=1 with the prepared pinned local model")
    from pathlib import Path

    assert (Path("models") / MODEL_DIR / "snapshot.json").is_file()
    model = LocalNLI()
    profile, _ = example("The patient has asthma.", "The patient has asthma.")
    yes = model.score(profile.case, "The patient has asthma.")
    no = model.score(profile.case, "The patient does not have asthma.")
    assert yes["probabilities"]["entailment"] > yes["probabilities"]["contradiction"]
    assert no["probabilities"]["contradiction"] > no["probabilities"]["entailment"]
    assert model.score(profile.case, "The patient has asthma.") == yes
    long = profile.case.model_copy(update={"text": "Synthetic description. " * 500})
    assert model.score(long, "The patient has asthma.")["status"] == "abstained"
