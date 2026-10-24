"""Authored review-order contracts and safety failures, not clinical-accuracy labels."""

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.review import ReviewPlan
from backend.app.services.eligibility.grouped import verify_grouped
from backend.app.services.eligibility.review import prioritise_missing, validate_review
from backend.app.services.eligibility.rules import verify
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import load_pairs

FIXTURE = Path("evaluation/data/fixtures/missing_information_review.json")


def assessment(case, source):
    return verify(extract_profile(case), parse_eligibility(source))


@pytest.mark.parametrize(
    "row,case,source", load_pairs(FIXTURE), ids=lambda r: r["id"] if isinstance(r, dict) else None
)
def test_authored_review_contracts(row, case, source):
    a = assessment(case, source)
    before = a.model_dump(mode="json")
    grouped = {source.trial_id: verify_grouped(a.profile, a.parsed)} if row["grouped"] else None
    plan = prioritise_missing([a], grouped=grouped)
    assert [[i.fact_name, i.requested_unit] for i in plan.items] == row["review_keys"]
    assert [i.criterion_count for i in plan.items] == row["review_criteria"]
    assert len(plan.interpretation_reviews) == row["interpretations"]
    assert len(plan.settled_branch_reviews) == row["settled"]
    assert plan.basis[0].status == row["status"]
    assert validate_review(plan, [a], grouped=grouped) == plan
    assert a.model_dump(mode="json") == before
    for item in plan.items:
        assert item.unblocked_trial_count == (0 if plan.basis[0].blocking_ids else 1)
        assert "do not infer a value or order a test" in item.prompt
    for ref in (
        [r for i in plan.items for r in i.references]
        + list(plan.interpretation_reviews)
        + list(plan.settled_branch_reviews)
    ):
        assert source.text[ref.evidence.start : ref.evidence.end] == ref.evidence.text
        assert set(ref.criterion_ids) <= {c.criterion_id for c in a.criteria}


def test_multi_trial_reuse_and_known_blockers_determine_order_without_clinical_weights():
    _, case, source = load_pairs(FIXTURE)[0]
    # Creatinine occurs in two unblocked trials; age occurs in two criteria of one.
    first = assessment(case, source)
    second = assessment(
        case,
        source.model_copy(
            update={
                "trial_id": "NCT99999002",
                "text": "Inclusion Criteria:\n- Creatinine <= 1.5 mg/dL.",
            }
        ),
    )
    plan = prioritise_missing([second, first])
    assert [i.fact_name for i in plan.items] == ["creatinine", "age"]
    assert plan.items[0].unblocked_trial_count == plan.items[0].trial_count == 2
    assert plan == prioritise_missing([first, second])
    blocked_case = case.model_copy(update={"text": "17-year-old man."})
    blocked = assessment(
        blocked_case,
        source.model_copy(
            update={
                "text": "Inclusion Criteria:\n- Age >= 18 years.\n- Hemoglobin >= 10 g/dL.",
            }
        ),
    )
    other = assessment(
        blocked_case,
        source.model_copy(
            update={
                "trial_id": "NCT99999003",
                "text": "Inclusion Criteria:\n- Creatinine <= 1.5 mg/dL.",
            }
        ),
    )
    plan = prioritise_missing([blocked, other])
    assert [i.fact_name for i in plan.items] == ["creatinine", "hemoglobin"]
    assert plan.items[1].unblocked_trial_count == 0 and plan.basis[0].blocking_ids


@pytest.mark.parametrize(
    "damage",
    [
        "case",
        "duplicate",
        "empty",
        "grouped",
        "null_grouped",
        "changed_grouped",
        "source",
        "outcome",
    ],
)
def test_review_rejects_incompatible_or_unreproducible_assessments(damage):
    _, case, source = load_pairs(FIXTURE)[0]
    a = assessment(case, source)
    inputs, options = [a], {}
    if damage == "case":
        other = assessment(
            case.model_copy(update={"text": "40-year-old man."}),
            source.model_copy(update={"trial_id": "NCT99999002"}),
        )
        inputs = [a, other]
    elif damage == "duplicate":
        inputs = [a, a]
    elif damage == "empty":
        inputs = []
    elif damage == "grouped":
        options = {"grouped": {}}
    elif damage in {"null_grouped", "changed_grouped"}:
        g = verify_grouped(a.profile, a.parsed)
        g["status"] = "potential_match"
        options = {"grouped": {source.trial_id: None if damage == "null_grouped" else g}}
    elif damage == "source":
        inputs = [a.model_copy(update={"assessment_id": "0" * 64})]
    else:
        changed = (a.criteria[0].model_copy(update={"outcome": "satisfied"}), *a.criteria[1:])
        inputs = [a.model_copy(update={"criteria": changed})]
    with pytest.raises(ValueError):
        prioritise_missing(inputs, **options)


def test_tampered_priority_counts_order_and_dispositions_fail_validation():
    _, case, source = load_pairs(FIXTURE)[0]
    a = assessment(case, source)
    plan = prioritise_missing([a])
    data = plan.model_dump()
    data["items"][0]["criterion_count"] += 1
    with pytest.raises(ValidationError):
        ReviewPlan.model_validate(data)
    data = copy.deepcopy(plan.model_dump())
    data["interpretation_reviews"] = [data["items"][0]["references"][0]]
    with pytest.raises(ValidationError):
        ReviewPlan.model_validate(data)
    reversed_plan = plan.model_copy(update={"items": tuple(reversed(plan.items))})
    with pytest.raises(ValueError):
        validate_review(reversed_plan, [a])
