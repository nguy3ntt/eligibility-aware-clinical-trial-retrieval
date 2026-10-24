"""Fit sealed relevance-head artifacts using training pairs and development labels only."""

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.app.schemas.patient import SyntheticCase
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
from backend.app.services.retrieval.reranker import reorder
from evaluation.metrics.retrieval import aggregate_metrics, query_metrics
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.artifacts import local_id
from pipelines.embeddings import file_hash, file_record, verify_files
from pipelines.hard_negatives import DEFAULT_DATA, EVIDENCE, INDEX, QRELS, TOPICS, load_dataset
from pipelines.indexing.qdrant import artifact_contract
from pipelines.reranking_data import load_evidence


def now():
    return datetime.now(UTC).isoformat()


def verify_fit_sources(data, rows):
    """Reproduce train/dev labels from their public source; never parse other grades."""
    split = data["split"]
    if set(split["trials"]) != {r["trial_id"] for r in rows}:
        raise ValueError("trial split differs from source index")
    source_cases = {c.case_id: c for c in load_cases(TOPICS, topics=True)}
    if set(source_cases) != set(split["cases"]):
        raise ValueError("case split differs from official synthetic source")
    expected = {p: {} for p in ("train", "dev")}
    with QRELS.open(encoding="utf-8-sig") as handle:
        for line in handle:
            fields = line.split()
            if not fields:
                continue
            cid, tid = "trec-ct-2022:" + fields[0], fields[2]
            cohort = split["cases"].get(cid)
            if cohort not in expected or split["trials"].get(tid) != cohort:
                continue
            expected[cohort].setdefault(cid, {})[tid] = int(fields[3])
    for cohort in expected:
        if data[f"labels-{cohort}"] != expected[cohort]:
            raise ValueError("training/development labels differ from external judgments")
        for record in data[f"cases-{cohort}"]:
            if SyntheticCase.model_validate(record) != source_cases.get(record["case_id"]):
                raise ValueError("case text/provenance differs from official synthetic source")


def feature_keys(data, cohort):
    keys = set()
    if cohort == "train":
        for sampler in ("hard", "random"):
            for row in data[f"pairs-{sampler}"]:
                keys.update(
                    (row["case_id"], tid) for tid in (row["positive_id"], row["negative_id"])
                )
    else:
        for case_id, candidates in data[f"candidates-{cohort}"].items():
            keys.update((case_id, row["trial_id"]) for row in candidates[:20])
    return sorted(keys)


def collect_features(model, cases, records, keys):
    indexed, metadata, vectors = {}, [], []
    for case in sorted(cases, key=lambda c: c.case_id):
        tids = [tid for cid, tid in keys if cid == case.case_id]
        for start in range(0, len(tids), 32):
            batch = tids[start : start + 32]
            values, evidence = model.features(
                case, [records[tid]["row"]["representations"]["summary"] for tid in batch]
            )
            for tid, vector, row in zip(batch, values, evidence, strict=True):
                indexed[(case.case_id, tid)] = len(vectors)
                vectors.append(vector)
                metadata.append(
                    {
                        "case_id": case.case_id,
                        "trial_id": tid,
                        "baseline_score": row["score"],
                        "input": row["input"],
                    }
                )
    if set(indexed) != set(keys) or not vectors:
        raise ValueError("feature case/trial inventory mismatch")
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (len(keys), FEATURE_DIMENSION) or not np.isfinite(matrix).all():
        raise ValueError("invalid frozen feature matrix")
    return indexed, matrix, metadata


def cohort_metrics(data, cohort, indexed, features, weight, bias):
    runs, per_case = {}, {}
    for case_id, candidates in data[f"candidates-{cohort}"].items():
        if weight is None or not candidates:
            ranking = [r["trial_id"] for r in candidates]
        else:
            scored = [
                {"score": float(features[indexed[(case_id, r["trial_id"])]] @ weight + bias)}
                for r in candidates[:20]
            ]
            ranking = [r["trial_id"] for r in reorder(candidates, scored)]
        runs[case_id] = ranking
        per_case[case_id] = query_metrics(ranking, data[f"labels-{cohort}"].get(case_id, {}))
    return {"aggregate": aggregate_metrics(per_case), "per_case": per_case, "rankings": runs}


