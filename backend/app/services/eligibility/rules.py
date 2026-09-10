"""Conservative whole-clause checks with no unit conversion or clinical inference."""

import json
import re
from pathlib import Path

from backend.app.schemas.eligibility import CriterionAssessment, TrialAssessment
from backend.app.schemas.patient import text_hash
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.criteria.parser import parse_eligibility

VERSION = "bounded-screening-rules-v1"
CONTEXT = re.compile(
    r"\b(?:or|if|unless|except\w*|provided|however|either|any of|one of|waiv\w*)\b", re.I
)
GATE = re.compile(r"For (female|male) participants:\s*(.+)", re.I | re.S)
SEX = re.compile(r"(?:Sex:\s*)?(male|female)(?: participants)?", re.I)


def verifier_hash():
    return text_hash(Path(__file__).read_text(encoding="utf-8"))


def usable_facts(profile, kind, name=None):
    mentions = [f for f in profile.facts if f.kind == kind and (name is None or f.name == name)]
    patient = [f for f in mentions if f.experiencer == "patient"]
    usable = [
        f
        for f in patient
        if f.temporality == "current"
        and f.assertion == "present"
        and f.certainty == "asserted"
        and f.operator == "eq"
    ]
    blocking = any(f.temporality in {"unknown", "current"} and f not in usable for f in patient)
    issue_code = {
        "age": "invalid_age",
        "sex": "sex_requires_review",
        "measurement": "unsupported_measurement",
    }[kind]
    blocking |= any(i.code == issue_code for i in profile.issues)
    if kind == "measurement":
        blocking |= any(
            re.match(r"[/^\w]|\s+per\b", profile.case.text[f.evidence.end :], re.I)
            or re.search(
                r"\b(?:if|unless|except|estimated|example|hypothetical)\b", f.context.text, re.I
            )
            for f in usable
        )
    if blocking or not usable:
        return None, mentions, "missing_uncertain_or_unanchored_patient_evidence"
    if len({(f.value, f.unit) for f in usable}) != 1:
        return None, mentions, "conflicting_patient_evidence"
    return usable[0], mentions, None


def check_predicate(value, constraint):
    bound = constraint.value
    return {
        "eq": lambda: value == bound,
        "ge": lambda: value >= bound,
        "gt": lambda: value > bound,
        "le": lambda: value <= bound,
        "lt": lambda: value < bound,
        "range": lambda: bound <= value <= constraint.upper,
    }[constraint.operator]()


def evaluate_criterion(profile, parsed, criterion):
    fact_ids = []

    def result(outcome, reason, rule="abstain-v1", missing=()):
        return CriterionAssessment(
            criterion_id=criterion.criterion_id,
            outcome=outcome,
            reason=reason,
            rule_id=rule,
            fact_ids=tuple(dict.fromkeys(fact_ids)),
            evidence=criterion.evidence,
            missing_information=missing,
        )

    # Unknown preambles may govern every subsequent section. Cross-clause alternatives
    # and nested groups cannot safely be treated as independent blocking requirements.
    if any(c.section == "unknown" for c in parsed.criteria):
        return result("unknown", "unknown_section_or_preamble")
    peers = [c for c in parsed.criteria if c.section_ordinal == criterion.section_ordinal]
    if CONTEXT.search(parsed.source.text) or any(
        c.parent_id or "embedded_heading_requires_review" in c.review_reasons for c in peers
    ):
        return result("unknown", "shared_or_nested_context_requires_review")
    wording = criterion.evidence.text.strip().rstrip(".").strip()
    gate = GATE.fullmatch(wording)
    if gate:
        wording = gate[2].strip().rstrip(".").strip()
    numeric = criterion.constraints[0] if len(criterion.constraints) == 1 else None
    numeric_complete = numeric is not None and wording == numeric.evidence.text.strip()
    sex = SEX.fullmatch(wording)
    if not numeric_complete and not sex:
        return result(
            "unknown", "unsupported_or_incomplete_predicate", missing=("criterion interpretation",)
        )
    if gate:
        subject, mentions, issue = usable_facts(profile, "sex")
        fact_ids.extend(f.fact_id for f in mentions)
        if issue:
            return result("unknown", issue, missing=("reliable current patient sex",))
        if subject.value.lower() != gate[1].lower():
            return result("not_applicable", "explicit_sex_condition_false", "sex-applicability-v1")
    kind = "sex" if sex else "age" if numeric.name == "age" else "measurement"
    fact, mentions, issue = usable_facts(profile, kind, None if sex else numeric.name)
    fact_ids.extend(f.fact_id for f in mentions)
    if issue:
        return result(
            "unknown", issue, missing=(f"reliable current patient {kind if sex else numeric.name}",)
        )
    if numeric_complete and fact.unit != numeric.unit:
        return result(
            "unknown", "units_differ_no_conversion", missing=(f"{numeric.name} in {numeric.unit}",)
        )
    truth = fact.value.lower() == sex[1].lower() if sex else check_predicate(fact.value, numeric)
    satisfied = truth if criterion.section == "inclusion" else not truth
    return result(
        "satisfied" if satisfied else "violated",
        "inclusion_predicate_" + str(truth).lower()
        if criterion.section == "inclusion"
        else "exclusion_predicate_" + str(truth).lower(),
        "exact-sex-v1" if sex else "same-unit-numeric-v1",
    )


def verify(profile, parsed):
    if extract_profile(profile.case) != profile:
        raise ValueError("profile differs from current source extraction")
    if parse_eligibility(parsed.source) != parsed:
        raise ValueError("criteria differ from current source parsing")
    assessments = tuple(evaluate_criterion(profile, parsed, c) for c in parsed.criteria)
    blocking = tuple(c.criterion_id for c in assessments if c.outcome == "violated")
    unknown = tuple(c.criterion_id for c in assessments if c.outcome == "unknown")
    status = (
        "likely_exclusion"
        if blocking
        else "insufficient_information"
        if (unknown or not any(c.outcome == "satisfied" for c in assessments))
        else "potential_match"
    )
    return TrialAssessment(
        assessment_id=text_hash(
            json.dumps(
                [profile.model_dump(mode="json"), parsed.model_dump(mode="json"), verifier_hash()],
                sort_keys=True,
            )
        ),
        verifier_version=VERSION,
        verifier_sha256=verifier_hash(),
        profile=profile,
        parsed=parsed,
        criteria=assessments,
        status=status,
        blocking_criterion_ids=blocking,
        unknown_criterion_ids=unknown,
        missing_information=tuple(
            dict.fromkeys(item for c in assessments for item in c.missing_information)
        ),
    )


def validate_assessment(assessment):
    """Reproduce stored decisions before a future consumer trusts them."""
    validated = TrialAssessment.model_validate(assessment.model_dump())
    if verify(validated.profile, validated.parsed) != validated:
        raise ValueError("stored screening differs from reproducible source verification")
    return validated
