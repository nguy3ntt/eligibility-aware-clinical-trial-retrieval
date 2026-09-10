"""Authored screening outcomes, source tampering, unsupported context and CLI contracts."""

import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.app.schemas.eligibility import TrialAssessment
from backend.app.services.eligibility.rules import verify
from backend.app.services.patient_extraction.extractor import extract_profile
from evaluation.screening import evaluate_fixture
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import load_pairs


@pytest.mark.parametrize(
    "row,case,source",
    load_pairs(),
    ids=lambda item: item.get("id") if isinstance(item, dict) else None,
)
def test_authored_criterion_and_trial_labels(row, case, source):
    result = verify(extract_profile(case), parse_eligibility(source))
    assert [c.outcome for c in result.criteria] == row["expected"]
    assert result.status == row["status"]
    assert TrialAssessment.model_validate_json(result.model_dump_json()) == result
    assert verify(extract_profile(case), parse_eligibility(source)) == result


def example(patient, criterion, section="Inclusion"):
    _, case, source = load_pairs()[0]
    return extract_profile(case.model_copy(update={"text": patient})), parse_eligibility(
        source.model_copy(update={"text": f"{section} Criteria:\n- {criterion}"})
    )


@pytest.mark.parametrize(
    "criterion",
    [
        "Age >= 18 years unless waived.",
        "Age >= 18 years or consent.",
        "Age >= 18 years; Hemoglobin >= 10 g/dL unless waived.",
        "Not age >= 18 years.",
        "Age >= 18 years on enrollment day.",
    ],
)
def test_partial_numeric_match_never_becomes_a_blocker(criterion):
    assert verify(*example("17-year-old man.", criterion)).status == "insufficient_information"


@pytest.mark.parametrize(
    "patient",
    [
        "40-year-old man. Hemoglobin 12 g/dL/min.",
        "40-year-old man. Hemoglobin 12 g/dL if the test is repeated.",
        "40-year-old man. Hemoglobin -5 g/dL. Hemoglobin 12 g/dL.",
        "40-year-old man. Hemoglobin 12 g/dL per minute.",
    ],
)
def test_unsafe_or_conditional_measurement_does_not_pass(patient):
    result = verify(*example(patient, "Hemoglobin >= 10 g/dL."))
    assert result.criteria[0].outcome == "unknown"


@pytest.mark.parametrize(
    "operator,bound,expected",
    [
        (">", 10, "violated"),
        (">=", 10, "satisfied"),
        ("<", 10, "violated"),
        ("<=", 10, "satisfied"),
        ("=", 10, "satisfied"),
        ("=", 11, "violated"),
    ],
)
def test_numeric_open_closed_boundaries(operator, bound, expected):
    result = verify(
        *example("40-year-old man. Hemoglobin 10 g/dL.", f"Hemoglobin {operator} {bound} g/dL.")
    )
    assert result.criteria[0].outcome == expected


def test_input_values_cannot_be_forged_even_when_spans_are_unchanged():
    profile, parsed = example("17-year-old man.", "Age >= 18 years.")
    facts = (profile.facts[0].model_copy(update={"value": 40.0}), *profile.facts[1:])
    with pytest.raises(ValueError, match="profile differs"):
        verify(profile.model_copy(update={"facts": facts}), parsed)
    criterion = parsed.criteria[0]
    constraint = criterion.constraints[0].model_copy(update={"value": 1.0})
    changed = criterion.model_copy(update={"constraints": (constraint,)})
    with pytest.raises(ValueError, match="criteria differ"):
        verify(profile, parsed.model_copy(update={"criteria": (changed,)}))
    invalid = profile.case.model_copy(update={"synthetic": False})
    with pytest.raises(ValidationError):
        verify(profile.model_copy(update={"case": invalid}), parsed)


def test_assessment_rejects_lost_evidence_or_false_trial_summary():
    result = verify(*example("17-year-old man.", "Age >= 18 years."))
    data = json.loads(result.model_dump_json())
    data["criteria"][0]["fact_ids"] = ["not-a-fact"]
    with pytest.raises(ValueError):
        TrialAssessment.model_validate(data)
    data = json.loads(result.model_dump_json())
    data["status"] = "potential_match"
    with pytest.raises(ValueError):
        TrialAssessment.model_validate(data)


def test_foundation_screening_needs_no_optional_model_dependencies():
    script = (
        "import sys; "
        "sys.modules.update({k:None for k in ('torch','transformers','numpy','bm25s')}); "
        "from evaluation.screening import evaluate_fixture; "
        "assert evaluate_fixture()['exact_pairs']==34"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    metrics = evaluate_fixture()
    assert metrics["criterion_count"] == 41
    assert metrics["supported_outcome_precision"] == 1


def test_cli_no_model_default_and_invalid_selection():
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.screening", "--pair-id", "demo-exclusion"],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["semantic"] is None
    assert data["screening"]["status"] == "likely_exclusion"
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.screening", "--pair-id", "missing"],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1


def test_cli_refuses_existing_report_and_unsafe_output_id(tmp_path):
    directory = tmp_path / "evaluation/reports/existing"
    directory.mkdir(parents=True)
    sentinel = directory / "keep.txt"
    sentinel.write_text("keep")
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.screening", "--output-id", "existing"],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert b"fresh output ID" in result.stderr
    assert sentinel.read_text() == "keep"
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.screening", "--output-id", "../escape"],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 2


def test_shared_exception_in_another_section_cannot_leave_a_false_blocker():
    profile, parsed = example(
        "17-year-old man.", "Age >= 18 years.\nExclusion Criteria:\n- Exceptions may be approved."
    )
    result = verify(profile, parsed)
    assert all(c.outcome == "unknown" for c in result.criteria)
    assert not result.blocking_criterion_ids


def test_missing_information_summary_preserves_requirement():
    result = verify(*example("40-year-old man.", "Hemoglobin >= 10 g/dL."))
    assert result.missing_information == ("reliable current patient hemoglobin",)


def test_self_consistent_but_forged_saved_decision_fails_reproduction():
    from backend.app.services.eligibility.rules import validate_assessment

    result = verify(*example("17-year-old man.", "Age >= 18 years."))
    assert validate_assessment(result) == result
    changed = result.criteria[0].model_copy(update={"outcome": "satisfied"})
    forged = result.model_copy(
        update={"criteria": (changed,), "status": "potential_match", "blocking_criterion_ids": ()}
    )
    with pytest.raises(ValueError, match="reproducible"):
        validate_assessment(forged)