def fit_head(pairs, indexed, features, base_weight, bias, dev_measure):
    """No test labels or features are accepted by this optimisation function."""
    import torch

    if (
        not pairs
        or features.shape[1:] != (FEATURE_DIMENSION,)
        or not np.isfinite(features).all()
        or not np.isfinite(bias)
    ):
        raise ValueError("valid training features and pairs required")
    counts = Counter(p["case_id"] for p in pairs)
    deltas = np.stack(
        [
            features[indexed[(p["case_id"], p["positive_id"])]]
            - features[indexed[(p["case_id"], p["negative_id"])]]
            for p in pairs
        ]
    )
    if (
        not np.isfinite(deltas).all()
        or base_weight.shape != (FEATURE_DIMENSION,)
        or not np.isfinite(base_weight).all()
    ):
        raise ValueError("nonfinite training input")
    torch.manual_seed(TRAINING["seed"])
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    x = torch.from_numpy(deltas)
    balance = torch.tensor([1 / counts[p["case_id"]] for p in pairs], dtype=torch.float32)
    initial = torch.from_numpy(base_weight.copy())
    parameter = initial.clone().requires_grad_()
    optimizer = torch.optim.Adam([parameter], lr=TRAINING["learning_rate"])
    best_weight, best_epoch = base_weight.copy(), 0
    best_metric = float(dev_measure(base_weight))
    if not np.isfinite(best_metric):
        raise ValueError("finite development metric required")
    history = [{"epoch": 0, "dev_ndcg_at_10": best_metric}]
    for epoch in range(1, TRAINING["epochs"] + 1):
        optimizer.zero_grad()
        margins = x @ parameter
        pair_loss = (torch.nn.functional.softplus(-margins) * balance).sum() / balance.sum()
        loss = pair_loss + TRAINING["delta_l2"] * ((parameter - initial) ** 2).sum()
        if not torch.isfinite(loss):
            raise ValueError("nonfinite training loss")
        loss.backward()
        if parameter.grad is None or not torch.isfinite(parameter.grad).all():
            raise ValueError("nonfinite relevance-head gradient")
        optimizer.step()
        row = {
            "epoch": epoch,
            "train_pair_loss_before_update": float(pair_loss.detach()),
            "train_regularized_loss_before_update": float(loss.detach()),
        }
        if epoch in TRAINING["checkpoints"]:
            weight = parameter.detach().numpy().copy()
            value = float(dev_measure(weight))
            if not np.isfinite(value):
                raise ValueError("nonfinite development metric")
            row["dev_ndcg_at_10"] = value
            if value > best_metric + 1e-12:
                best_metric, best_epoch, best_weight = value, epoch, weight.copy()
        history.append(row)
    final = parameter.detach().numpy().copy()
    return {
        "weight": best_weight.tolist(),
        "bias": bias,
        "selected_epoch": best_epoch,
        "feature_contract": "pinned_classifier_input_eval_v1",
        "selected_dev_ndcg_at_10": best_metric,
        "final_epoch_weight": final.tolist(),
        "history": history,
        "train_pairs": len(pairs),
        "train_cases": len(counts),
        "final_delta_l2_norm": float(np.linalg.norm(final - base_weight)),
    }


