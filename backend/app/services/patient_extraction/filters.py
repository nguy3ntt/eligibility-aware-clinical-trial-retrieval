"""Evidence-backed age/sex filters; all other extracted facts remain non-filtering."""

from backend.app.repositories.qdrant import compatibility_filter
from backend.app.schemas.patient import PatientProfile
from backend.app.services.patient_extraction.extractor import extract_profile

VERSION = "profile-demographic-filter-v1"
# Preserve the historical retrieval comparison convention; no calendar-age precision claim.
UNIT_DAYS = {"day": 1.0, "week": 7.0, "month": 30.436875, "year": 365.2425}


def build_filter_plan(profile: PatientProfile) -> dict:
    # Validate semantic values as well as source spans: do not trust edited/older profiles.
    verified = extract_profile(profile.case)
    if profile.model_dump() != verified.model_dump():
        raise ValueError(
            "profile differs from current deterministic extraction; re-extract the case"
        )
    demographics, decisions = {}, []
    for kind in ("age", "sex"):
        mentions = [f for f in profile.facts if f.kind == kind and f.experiencer == "patient"]
        usable = [
            f
            for f in mentions
            if f.assertion == "present"
            and f.certainty == "asserted"
            and f.temporality == "current"
            and f.operator == "eq"
        ]
        blocked = any(f.temporality in {"current", "unknown"} and f not in usable for f in mentions)
        if kind == "age" and any(i.code == "invalid_age" for i in profile.issues):
            blocked = True
        if kind == "sex" and any(i.code == "sex_requires_review" for i in profile.issues):
            blocked = True
        values = {float(f.value) * UNIT_DAYS[f.unit] if kind == "age" else f.value for f in usable}
        accepted = bool(usable) and len(values) == 1 and not blocked
        if accepted:
            demographics["age_days" if kind == "age" else "sex"] = next(iter(values))
        decisions.append(
            {
                "kind": kind,
                "action": "apply" if accepted else "abstain",
                "reason": "consistent_current_patient_evidence"
                if accepted
                else "missing_uncertain_conflicting_or_unanchored",
                "fact_ids": [f.fact_id for f in mentions],
            }
        )
    return {
        "version": VERSION,
        "demographics": demographics,
        "qdrant_filter": compatibility_filter(demographics),
        "decisions": decisions,
        "non_filtering_fact_ids": [
            f.fact_id for f in profile.facts if f.kind not in {"age", "sex"}
        ],
        "age_unit_days": UNIT_DAYS,
        "eligibility_assessment": "not_performed",
        "notice": "Potential matches only. Unknown facts require professional review.",
    }
