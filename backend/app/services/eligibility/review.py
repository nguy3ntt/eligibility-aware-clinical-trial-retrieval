"""Order existing fact gaps by reuse; never estimate clinical urgency or change decisions."""

import json
import re
from pathlib import Path

from backend.app.schemas.patient import text_hash
from backend.app.schemas.review import ReviewBasis, ReviewItem, ReviewPlan, ReviewReference
from backend.app.services.eligibility.age import whole_age
from backend.app.services.eligibility.grouped import validate_grouped
from backend.app.services.eligibility.rules import GATE, validate_assessment
from pipelines.criteria.parser import numeric_constraints

VERSION = "missing-information-review-v1"
FACT_REASONS = {
    "missing_uncertain_or_unanchored_patient_evidence",
    "conflicting_patient_evidence",
    "units_differ_no_conversion",
}


def fingerprint():
    schema = Path(__file__).resolve().parents[2] / "schemas" / "review.py"
    return text_hash(
        Path(__file__).read_text(encoding="utf-8") + schema.read_text(encoding="utf-8")
    )


def digest(value):
    return text_hash(json.dumps(value, sort_keys=True, separators=(",", ":")))


def fact_key(ref):
    """Accept only the verifier's explicit fact-gap vocabulary, never criterion type tags."""
    if ref.reason not in FACT_REASONS or len(ref.missing_information) != 1:
        return None
    text = ref.missing_information[0]
    match = re.fullmatch(
        r"reliable current patient (age|sex|hemoglobin|hba1c|creatinine|bmi|platelets)", text
    )
    if match:
        name = match[1]
        if name == "sex":
            return name, None
        wording = ref.evidence.text.strip().rstrip(".").strip()
        gate = GATE.fullmatch(wording)
        if name == "age" and (age := whole_age(gate[2] if gate else wording)) is not None:
            return name, age.unit
        constraints, _ = numeric_constraints(ref.evidence.text, 0, len(ref.evidence.text))
        units = {c.unit for c in constraints if c.name == name}
        return (name, next(iter(units))) if len(units) == 1 else None
    # Units already come from a complete recognised predicate in the verified assessment.
    match = re.fullmatch(r"(age|hemoglobin|hba1c|creatinine|bmi|platelets) in (.+)", text)
    if match and ref.reason == "units_differ_no_conversion":
        return match[1], match[2]
    return None


def reference(assessment, decision, *, node=False):
    ids = tuple(decision["criterion_ids"]) if node else (decision.criterion_id,)
    node_id = decision["node_id"] if node else None
    return ReviewReference(
        reference_id=digest([assessment.assessment_id, node_id, ids]),
        assessment_id=assessment.assessment_id,
        trial_id=assessment.parsed.source.trial_id,
        criterion_ids=ids,
        node_id=node_id,
        evidence=decision["evidence"] if node else decision.evidence,
        fact_ids=tuple(decision["fact_ids"]) if node else decision.fact_ids,
        reason=decision["reason"] if node else decision.reason,
        missing_information=tuple(decision["missing_information"])
        if node
        else decision.missing_information,
    )


def grouped_leaves(root, active=True):
    """An unknown below a known parent cannot change that already-settled expression."""
    active = active and root["truth"] == "unknown"
    if root["children"]:
        for child in root["children"]:
            yield from grouped_leaves(child, active)
    elif root["truth"] == "unknown":
        yield root, active