def fit(data_root, output, study, model):
    manifest, data = load_dataset(data_root, stage="fit")
    if any(key.endswith("-test") for key in data):
        raise ValueError("fitting cannot receive test data")
    contract, rows, _ = artifact_contract(INDEX)
    records = load_evidence(EVIDENCE, rows, contract["artifact_sha256"])
    if manifest["source_contract"] != contract or manifest["sources"] != {
        "topics": file_hash(TOPICS),
        "qrels": file_hash(QRELS),
        "evidence_manifest": file_hash(EVIDENCE / "manifest.json"),
    }:
        raise ValueError("training sources differ from prepared mining artifact")
    if output.exists() or study.exists():
        raise ValueError("fresh model and study destinations required")
    verify_fit_sources(data, rows)
    output.mkdir(parents=True)
    study.mkdir(parents=True)
    protocol = {
        "version": VERSION,
        "created_at_utc": now(),
        "training": TRAINING,
        "data_manifest_sha256": file_hash(data_root / "manifest.json"),
        "base_model": model.metadata,
        "runtime": runtime_identity(),
        "code_identity": code_identity(),
        "test_labels_used_for_fit": False,
        "default_promotion": False,
        "limits": "Retrospective split of inspected cases. Lexical group proxies do not prove "
        "semantic/protocol-family or public-model-training independence.",
    }
    write_json(study / "protocol.json", protocol)
    started = time.perf_counter()
    cases = [SyntheticCase.model_validate(c) for p in ("train", "dev") for c in data[f"cases-{p}"]]
    train_keys, dev_keys = feature_keys(data, "train"), feature_keys(data, "dev")
    if any(
        data["split"]["cases"][cid] != "train" or data["split"]["trials"][tid] != "train"
        for cid, tid in train_keys
    ):
        raise ValueError("training feature leakage")
    keys = sorted(set(train_keys + dev_keys))
    indexed, features, feature_meta = collect_features(model, cases, records, keys)
    np.save(study / "fit-features.npy", features, allow_pickle=False)
    write_json(study / "fit-feature-evidence.json", feature_meta)
    base = cohort_metrics(data, "dev", indexed, features, model.base_weight, model.base_bias)
    outputs = {}
    for sampler in ("random", "hard"):

        def measured(weight):
            return cohort_metrics(data, "dev", indexed, features, weight, model.base_bias)[
                "aggregate"
            ]["ndcg_at_10"]

        learned = fit_head(
            data[f"pairs-{sampler}"],
            indexed,
            features,
            model.base_weight,
            model.base_bias,
            measured,
        )
        learned["sampler"] = sampler
        outputs[sampler] = learned
    write_json(study / "training-controls.json", outputs)
    hard = outputs["hard"]
    write_json(
        output / "head.json",
        {k: hard[k] for k in ("weight", "bias", "selected_epoch", "feature_contract", "sampler")},
    )
    write_json(
        output / "training.json",
        {
            "history": hard["history"],
            "train_pairs": hard["train_pairs"],
            "train_cases": hard["train_cases"],
            "final_delta_l2_norm": hard["final_delta_l2_norm"],
            "protocol_sha256": file_hash(study / "protocol.json"),
        },
    )
    adapter = {
        "version": VERSION,
        "status": "complete",
        "sealed_at_utc": now(),
        "training": TRAINING,
        "base_model": model.metadata,
        "runtime": runtime_identity(),
        "code_identity": code_identity(),
        "promoted": False,
        "source_artifact_sha256": contract["artifact_sha256"],
        "dataset_manifest_sha256": file_hash(data_root / "manifest.json"),
        "case_partitions": data["split"]["cases"],
        "files": [file_record(output / name, output) for name in ("head.json", "training.json")],
    }
    write_json(output / "manifest.json", adapter)
    seal = {
        "version": VERSION,
        "status": "fit_sealed",
        "sealed_at_utc": now(),
        "model_manifest_sha256": file_hash(output / "manifest.json"),
        "data_manifest_sha256": file_hash(data_root / "manifest.json"),
        "protocol_sha256": file_hash(study / "protocol.json"),
        "fit_seconds": time.perf_counter() - started,
        "test_features_or_labels_consumed_by_fit": False,
        "files": [file_record(p, study) for p in sorted(study.iterdir())],
    }
    write_json(study / "fit-seal.json", seal)
    validate_adapter(
        output, base_metadata=model.metadata, source_artifact_sha256=contract["artifact_sha256"]
    )
    return {
        "status": "fit_sealed",
        "train_pairs_per_sampler": len(data["pairs-hard"]),
        "dev_base_ndcg_at_10": base["aggregate"]["ndcg_at_10"],
        "selected_epochs": {s: r["selected_epoch"] for s, r in outputs.items()},
        "fit_seconds": seal["fit_seconds"],
    }


