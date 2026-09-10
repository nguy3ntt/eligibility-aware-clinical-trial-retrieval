"""Bounded, explicit synthetic sources; invalid records never disappear silently."""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from backend.app.schemas.patient import SyntheticCase
from pipelines.connectors.trec import SOURCE_PAGE, load_topics


class SyntheticSourceError(ValueError):
    def __init__(self, positions: list[int]):
        self.issues = [{"position": p, "code": "invalid_or_duplicate_record"} for p in positions]
        super().__init__(f"invalid or duplicate synthetic records at positions {positions}")


def load_cases(path: Path, *, topics: bool = False) -> list[SyntheticCase]:
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError("synthetic case source exceeds 2 MiB")
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    try:
        if topics:
            rows = load_topics(raw)
            source = SOURCE_PAGE
        else:
            dataset = json.loads(raw)
            if not isinstance(dataset, dict) or dataset.get("synthetic") is not True:
                raise ValueError("explicit synthetic dataset flag required")
            if dataset.get("schema_version") != "synthetic-cases-v1":
                raise ValueError("unsupported synthetic fixture schema")
            source = "invented-fixture:" + dataset["dataset_id"]
            rows = dataset["cases"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
            raise ValueError("synthetic source must contain 1..200 cases")
        cases, seen, failures = [], set(), []
        for position, row in enumerate(rows):
            try:
                case = SyntheticCase(
                    case_id=row["case_id"],
                    synthetic=True,
                    text=row["text"],
                    source=source,
                    source_sha256=checksum,
                    source_locator=row["source_locator"] if topics else f"/cases/{position}",
                )
                if case.case_id in seen:
                    raise ValueError("duplicate case ID")
                seen.add(case.case_id)
                cases.append(case)
            except (KeyError, TypeError, ValueError, ValidationError):
                failures.append(position)
        if failures:
            raise SyntheticSourceError(failures)
        return cases
    except (json.JSONDecodeError, UnicodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid synthetic source structure or encoding") from exc
