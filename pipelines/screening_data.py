"""Explicitly invented screening fixtures and reproducible source construction."""

import json
from pathlib import Path

from backend.app.schemas.criteria import EligibilitySource
from backend.app.schemas.patient import SyntheticCase
from pipelines.criteria.artifacts import file_hash

DEFAULT_FIXTURE = Path("evaluation/data/fixtures/screening.json")


def load_pairs(path=DEFAULT_FIXTURE):
    if path.stat().st_size > 1024**2:
        raise ValueError("screening fixture exceeds 1 MiB")
    data = json.loads(path.read_bytes())
    if data.get("synthetic") is not True or data.get("schema_version") != "screening-fixtures-v1":
        raise ValueError("explicit invented screening fixture required")
    rows = data["pairs"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("screening fixture requires 1..100 pairs")
    digest = file_hash(path)
    results, seen = [], set()
    for i, row in enumerate(rows):
        try:
            identity = row["id"]
            if (
                identity in seen
                or not isinstance(row["expected"], list)
                or any(
                    o not in {"satisfied", "violated", "unknown", "not_applicable"}
                    for o in row["expected"]
                )
                or row["status"]
                not in {"potential_match", "likely_exclusion", "insufficient_information"}
            ):
                raise ValueError("invalid or duplicate label")
            seen.add(identity)
            case = SyntheticCase(
                case_id=identity,
                synthetic=True,
                text=row["patient"],
                source="invented-fixture:" + data["dataset_id"],
                source_sha256=digest,
                source_locator=f"/pairs/{i}/patient",
            )
            source = EligibilitySource(
                trial_id=f"NCT{90000000 + i:08}",
                text=row["eligibility"],
                source_kind="invented_trial_fixture",
                source_sha256=digest,
                source_locator=f"/pairs/{i}/eligibility",
                provenance={"dataset_id": data["dataset_id"]},
            )
            results.append((row, case, source))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid screening fixture at position {i}") from exc
    return results
