"""Milestone 1 bounded acquisition and deterministic, offline source profiling."""

import argparse
import json
import platform
from collections import Counter
from pathlib import Path

import httpx

from pipelines.connectors.clinicaltrials import API_ROOT, fetch_trials, study_id
from pipelines.connectors.snapshots import Snapshot, sha256, verify_snapshot, write_json
from pipelines.connectors.trec import (
    QRELS_URL,
    SOURCE_PAGE,
    TOPICS_URL,
    SourceValidationError,
    load_qrels,
    load_topics,
    select_trial_ids,
)

VERSION = "m1-inspection-v1"
SEED = "trec-2022-inspection-v1"
FIELDS = {
    "nct_id": ("identificationModule.nctId", str),
    "brief_title": ("identificationModule.briefTitle", str),
    "official_title": ("identificationModule.officialTitle", str),
    "brief_summary": ("descriptionModule.briefSummary", str),
    "detailed_description": ("descriptionModule.detailedDescription", str),
    "overall_status": ("statusModule.overallStatus", str),
    "last_update_date": ("statusModule.lastUpdatePostDateStruct.date", str),
    "start_date": ("statusModule.startDateStruct.date", str),
    "study_type": ("designModule.studyType", str),
    "phases": ("designModule.phases", list),
    "enrollment": ("designModule.enrollmentInfo.count", int),
    "conditions": ("conditionsModule.conditions", list),
    "interventions": ("armsInterventionsModule.interventions", list),
    "locations": ("contactsLocationsModule.locations", list),
    "eligibility_text": ("eligibilityModule.eligibilityCriteria", str),
    "sex": ("eligibilityModule.sex", str),
    "minimum_age": ("eligibilityModule.minimumAge", str),
    "maximum_age": ("eligibilityModule.maximumAge", str),
    "healthy_volunteers": ("eligibilityModule.healthyVolunteers", bool),
    "standard_ages": ("eligibilityModule.stdAges", list),
    "study_population": ("eligibilityModule.studyPopulation", str),
}
ABSENT = object()
INVALID_CONTAINER = object()


def code_hashes() -> dict:
    paths = [Path(__file__), *sorted((Path(__file__).parent / "connectors").glob("*.py"))]
    return {
        path.relative_to(Path(__file__).parent).as_posix(): sha256(path.read_bytes())
        for path in paths
    }


def acquire(root: Path, limit: int, seed: str, client: httpx.Client) -> dict:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    snapshot = Snapshot(root)
    manifest = {
        "pipeline_version": VERSION,
        "code_hashes": code_hashes(),
        "python_version": platform.python_version(),
        "httpx_version": httpx.__version__,
        "status": "failed",
        "config": {
            "limit": limit,
            "seed": seed,
            "selection": "sha256-ranked-unique-qrel-ids-v1",
            "batch_size": 100,
        },
        "sources": {
            "topics": {"url": TOPICS_URL, "synthetic_evidence": SOURCE_PAGE},
            "qrels": {
                "url": QRELS_URL,
                "labels": {"0": "not_relevant", "1": "excluded", "2": "eligible"},
            },
            "ctgov": {
                "url": API_ROOT,
                "terms_url": "https://clinicaltrials.gov/about-site/terms-conditions",
            },
        },
        "redistribution": (
            "Local research snapshots only; source terms apply, not repository MIT licence."
        ),
        "benchmark_corpus_date": "2021-04-27",
        "current_api_is_benchmark_corpus": False,
        "issues": [],
    }
    try:
        topics = load_topics(snapshot.capture(client, "topics2022.xml", TOPICS_URL))
        manifest["source_warnings"] = sorted(
            {topic["source_warning"] for topic in topics if topic["source_warning"]}
        )
        qrels = load_qrels(
            snapshot.capture(client, "qrels2022.txt", QRELS_URL), {t["topic_id"] for t in topics}
        )
        selected = select_trial_ids(qrels, limit, seed)
        manifest["selected_trial_ids"] = selected
        before = json.loads(
            snapshot.capture(client, "api-version-before.json", f"{API_ROOT}/version")
        )
        manifest["issues"] = fetch_trials(client, snapshot, selected)
        after = json.loads(
            snapshot.capture(client, "api-version-after.json", f"{API_ROOT}/version")
        )
        if (
            not isinstance(before, dict)
            or not before.get("dataTimestamp")
            or not before.get("apiVersion")
        ):
            raise ValueError("invalid API version response")
        if before != after:
            raise ValueError(
                "API version/data timestamp changed during acquisition; start a new run"
            )
        manifest["api_version"] = before
        # Retain missing IDs as gaps; malformed/duplicate/unrequested rows invalidate a run.
        fatal = [issue for issue in manifest["issues"] if "source" in issue]
        if fatal:
            raise SourceValidationError(fatal)
        manifest["status"] = "complete"
    except Exception as exc:
        errors = (
            exc.issues
            if isinstance(exc, SourceValidationError)
            else [{"reason": type(exc).__name__}]
        )
        manifest["issues"].extend(issue for issue in errors if issue not in manifest["issues"])
        raise
    finally:
        manifest["files"] = snapshot.files
        write_json(root / "manifest.json", manifest)
    return manifest


