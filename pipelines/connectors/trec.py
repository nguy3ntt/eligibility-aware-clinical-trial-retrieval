"""Strict loaders for the official synthetic TREC Clinical Trials topics and qrels."""

import hashlib
import re
import xml.etree.ElementTree as ET

NCT_ID = re.compile(r"NCT\d{8}\Z", re.ASCII)
TOPICS_URL = "https://www.trec-cds.org/topics2022.xml"
QRELS_URL = "https://trec.nist.gov/data/trials/qrels2022.txt"
SOURCE_PAGE = "https://www.trec-cds.org/2022.html"
LABELS = {0: "not_relevant", 1: "excluded", 2: "eligible"}
# Observed official topics2022.xml has a stale 2021 task header. Never generalize this
# exception to arbitrary 2021 topics: accept only the exact inspected source bytes.
KNOWN_2022_LEGACY_HEADER_SHA256 = "c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91"


class SourceValidationError(ValueError):
    """Retain every detected issue without echoing patient narratives into logs."""

    def __init__(self, issues: list[dict]) -> None:
        self.issues = issues
        super().__init__(f"Source validation failed with {len(issues)} issue(s)")


def load_topics(raw: bytes) -> list[dict]:
    """Load only the documented 2022 XML format; preserve narrative whitespace."""
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SourceValidationError([{"source": "topics", "reason": "DTD/entity forbidden"}])
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceValidationError([{"source": "topics", "reason": "invalid XML"}]) from exc
    legacy_header = (
        root.get("task") == "2021 TREC Clinical Trials"
        and hashlib.sha256(raw).hexdigest() == KNOWN_2022_LEGACY_HEADER_SHA256
    )
    if root.tag != "topics" or (
        root.get("task") != "2022 TREC Clinical Trials" and not legacy_header
    ):
        raise SourceValidationError([{"source": "topics", "reason": "unexpected task/root"}])
    topics, issues, seen = [], [], set()
    for position, element in enumerate(root, 1):
        topic_id = element.get("number", "")
        narrative = element.text or ""
        if (
            element.tag != "topic"
            or len(element)
            or not re.fullmatch(r"[1-9][0-9]*", topic_id)
            or not narrative.strip()
            or topic_id in seen
        ):
            issues.append({"source": "topics", "position": position, "reason": "invalid/duplicate"})
            continue
        seen.add(topic_id)
        topics.append(
            {
                "topic_id": topic_id,
                "case_id": f"trec-ct-2022:{topic_id}",
                "text": narrative,
                "synthetic": True,
                "synthetic_provenance": SOURCE_PAGE,
                "source_task_attribute": root.get("task"),
                "source_warning": "known_2022_file_with_2021_header" if legacy_header else None,
                "source_locator": f"/topics/topic[@number='{topic_id}']",
            }
        )
    if not topics and not issues:
        issues.append({"source": "topics", "reason": "empty collection"})
    if issues:
        raise SourceValidationError(issues)
    return topics


def load_qrels(raw: bytes, topic_ids: set[str]) -> list[dict]:
    """Validate labels and joins; duplicate pairs are errors, including identical duplicates."""
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise SourceValidationError([{"source": "qrels", "reason": "invalid UTF-8"}]) from exc
    rows, issues, seen = [], [], set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        parts = line.split()
        reason = None
        if len(parts) != 4:
            reason = "expected four columns"
        else:
            topic_id, iteration, trial_id, grade = parts
            if topic_id not in topic_ids:
                reason = "unknown topic"
            elif iteration != "0" or not NCT_ID.fullmatch(trial_id) or grade not in {"0", "1", "2"}:
                reason = "invalid iteration, NCT ID, or label"
            elif (topic_id, trial_id) in seen:
                reason = "duplicate topic/trial judgment"
        if reason:
            issues.append({"source": "qrels", "line": line_number, "reason": reason})
            continue
        seen.add((topic_id, trial_id))
        rows.append(
            {
                "topic_id": topic_id,
                "trial_id": trial_id,
                "grade": int(grade),
                "benchmark_label": LABELS[int(grade)],
                "source_line": line_number,
            }
        )
    if not rows and not issues:
        issues.append({"source": "qrels", "reason": "empty collection"})
    if issues:
        raise SourceValidationError(issues)
    return rows


def select_trial_ids(qrels: list[dict], limit: int, seed: str) -> list[str]:
    """Stable hash-ranked unique IDs; independent of input order and Python RNG versions."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    ids = {row["trial_id"] for row in qrels}
    if len(ids) < limit:
        raise ValueError("requested sample exceeds the unique judged trial IDs")
    return sorted(
        ids,
        key=lambda trial_id: (hashlib.sha256(f"{seed}:{trial_id}".encode()).hexdigest(), trial_id),
    )[:limit]