def prioritise_missing(assessments, *, grouped=None):
    """Pure review artifact for 1..10 same-case trials, with exhaustive unknown disposition."""
    assessments = sorted(assessments, key=lambda a: a.parsed.source.trial_id)
    if not 1 <= len(assessments) <= 10:
        raise ValueError("review requires 1..10 source assessments")
    case = assessments[0].profile.case
    if len({a.parsed.source.trial_id for a in assessments}) != len(assessments):
        raise ValueError("duplicate trial assessment")
    for a in assessments:
        if a.profile.case != case:
            raise ValueError("review cannot mix synthetic cases or case versions")
        validate_assessment(a)
    if grouped is not None and set(grouped) != {a.parsed.source.trial_id for a in assessments}:
        raise ValueError("grouped review must supply exactly the source trial set")
    bases, candidates, interpretation, settled = [], {}, [], []
    for a in assessments:
        trial_id = a.parsed.source.trial_id
        g = grouped[trial_id] if grouped is not None else None
        if grouped is not None and not isinstance(g, dict):
            raise ValueError("grouped review requires complete source packets")
        if g is not None:
            validate_grouped(g, a.profile, a.parsed)
        bases.append(
            ReviewBasis(
                assessment_id=a.assessment_id,
                trial_id=trial_id,
                source_sha256=a.parsed.source.source_sha256,
                source_text_sha256=a.parsed.text_sha256,
                status=g["status"] if g else a.status,
                blocking_ids=tuple(g["blocking_node_ids"]) if g else a.blocking_criterion_ids,
                grouped_sha256=digest(g) if g else None,
                scope_review_required=g["scope_review_required"] if g else False,
            )
        )
        if g and not g["scope_review_required"]:
            refs = [
                (reference(a, n, node=True), active)
                for section in g["sections"]
                for n, active in grouped_leaves(section["root"])
            ]
        else:
            refs = [(reference(a, c), True) for c in a.criteria if c.outcome == "unknown"]
        if (
            sum(len(v) for v in candidates.values())
            + len(interpretation)
            + len(settled)
            + len(refs)
            > 4096
        ):
            raise ValueError("review reference bound exceeded")
        for ref, active in refs:
            if not active:
                settled.append(ref)
            elif g and g["scope_review_required"]:
                interpretation.append(ref)
            elif (key := fact_key(ref)) is not None:
                candidates.setdefault(key, []).append(ref)
            else:
                interpretation.append(ref)
    basis = {b.trial_id: b for b in bases}
    items = []
    for (name, unit), refs in candidates.items():
        tids = {r.trial_id for r in refs}
        items.append(
            ReviewItem(
                item_id=digest([case.case_id, name, unit]),
                rank=1,
                fact_name=name,
                requested_unit=unit,
                prompt=f"Review the synthetic record for reliable current patient {name}"
                + (f" in {unit}" if unit else "")
                + ". Reconcile uncertain or conflicting evidence; "
                "do not infer a value or order a test.",
                unblocked_trial_count=sum(not basis[t].blocking_ids for t in tids),
                trial_count=len(tids),
                criterion_count=len({(r.trial_id, c) for r in refs for c in r.criterion_ids}),
                references=tuple(
                    sorted(refs, key=lambda r: (r.trial_id, r.evidence.start, r.reference_id))
                ),
            )
        )
    items.sort(
        key=lambda i: (
            -i.unblocked_trial_count,
            -i.criterion_count,
            -i.trial_count,
            i.fact_name,
            i.requested_unit or "",
        )
    )
    body = {
        "implementation_sha256": fingerprint(),
        "case_id": case.case_id,
        "case_text_sha256": text_hash(case.text),
        "mode": "grouped" if grouped is not None else "ordinary",
        "basis": bases,
        "items": [i.model_copy(update={"rank": rank}) for rank, i in enumerate(items, 1)],
        "interpretation_reviews": tuple(interpretation),
        "settled_branch_reviews": tuple(settled),
    }
    provisional = ReviewPlan(plan_id="0" * 64, **body)
    payload = provisional.model_dump(mode="json", exclude={"plan_id"})
    return ReviewPlan(plan_id=digest(payload), **body)


def validate_review(plan, assessments, *, grouped=None):
    validated = ReviewPlan.model_validate(plan.model_dump())
    if prioritise_missing(assessments, grouped=grouped) != validated:
        raise ValueError("review plan differs from reproducible source ordering")
    return validated