def field_value(study: dict, path: str) -> object:
    current = study
    for part in ("protocolSection." + path).split("."):
        if current is ABSENT or current is None:
            return current
        if not isinstance(current, dict):
            return INVALID_CONTAINER
        current = current.get(part, ABSENT)
    return current


def state(value: object, expected: type) -> str:
    if value is ABSENT:
        return "absent"
    if value is None:
        return "null"
    if type(value) is not expected:
        return "wrong_type"
    if isinstance(value, str | list | dict) and not (
        value.strip() if isinstance(value, str) else value
    ):
        return "empty"
    return "present"


def inventory(value: object, path: str = "") -> dict[str, set[str]]:
    """All observed paths and types, folding array positions into [] without storing values."""
    result = {path or "/": {type(value).__name__}}
    children = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else []
    )
    for key, child in children:
        child_path = f"{path}/{key}" if isinstance(value, dict) else f"{path}/[]"
        for observed, types in inventory(child, child_path).items():
            result.setdefault(observed, set()).update(types)
    return result


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def profile(snapshot_root: Path, output: Path) -> dict:
    """Verify raw bytes, then derive auditable profiles; never contact a network service."""
    manifest = verify_snapshot(snapshot_root)
    if manifest.get("pipeline_version") != VERSION:
        raise ValueError("unsupported snapshot version")
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = build_profile(snapshot_root, output, manifest)
    except Exception as exc:
        write_json(
            output / "validation-failure.json",
            {
                "status": "failed",
                "issues": exc.issues
                if isinstance(exc, SourceValidationError)
                else [{"reason": type(exc).__name__}],
            },
        )
        raise
    return report


