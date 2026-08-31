"""Acquire only a preselected bounded set of public trial records via API v2."""

import json

import httpx

from pipelines.connectors.snapshots import Snapshot
from pipelines.connectors.trec import NCT_ID, SourceValidationError

API_ROOT = "https://clinicaltrials.gov/api/v2"


def study_id(study: object) -> str | None:
    try:
        value = study["protocolSection"]["identificationModule"]["nctId"]
    except (KeyError, TypeError):
        return None
    return value if isinstance(value, str) and NCT_ID.fullmatch(value) else None


def fetch_trials(client: httpx.Client, snapshot: Snapshot, trial_ids: list[str]) -> list[dict]:
    if not 1 <= len(trial_ids) <= 1000 or len(set(trial_ids)) != len(trial_ids):
        raise ValueError("expected 1-1000 unique trial IDs")
    if any(not NCT_ID.fullmatch(trial_id) for trial_id in trial_ids):
        raise ValueError("invalid requested NCT ID")
    issues, seen = [], set()
    for offset in range(0, len(trial_ids), 100):
        batch = trial_ids[offset : offset + 100]
        name = f"ctgov-{offset // 100 + 1:03d}.json"
        raw = snapshot.capture(
            client,
            name,
            f"{API_ROOT}/studies",
            {"format": "json", "filter.ids": ",".join(batch), "pageSize": 100},
        )
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceValidationError([{"source": name, "reason": "invalid JSON"}]) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
            raise SourceValidationError([{"source": name, "reason": "expected studies array"}])
        # Each batch is no larger than the requested page; never follow a cursor into a corpus scan.
        if len(payload["studies"]) > len(batch):
            raise SourceValidationError([{"source": name, "reason": "unexpected pagination/size"}])
        for index, study in enumerate(payload["studies"]):
            trial_id = study_id(study)
            reason = None
            if trial_id is None:
                reason = "missing or malformed trial ID"
            elif trial_id not in batch:
                reason = "unrequested trial ID"
            elif trial_id in seen:
                reason = "duplicate trial ID"
            if reason:
                issues.append({"source": name, "locator": f"/studies/{index}", "reason": reason})
            else:
                seen.add(trial_id)
        # The API can emit a cursor for a full page even when all requested IDs arrived.
        # Stop by the explicit ID set; refuse an incomplete paginated batch for inspection.
        if payload.get("nextPageToken") and set(batch) - seen:
            raise SourceValidationError(
                [{"source": name, "reason": "incomplete batch with unexpected pagination"}]
            )
    for trial_id in sorted(set(trial_ids) - seen):
        issues.append({"trial_id": trial_id, "reason": "requested ID absent from current API"})
    return issues
