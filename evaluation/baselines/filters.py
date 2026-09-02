"""Conservative age/sex compatibility filters for synthetic benchmark topics."""

from __future__ import annotations

import re

AGE_PATTERN = re.compile(
    r"\b(\d{1,3}(?:\.\d+)?)\s*[- ]?(year|month|week|day)s?\s*[- ]?old\b",
    re.IGNORECASE,
)
COMPACT_PATTERN = re.compile(r"\b(\d{1,3})([MF])\b")
SEX_PATTERNS = {
    "Female": re.compile(r"\b(female|woman|girl|lady)\b", re.IGNORECASE),
    "Male": re.compile(r"\b(male|man|boy|gentleman)\b", re.IGNORECASE),
}
UNIT_DAYS = {"day": 1.0, "week": 7.0, "month": 30.436875, "year": 365.2425}
TRIAL_AGE = re.compile(
    r"^(\d+(?:\.\d+)?)\s+(Minute|Minutes|Day|Days|Week|Weeks|Month|Months|Year|Years)$"
)


def extract_topic_demographics(text: str) -> dict[str, object | None]:
    # TREC topics introduce the synthetic patient at the start. Restrict sex
    # detection to that presentation so later relatives or clinical examples
    # cannot create a false patient-sex match.
    presentation = text[:240]
    age_days = None
    age_source = None
    match = AGE_PATTERN.search(presentation)
    if match:
        age_days = float(match.group(1)) * UNIT_DAYS[match.group(2).lower()]
        age_source = match.group(0)
    compact = COMPACT_PATTERN.search(presentation)
    if age_days is None and compact:
        age_days = float(compact.group(1)) * UNIT_DAYS["year"]
        age_source = compact.group(0)
    sexes = [sex for sex, pattern in SEX_PATTERNS.items() if pattern.search(presentation)]
    if compact:
        compact_sex = "Female" if compact.group(2).upper() == "F" else "Male"
        if compact_sex not in sexes:
            sexes.append(compact_sex)
    return {
        "age_days": age_days,
        "age_source": age_source,
        "sex": sexes[0] if len(sexes) == 1 else None,
        "sex_ambiguous": len(sexes) > 1,
        "extractor_version": "synthetic-topic-demographics-v1",
    }


def trial_age_days(value: str | None) -> float | None:
    if not value:
        return None
    match = TRIAL_AGE.fullmatch(value.strip())
    if not match:
        return None
    quantity = float(match.group(1))
    unit = match.group(2).lower().rstrip("s")
    if unit == "minute":
        return quantity / 1440
    return quantity * UNIT_DAYS[unit]


def not_deterministically_incompatible(
    topic: dict[str, object | None], trial: dict[str, str | None]
) -> bool:
    """Keep unknowns; remove only explicit age or sex contradictions."""
    topic_age = topic.get("age_days")
    if isinstance(topic_age, int | float):
        minimum = trial_age_days(trial.get("minimum_age"))
        maximum = trial_age_days(trial.get("maximum_age"))
        if minimum is not None and topic_age < minimum:
            return False
        if maximum is not None and topic_age > maximum:
            return False
    topic_sex = topic.get("sex")
    trial_sex = (trial.get("sex") or "").strip().lower()
    return not (
        topic_sex
        and trial_sex
        and trial_sex not in {"all", "both"}
        and str(topic_sex).lower() != trial_sex
    )