def build_profile(snapshot_root: Path, output: Path, manifest: dict) -> dict:
    topics = load_topics((snapshot_root / "topics2022.xml").read_bytes())
    qrels = load_qrels(
        (snapshot_root / "qrels2022.txt").read_bytes(), {t["topic_id"] for t in topics}
    )
    selected = select_trial_ids(qrels, manifest["config"]["limit"], manifest["config"]["seed"])
    if selected != manifest["selected_trial_ids"]:
        raise ValueError("sample selection does not reproduce")
    sources = {entry["path"]: entry for entry in manifest["files"]}
    trials, issues = {}, list(manifest["issues"])
    fields = {name: Counter() for name in FIELDS}
    paths: dict[str, Counter] = {}
    statuses, study_types, grades, formats = Counter(), Counter(), Counter(), Counter()
    examples, placeholders = [], []
    age_units, phase_combinations, start_date_lengths = Counter(), Counter(), Counter()
    for name in sorted(sources):
        if not name.startswith("ctgov-"):
            continue
        studies = json.loads((snapshot_root / name).read_bytes())["studies"]
        for index, study in enumerate(studies):
            trial_id = study_id(study)
            if not trial_id or trial_id not in selected or trial_id in trials:
                raise ValueError("invalid, unrequested, or duplicate trial in snapshot")
            source_ref = {
                "file": name,
                "sha256": sources[name]["sha256"],
                "json_pointer": f"/studies/{index}",
            }
            trials[trial_id] = {"record": study, "source": source_ref}
            for path, types in inventory(study).items():
                counts = paths.setdefault(path, Counter())
                counts["records_present"] += 1
                for kind in types:
                    counts[f"type:{kind}"] += 1
            for field, (path, expected) in FIELDS.items():
                field_state = state(field_value(study, path), expected)
                fields[field][field_state] += 1
                if field_state == "wrong_type":
                    issues.append(
                        {
                            "trial_id": trial_id,
                            "field": field,
                            "reason": "wrong type",
                            "source": source_ref,
                        }
                    )
            for counter, field in [(statuses, "overall_status"), (study_types, "study_type")]:
                value = field_value(study, FIELDS[field][0])
                counter[value if isinstance(value, str) else "<missing_or_invalid>"] += 1
            for field in ["minimum_age", "maximum_age"]:
                value = field_value(study, FIELDS[field][0])
                if isinstance(value, str) and value.split():
                    age_units[value.split()[-1]] += 1
            value = field_value(study, FIELDS["phases"][0])
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                phase_combinations[",".join(value) or "<empty>"] += 1
            else:
                phase_combinations["<absent_or_invalid>"] += 1
            value = field_value(study, FIELDS["start_date"][0])
            start_date_lengths[
                str(len(value)) if isinstance(value, str) else "absent_or_invalid"
            ] += 1
            text = field_value(study, FIELDS["eligibility_text"][0])
            if isinstance(text, str) and text.strip():
                lowered = text.lower()
                if lowered.strip().rstrip(".") in {
                    "no eligibility criteria",
                    "not provided",
                    "n/a",
                }:
                    placeholders.append({"trial_id": trial_id, "source": source_ref})
                category = (
                    "both_heading_markers"
                    if "inclusion criteria" in lowered and "exclusion criteria" in lowered
                    else "other_format"
                )
                formats[category] += 1
                if sum(example["category"] == category for example in examples) < 6:
                    examples.append(
                        {
                            "trial_id": trial_id,
                            "category": category,
                            "text": text,
                            "source": {
                                **source_ref,
                                "field": "/protocolSection/eligibilityModule/eligibilityCriteria",
                            },
                        }
                    )
            else:
                formats["missing_or_invalid"] += 1
    topic_map = {topic["topic_id"]: topic for topic in topics}
    trace = []
    for row in qrels:
        grades[str(row["grade"])] += 1
        trial = trials.get(row["trial_id"])
        trace.append(
            {
                **row,
                "case_id": topic_map[row["topic_id"]]["case_id"],
                "topic_source": {
                    "file": "topics2022.xml",
                    "sha256": sources["topics2022.xml"]["sha256"],
                    "locator": topic_map[row["topic_id"]]["source_locator"],
                },
                "qrel_source": {
                    "file": "qrels2022.txt",
                    "sha256": sources["qrels2022.txt"]["sha256"],
                    "line": row["source_line"],
                },
                "current_trial_source": trial["source"] if trial else None,
                "current_trial_status": "available"
                if trial
                else "missing_from_api"
                if row["trial_id"] in selected
                else "outside_bounded_sample",
                "historical_trial_status": "not_loaded",
                "benchmark_comparable": False,
            }
        )
    # Prepare, do not claim completion of, ten human reviews, cycling across all three grades.
    candidates = {
        grade: [row for row in trace if row["grade"] == grade and row["current_trial_source"]]
        for grade in range(3)
    }
    pairs, used, used_topics = [], set(), set()
    while len(pairs) < 10:
        added = False
        for grade in range(3):
            candidate = next(
                (
                    row
                    for row in candidates[grade]
                    if row["trial_id"] not in used and row["topic_id"] not in used_topics
                ),
                next((row for row in candidates[grade] if row["trial_id"] not in used), None),
            )
            if candidate is None or len(pairs) == 10:
                continue
            used.add(candidate["trial_id"])
            used_topics.add(candidate["topic_id"])
            added = True
            record = trials[candidate["trial_id"]]["record"]
            evidence = field_value(record, FIELDS["eligibility_text"][0])
            pairs.append(
                {
                    **candidate,
                    "synthetic_case_text": topic_map[candidate["topic_id"]]["text"],
                    "trial_eligibility_text": evidence if isinstance(evidence, str) else None,
                    "eligibility_source_field": (
                        "/protocolSection/eligibilityModule/eligibilityCriteria"
                    ),
                    "human_review_status": "pending",
                    "review_notes": None,
                    "system_eligibility_assessment": None,
                }
            )
        if not added:
            break
    count = len(trials)
    report = {
        "pipeline_version": VERSION,
        "scope": (
            "Current API records for a hash-selected subset of unique TREC 2022 judged IDs; "
            "not a population sample or benchmark run."
        ),
        "source_warnings": manifest["source_warnings"],
        "api_version": manifest["api_version"],
        "topics": len(topics),
        "qrels": len(qrels),
        "qrel_unique_trials": len({row["trial_id"] for row in qrels}),
        "qrel_grades": dict(grades),
        "requested_trials": len(selected),
        "received_trials": count,
        "missing_requested_ids": sorted(set(selected) - trials.keys()),
        "qrels_with_current_trial": sum(
            row["current_trial_status"] == "available" for row in trace
        ),
        "qrels_outside_sample": sum(
            row["current_trial_status"] == "outside_bounded_sample" for row in trace
        ),
        "qrels_missing_from_api": sum(
            row["current_trial_status"] == "missing_from_api" for row in trace
        ),
        "historical_trial_records_loaded": 0,
        "validation_issues": len(issues),
        "human_reviews_completed": 0,
        "review_pairs_prepared": len(pairs),
        "overall_status": dict(sorted(statuses.items())),
        "study_types": dict(sorted(study_types.items())),
        "eligibility_format_markers": dict(formats),
        "eligibility_placeholder_records": placeholders,
        "age_unit_tokens": dict(sorted(age_units.items())),
        "phase_combinations": dict(sorted(phase_combinations.items())),
        "start_date_string_lengths": dict(sorted(start_date_lengths.items())),
        "fields": {
            name: {
                "source_path": f"protocolSection.{FIELDS[name][0]}",
                "expected_type": FIELDS[name][1].__name__,
                **{
                    key: counts[key] for key in ["present", "absent", "null", "empty", "wrong_type"]
                },
            }
            for name, counts in fields.items()
        },
    }
    write_json(output / "profile.json", report)
    write_json(output / "field-inventory.json", paths)
    write_json(output / "validation-issues.json", issues)
    write_json(output / "eligibility-examples.json", examples)
    write_jsonl(output / "topics.jsonl", topics)
    write_jsonl(output / "qrels.jsonl", qrels)
    write_jsonl(output / "qrel-trial-trace.jsonl", trace)
    write_jsonl(output / "pair-review.jsonl", pairs)
    summary = [
        "# Bounded source profile",
        "",
        report["scope"],
        "",
        f"Trials: {count}/{len(selected)}. Topics: {len(topics)}. Qrels: {len(qrels)}.",
        "",
        "Historical corpus: not loaded. Human pair reviews: pending. "
        "No eligibility decisions or retrieval metrics.",
        "",
        "| Field | Present | Absent | Null | Empty | Wrong type |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, counts in report["fields"].items():
        summary.append(
            f"| {name} | "
            + " | ".join(
                str(counts[k]) for k in ["present", "absent", "null", "empty", "wrong_type"]
            )
            + " |"
        )
    with (output / "summary.md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(summary) + "\n")
    write_json(
        output / "manifest.json",
        {
            "status": "complete",
            "pipeline_version": VERSION,
            "code_hashes": code_hashes(),
            "input_manifest_sha256": sha256((snapshot_root / "manifest.json").read_bytes()),
            "config": manifest["config"],
            "files": [
                {"path": p.name, "sha256": sha256(p.read_bytes()), "bytes": p.stat().st_size}
                for p in sorted(output.iterdir())
            ],
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser(
        "fetch", help="Download official synthetic topics, qrels, and at most 1000 trials"
    )
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--seed", default=SEED)
    inspect = sub.add_parser("profile", help="Verify and profile an existing snapshot offline")
    inspect.add_argument("--run-id", required=True)
    inspect.add_argument("--output-id", required=True)
    args = parser.parse_args()
    for name in [args.run_id, getattr(args, "output_id", args.run_id)]:
        if not name or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in name
        ):
            parser.error(
                "run/output IDs must contain only letters, digits, hyphens, or underscores"
            )
    root = Path("data/raw") / args.run_id
    if args.command == "fetch":
        with httpx.Client(
            timeout=45,
            follow_redirects=True,
            headers={"User-Agent": f"eligibility-aware-research/{VERSION}"},
        ) as client:
            result = acquire(root, args.limit, args.seed, client)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "selected": len(result["selected_trial_ids"]),
                    "issues": len(result["issues"]),
                }
            )
        )
    else:
        result = profile(root, Path("data/interim") / args.output_id)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in [
                        "topics",
                        "qrels",
                        "received_trials",
                        "validation_issues",
                        "review_pairs_prepared",
                    ]
                }
            )
        )


if __name__ == "__main__":
    main()
