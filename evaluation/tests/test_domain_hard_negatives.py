"""Invented feature damage must fail before numerical experiment reproduction."""

import json

import numpy as np
import pytest

from evaluation import domain_hard_negatives as study_verifier
from evaluation.domain_hard_negatives import feature_matrix
from pipelines.embeddings import file_hash, file_record


@pytest.mark.parametrize("damage", ["none", "duplicate", "partition", "nan", "dimension", "dtype"])
def test_frozen_feature_inventory(tmp_path, damage):
    rows = [{"case_id": "invented-case", "trial_id": "invented-trial", "baseline_score": 0}]
    values = np.zeros((1, 384), dtype=np.float32)
    if damage == "duplicate":
        rows *= 2
        values = np.zeros((2, 384), dtype=np.float32)
    elif damage == "partition":
        rows[0]["case_id"] = "other-partition"
    elif damage == "nan":
        values[0, 0] = np.nan
    elif damage == "dimension":
        values = np.zeros((1, 1), dtype=np.float32)
    elif damage == "dtype":
        values = values.astype(np.float64)
    (tmp_path / "rows.json").write_text(json.dumps(rows))
    np.save(tmp_path / "values.npy", values, allow_pickle=False)
    args = (tmp_path, "values.npy", "rows.json", [("invented-case", "invented-trial")])
    if damage == "none":
        indexed, matrix, metadata = feature_matrix(*args)
        assert indexed == {("invented-case", "invented-trial"): 0}
        assert np.array_equal(matrix, values) and metadata == rows
    else:
        with pytest.raises(ValueError, match="feature inventory"):
            feature_matrix(*args)


@pytest.mark.parametrize(
    "damage", ["none", "changed_feature", "omitted_file", "chronology", "seal"]
)
def test_seal_verification_rejects_changed_or_incomplete_studies(tmp_path, monkeypatch, damage):
    data, model, study = (tmp_path / name for name in ("data", "model", "study"))
    for root in (data, model, study / "test"):
        root.mkdir(parents=True)

    def write(path, value):
        path.write_text(json.dumps(value))

    write(data / "manifest.json", {})
    manifest = {
        "dataset_manifest_sha256": file_hash(data / "manifest.json"),
        "sealed_at_utc": "2026-01-01T00:00:01+00:00",
    }
    write(model / "manifest.json", manifest)
    monkeypatch.setattr(study_verifier, "validate_adapter", lambda _: (manifest, {}))
    protocol = {
        "data_manifest_sha256": manifest["dataset_manifest_sha256"],
        "code_identity": study_verifier.code_identity(),
        "runtime": study_verifier.runtime_identity(),
        "training": study_verifier.TRAINING,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
    }
    write(study / "protocol.json", protocol)
    for name in ("fit-features.npy", "fit-feature-evidence.json", "training-controls.json"):
        (study / name).write_bytes(b"sealed invented bytes")
    seal = {
        "status": "fit_sealed",
        "version": study_verifier.VERSION,
        "data_manifest_sha256": manifest["dataset_manifest_sha256"],
        "model_manifest_sha256": file_hash(model / "manifest.json"),
        "protocol_sha256": file_hash(study / "protocol.json"),
        "test_features_or_labels_consumed_by_fit": False,
        "sealed_at_utc": "2026-01-01T00:00:02+00:00",
        "files": [file_record(p, study) for p in study.iterdir() if p.is_file()],
    }
    if damage == "omitted_file":
        seal["files"] = [r for r in seal["files"] if r["path"] != "fit-features.npy"]
    write(study / "fit-seal.json", seal)
    test = study / "test"
    stage = {
        "opened_at_utc": "2026-01-01T00:00:03+00:00",
        "fit_seal_sha256": file_hash(study / "fit-seal.json"),
    }
    if damage == "chronology":
        stage["opened_at_utc"] = "2025-12-01T00:00:00+00:00"
    if damage == "seal":
        stage["fit_seal_sha256"] = "wrong seal"
    write(test / "stage.json", stage)
    for name in ("features.npy", "feature-evidence.json", "results.json"):
        (test / name).write_bytes(b"sealed invented test bytes")
    report = {
        "status": "complete",
        "version": study_verifier.VERSION,
        "fit_seal_sha256": file_hash(study / "fit-seal.json"),
        "test_opened_after_fit_seal": True,
        "test_labels_used_for_training_or_selection": False,
        "project_unseen_holdout": False,
        "default_promotion": False,
        "files": [file_record(p, test) for p in test.iterdir()],
    }
    write(test / "experiment.json", report)
    if damage == "changed_feature":
        (study / "fit-features.npy").write_bytes(b"modified")
    if damage == "none":
        assert study_verifier.verify_seals(data, model, study)[0] == manifest
    else:
        with pytest.raises(ValueError):
            study_verifier.verify_seals(data, model, study)
