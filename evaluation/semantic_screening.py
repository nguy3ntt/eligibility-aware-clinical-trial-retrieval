"""Disjoint synthetic calibration/test NLI diagnostic; no automatic clinical promotion."""

import argparse
import json
import math
from pathlib import Path

from backend.app.schemas.patient import SyntheticCase
from backend.app.services.eligibility.semantic import (
    LABELS,
    THRESHOLD,
    LocalNLI,
    probabilities,
    proposal,
)
from evaluation.screening import code_fingerprints
from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash, local_id

DEFAULT_FIXTURE = Path("evaluation/data/fixtures/semantic_screening.json")
TEMPERATURES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)


def load_pairs(path):
    if path.stat().st_size > 1024**2:
        raise ValueError("NLI fixture exceeds 1 MiB")
    data = json.loads(path.read_bytes())
    if data.get("synthetic") is not True or data.get("schema_version") != "synthetic-nli-pairs-v1":
        raise ValueError("explicit synthetic NLI fixture required")
    rows = data["pairs"]
    if not 2 <= len(rows) <= 200:
        raise ValueError("bounded NLI fixture requires 2..200 pairs")
    ids, pairs, splits = set(), set(), set()
    cases = []
    for i, row in enumerate(rows):
        if row["id"] in ids or (row["patient"], row["criterion"]) in pairs:
            raise ValueError("duplicate NLI identity or pair across splits")
        if (
            row["split"] not in {"calibration", "test"}
            or row["label"] not in LABELS
            or row["section"] not in {"inclusion", "exclusion"}
        ):
            raise ValueError("invalid NLI split or label")
        if not isinstance(row["criterion"], str) or not row["criterion"].strip():
            raise ValueError("empty NLI hypothesis")
        case = SyntheticCase(
            case_id=row["id"],
            synthetic=True,
            text=row["patient"],
            source="invented-fixture:" + data["dataset_id"],
            source_sha256=file_hash(path),
            source_locator=f"/pairs/{i}/patient",
        )
        ids.add(row["id"])
        pairs.add((row["patient"], row["criterion"]))
        splits.add(row["split"])
        cases.append((row, case))
    if splits != {"calibration", "test"}:
        raise ValueError("both independent calibration and test splits required")
    return cases


def wilson_lower(correct, total):
    if not total:
        return None
    p, z = correct / total, 1.96
    return (
        p + z * z / (2 * total) - z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    ) / (1 + z * z / total)


def metrics(rows, temperature=1.0):
    probabilities_by_row = [probabilities(r["logits"], temperature) for r in rows]
    labels = [LABELS.index(r["label"]) for r in rows]
    if not rows:
        raise ValueError("cannot calibrate/evaluate an empty scored split")
    predictions = [max(range(3), key=p.__getitem__) for p in probabilities_by_row]
    confidence = [max(p) for p in probabilities_by_row]
    correct = [a == b for a, b in zip(predictions, labels, strict=True)]
    bins, ece = [], 0.0
    for index in range(10):
        indices = [
            i
            for i, c in enumerate(confidence)
            if index / 10 <= c and (c < (index + 1) / 10 or index == 9)
        ]
        if indices:
            accuracy = sum(correct[i] for i in indices) / len(indices)
            mean = sum(confidence[i] for i in indices) / len(indices)
            ece += len(indices) / len(rows) * abs(accuracy - mean)
            bins.append(
                {
                    "lower": index / 10,
                    "upper": (index + 1) / 10,
                    "count": len(indices),
                    "accuracy": accuracy,
                    "confidence": mean,
                }
            )
    decisions = [proposal(p, r["section"]) for p, r in zip(probabilities_by_row, rows, strict=True)]
    expected = [
        "unknown"
        if r["label"] == "neutral"
        else "satisfied"
        if (r["label"] == "entailment") == (r["section"] == "inclusion")
        else "violated"
        for r in rows
    ]
    selected = [i for i, d in enumerate(decisions) if d != "unknown"]
    selected_correct = sum(decisions[i] == expected[i] for i in selected)
    return {
        "pairs": len(rows),
        "accuracy": sum(correct) / len(rows),
        "nll": -sum(
            math.log(max(p[y], 1e-15)) for p, y in zip(probabilities_by_row, labels, strict=True)
        )
        / len(rows),
        "brier": sum(
            sum((p[j] - (j == y)) ** 2 for j in range(3))
            for p, y in zip(probabilities_by_row, labels, strict=True)
        )
        / len(rows),
        "ece_10_bins": ece,
        "reliability_bins": bins,
        "high_confidence_threshold": THRESHOLD,
        "high_confidence_decisions": len(selected),
        "high_confidence_correct": selected_correct,
        "high_confidence_precision": selected_correct / len(selected) if selected else None,
        "high_confidence_precision_wilson_lower_95": wilson_lower(selected_correct, len(selected)),
        "decision_coverage": len(selected) / len(rows),
        "shadow_trial_accuracy": sum(a == b for a, b in zip(decisions, expected, strict=True))
        / len(rows),
        "shadow_trial_definition": "one criterion per invented trial; no promotion into screening",
    }


def choose_temperature(calibration):
    # Test rows must never select temperature, threshold, model or sample.
    if any(r["split"] != "calibration" for r in calibration):
        raise ValueError("temperature selection accepts only calibration rows")
    return min(TEMPERATURES, key=lambda t: (metrics(calibration, t)["nll"], abs(t - 1), t))


def evaluate(path, model, output):
    records = []
    for row, case in load_pairs(path):
        result = model.score(case, row["criterion"])
        records.append(
            {
                **row,
                "source_sha256": case.source_sha256,
                "source_locator": case.source_locator,
                "criterion_locator": case.source_locator.removesuffix("patient") + "criterion",
                **result,
            }
        )
    write_json(output / "predictions.json", records)
    scored = [r for r in records if r["status"] == "scored"]
    calibration = [r for r in scored if r["split"] == "calibration"]
    test = [r for r in scored if r["split"] == "test"]
    temperature = choose_temperature(calibration)
    # Exact query replay checks model.eval/inference_mode and stable inputs.
    row, case = load_pairs(path)[0]
    repeat = model.score(case, row["criterion"])
    if any(repeat[k] != records[0][k] for k in repeat):
        raise ValueError("NLI inference replay changed")
    return {
        "status": "complete",
        "model": model.metadata,
        "temperature": temperature,
        "temperature_grid": list(TEMPERATURES),
        "selection": "calibration NLL only; fixed 0.95 threshold",
        "calibration_raw": metrics(calibration),
        "calibration_scaled": metrics(calibration, temperature),
        "test_raw": metrics(test),
        "test_scaled": metrics(test, temperature),
        "abstained_pairs": len(records) - len(scored),
        "replay_identical": True,
        "promotion": {
            "enabled": False,
            "reason": "research advisory; independent clinical/domain validation absent",
        },
        "fixture_sha256": file_hash(path),
        "predictions_sha256": file_hash(output / "predictions.json"),
        "implementation_sha256": code_fingerprints(),
        "limitation": "Authored disjoint synthetic splits; no clinical validation or test tuning.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output ID.\n")
    try:
        result = evaluate(args.fixture, LocalNLI(), output)
        write_json(output / "experiment.json", result)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in {"implementation_sha256", "model"}},
                indent=2,
            )
        )
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(1, f"NLI evaluation failed ({type(exc).__name__}); inspect local inputs.\n")


if __name__ == "__main__":
    main()