def score_test(data_root, output, study, model):
    from evaluation.release_benchmark import paired_interval

    seal = json.loads((study / "fit-seal.json").read_bytes())
    protocol = json.loads((study / "protocol.json").read_bytes())
    if (
        seal["status"] != "fit_sealed"
        or seal["model_manifest_sha256"] != file_hash(output / "manifest.json")
        or seal["data_manifest_sha256"] != file_hash(data_root / "manifest.json")
        or seal["protocol_sha256"] != file_hash(study / "protocol.json")
        or protocol["code_identity"] != code_identity()
        or protocol["runtime"] != runtime_identity()
        or protocol["base_model"] != model.metadata
    ):
        raise ValueError("fit seal/code/runtime/model differs; test scoring refused")
    verify_files(study, seal["files"], {r["path"] for r in seal["files"]})
    validate_adapter(output, base_metadata=model.metadata)
    test = study / "test"
    test.mkdir(exist_ok=False)
    write_json(
        test / "stage.json",
        {
            "opened_at_utc": now(),
            "fit_seal_sha256": file_hash(study / "fit-seal.json"),
            "limits": "Labels inspected in earlier project development; not an unseen-case claim.",
        },
    )
    _, data = load_dataset(data_root)  # Test labels become accessible only after the fit seal.
    _, rows, _ = artifact_contract(INDEX)
    records = load_evidence(EVIDENCE, rows, data["protocol"]["source_contract"]["artifact_sha256"])
    cases = [SyntheticCase.model_validate(c) for c in data["cases-test"]]
    keys = feature_keys(data, "test")
    started = time.perf_counter()
    indexed, features, evidence = collect_features(model, cases, records, keys)
    np.save(test / "features.npy", features, allow_pickle=False)
    write_json(test / "feature-evidence.json", evidence)
    controls = json.loads((study / "training-controls.json").read_bytes())
    models = {
        "dense": None,
        "base_reranker": model.base_weight,
        "random_head": np.asarray(controls["random"]["weight"], dtype=np.float32),
        "hard_head": np.asarray(controls["hard"]["weight"], dtype=np.float32),
    }
    results = {
        name: cohort_metrics(data, "test", indexed, features, weight, model.base_bias)
        for name, weight in models.items()
    }
    write_json(test / "results.json", results)
    comparisons = {
        name: paired_interval(results["base_reranker"]["per_case"], results[name]["per_case"])
        for name in ("random_head", "hard_head")
    }
    comparisons["hard_vs_random"] = paired_interval(
        results["random_head"]["per_case"], results["hard_head"]["per_case"]
    )
    comparisons["hard_vs_dense"] = paired_interval(
        results["dense"]["per_case"], results["hard_head"]["per_case"]
    )
    report = {
        "version": VERSION,
        "status": "complete",
        "fit_seal_sha256": file_hash(study / "fit-seal.json"),
        "test_opened_after_fit_seal": json.loads((test / "stage.json").read_bytes())[
            "opened_at_utc"
        ]
        >= seal["sealed_at_utc"],
        "test_cases": len(cases),
        "test_trials": sum(p == "test" for p in data["split"]["trials"].values()),
        "test_judgments": sum(map(len, data["labels-test"].values())),
        "test_cases_without_judged_relevant": sum(
            not any(g > 0 for g in data["labels-test"].get(c.case_id, {}).values()) for c in cases
        ),
        "metrics": {name: r["aggregate"] for name, r in results.items()},
        "comparisons": comparisons,
        "selected_epochs": {s: r["selected_epoch"] for s, r in controls.items()},
        "feature_inference_seconds": time.perf_counter() - started,
        "test_labels_used_for_training_or_selection": False,
        "project_unseen_holdout": False,
        "default_promotion": False,
        "files": [file_record(p, test) for p in sorted(test.iterdir())],
    }
    write_json(test / "experiment.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fit", "score-test", "verify"])
    parser.add_argument("--data-id", type=local_id, default=DEFAULT_DATA)
    parser.add_argument("--model-id", type=local_id, default=DEFAULT_MODEL)
    parser.add_argument("--study-id", type=local_id, default="domain-hard-reranker-v1")
    args = parser.parse_args()
    data, output, study = (
        Path("data/processed") / args.data_id,
        Path("models") / args.model_id,
        Path("evaluation/reports") / args.study_id,
    )
    try:
        if args.command == "verify":
            manifest, head = validate_adapter(output)
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "selected_epoch": head["selected_epoch"],
                        "promoted": manifest["promoted"],
                    }
                )
            )
            return
        model = FeatureReranker()
        if args.command == "fit":
            result = fit(data, output, study, model)
        else:
            result = score_test(data, output, study, model)
        print(json.dumps({k: v for k, v in result.items() if k not in {"files"}}))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.exit(
            1,
            f"Domain training failed ({type(exc).__name__}); "
            "preserve evidence and use fresh output identities.\n",
        )


if __name__ == "__main__":
    main()
