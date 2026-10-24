"""Reproduce the sealed retrospective head experiment from cached frozen features."""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.app.services.retrieval.domain_reranker import (
    DEFAULT_MODEL,
    FEATURE_DIMENSION,
    TRAINING,
    VERSION,
    FeatureReranker,
    code_identity,
    runtime_identity,
    validate_adapter,
)
from evaluation.release_benchmark import paired_interval
from pipelines.criteria.artifacts import local_id
from pipelines.embeddings import file_hash, verify_files
from pipelines.hard_negatives import DEFAULT_DATA, load_dataset
from pipelines.train_domain_reranker import cohort_metrics, feature_keys, fit_head


def read(path):
    return json.loads(path.read_bytes())


def verify_seals(data_root, model_root, study):
    """Reject incomplete or changed inventories before loading feature arrays."""
    manifest, head = validate_adapter(model_root)
    seal, protocol = read(study / "fit-seal.json"), read(study / "protocol.json")
    if (
        seal["status"] != "fit_sealed"
        or seal["version"] != VERSION
        or seal["model_manifest_sha256"] != file_hash(model_root / "manifest.json")
        or seal["data_manifest_sha256"] != file_hash(data_root / "manifest.json")
        or manifest["dataset_manifest_sha256"] != seal["data_manifest_sha256"]
        or protocol["data_manifest_sha256"] != seal["data_manifest_sha256"]
        or seal["protocol_sha256"] != file_hash(study / "protocol.json")
        or protocol["code_identity"] != code_identity()
        or protocol["runtime"] != runtime_identity()
        or protocol["training"] != TRAINING
        or seal["test_features_or_labels_consumed_by_fit"] is not False
    ):
        raise ValueError("fit seal/source/configuration mismatch")
    verify_files(
        study,
        seal["files"],
        {
            "protocol.json",
            "fit-features.npy",
            "fit-feature-evidence.json",
            "training-controls.json",
        },
    )
    test = study / "test"
    report = read(test / "experiment.json")
    verify_files(
        test,
        report["files"],
        {"stage.json", "features.npy", "feature-evidence.json", "results.json"},
    )
    stage = read(test / "stage.json")
    fit_hash = file_hash(study / "fit-seal.json")
    chronology = [
        protocol["created_at_utc"],
        manifest["sealed_at_utc"],
        seal["sealed_at_utc"],
        stage["opened_at_utc"],
    ]
    stamps = [datetime.fromisoformat(t) for t in chronology]
    if (
        stamps != sorted(stamps)
        or report["fit_seal_sha256"] != fit_hash
        or stage["fit_seal_sha256"] != fit_hash
        or report["status"] != "complete"
        or report["version"] != VERSION
        or report["test_opened_after_fit_seal"] is not True
        or report["test_labels_used_for_training_or_selection"] is not False
        or report["project_unseen_holdout"] is not False
        or report["default_promotion"] is not False
    ):
        raise ValueError("test chronology or research boundary mismatch")
    return manifest, head, protocol, report


def feature_matrix(root, matrix_name, evidence_name, expected):
    evidence = read(root / evidence_name)
    keys = [(r["case_id"], r["trial_id"]) for r in evidence]
    matrix = np.load(root / matrix_name, allow_pickle=False)
    if (
        len(keys) != len(set(keys))
        or set(keys) != set(expected)
        or matrix.shape != (len(keys), FEATURE_DIMENSION)
        or matrix.dtype != np.float32
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("frozen feature inventory/values mismatch")
    return {key: i for i, key in enumerate(keys)}, matrix, evidence


def verify(data_root, model_root, study):
    manifest, head, protocol, report = verify_seals(data_root, model_root, study)
    _, data = load_dataset(data_root)
    if manifest["case_partitions"] != data["split"]["cases"]:
        raise ValueError("model exposure differs from sealed split")
    model = FeatureReranker()  # Load pinned head only; no transformer inference or updates.
    if protocol["base_model"] != model.metadata or manifest["base_model"] != model.metadata:
        raise ValueError("base model mismatch")
    fit_data = {k: v for k, v in data.items() if not k.endswith("-test")}
    expected = set(feature_keys(fit_data, "train") + feature_keys(fit_data, "dev"))
    indexed, features, evidence = feature_matrix(
        study, "fit-features.npy", "fit-feature-evidence.json", expected
    )
    test = study / "test"
    test_indexed, test_features, test_evidence = feature_matrix(
        test, "features.npy", "feature-evidence.json", feature_keys(data, "test")
    )
    for matrix, rows in ((features, evidence), (test_features, test_evidence)):
        if not np.allclose(
            matrix @ model.base_weight + model.base_bias,
            [r["baseline_score"] for r in rows],
            atol=1e-5,
            rtol=0,
        ):
            raise ValueError("frozen features differ from original logits")
    controls = read(study / "training-controls.json")
    for sampler in ("random", "hard"):

        def measured(weight):
            return cohort_metrics(fit_data, "dev", indexed, features, weight, model.base_bias)[
                "aggregate"
            ]["ndcg_at_10"]

        reproduced = fit_head(
            fit_data[f"pairs-{sampler}"],
            indexed,
            features,
            model.base_weight,
            model.base_bias,
            measured,
        )
        reproduced["sampler"] = sampler
        if reproduced != controls[sampler]:
            raise ValueError("training/selection reproduction differs")
    if head != {k: controls["hard"][k] for k in head}:
        raise ValueError("selected model differs from sealed training")
    models = {
        "dense": None,
        "base_reranker": model.base_weight,
        "random_head": np.asarray(controls["random"]["weight"], dtype=np.float32),
        "hard_head": np.asarray(controls["hard"]["weight"], dtype=np.float32),
    }
    results = {
        name: cohort_metrics(data, "test", test_indexed, test_features, weight, model.base_bias)
        for name, weight in models.items()
    }
    comparisons = {
        name: paired_interval(results["base_reranker"]["per_case"], results[name]["per_case"])
        for name in ("random_head", "hard_head")
    }
    for name, baseline in (("hard_vs_random", "random_head"), ("hard_vs_dense", "dense")):
        comparisons[name] = paired_interval(
            results[baseline]["per_case"], results["hard_head"]["per_case"]
        )
    if (
        results != read(test / "results.json")
        or report["metrics"] != {n: r["aggregate"] for n, r in results.items()}
        or report["comparisons"] != comparisons
        or report["selected_epochs"] != {s: r["selected_epoch"] for s, r in controls.items()}
    ):
        raise ValueError("test rankings/metrics/interval reproduction differs")
    return {
        "status": "verified",
        "training_controls_reproduced": 2,
        "test_rankings_reproduced": sum(len(r["rankings"]) for r in results.values()),
        "selected_epochs": report["selected_epochs"],
        "promoted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-id", type=local_id, default=DEFAULT_DATA)
    parser.add_argument("--model-id", type=local_id, default=DEFAULT_MODEL)
    parser.add_argument("--study-id", type=local_id, default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify(
                    Path("data/processed") / args.data_id,
                    Path("models") / args.model_id,
                    Path("evaluation/reports") / args.study_id,
                )
            )
        )
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.exit(1, f"Study verification failed ({type(exc).__name__}); preserve evidence.\n")


if __name__ == "__main__":
    main()
