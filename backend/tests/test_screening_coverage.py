"""Whole-predicate boundaries and abstention regressions on invented cases only."""

from pathlib import Path

import pytest

from backend.app.services.eligibility.age import whole_age
from backend.app.services.eligibility.rules import validate_assessment, verify
from backend.app.services.patient_extraction.extractor import extract_profile
from evaluation.screening import evaluate_fixture
from evaluation.screening_coverage import compare
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import load_pairs

FIXTURE = Path("evaluation/data/fixtures/screening_coverage.json")


@pytest.mark.parametrize(
    "row,case,source",
    load_pairs(FIXTURE),
    ids=lambda x: x.get("id") if isinstance(x, dict) else None,
)
def test_extended_authored_contracts(row, case, source):
    result = verify(extract_profile(case), parse_eligibility(source))
    assert [c.outcome for c in result.criteria] == row["expected"]
    assert result.status == row["status"]
    assert validate_assessment(result) == result
    for criterion in result.criteria:
        if criterion.outcome != "unknown":
            assert criterion.fact_ids
            assert all(
                f.experiencer == "patient" and f.temporality == "current"
                for f in result.profile.facts
                if f.fact_id in criterion.fact_ids
            )


@pytest.mark.parametrize(
    "text",
    [
        "Age 18 years or older unless waived",
        "Age 18 years or older with asthma",
        "Age 18 years or older at screening",
        "Age 18 years or older or consent",
        "Not age >18 years",
        "Age >18 years per protocol",
        "Age 3 to <9 years, except controls",
        "Age >9 to <3 years",
        "Age >9 to <9 years",
        "Age 18 to 65 years and consent",
        "Age 18 years old if possible",
        ">18 years",
        "<6 months",
        "Age >=18",
        "Age -1 to 9 years",
        "Age 18 years or older..",
    ],
)
def test_age_grammar_never_accepts_a_partial_clause(text):
    assert whole_age(text) is None


@pytest.mark.parametrize(
    "text,value,expected",
    [
        ("Ages 3 to <9 years", 3, True),
        ("Ages 3 to <9 years", 9, False),
        ("Age >3 to <=9 years", 3, False),
        ("Age >3 to <=9 years", 9, True),
        ("Age 18 years or older", 18, True),
        ("Age 18 years and younger", 18, True),
        (">60 years of age", 60, False),
        ("<60 years of age", 60, False),
        ("Adults above 18 years,", 18, False),
        ("Child under 32 months old", 32, False),
        ("Age ≥18 and ≤65 years", 65, True),
        ("Age >18 and <65 years", 65, False),
    ],
)
def test_open_and_closed_age_bounds(text, value, expected):
    assert whole_age(text).accepts(value) is expected


@pytest.mark.parametrize(
    "text",
    [
        "Ages 3 to <9 years..",
        "Ages 3 to <9 years with asthma",
        "Age >=18 years unless waived",
        "Age 18 years or older if consented",
        "Ages 3 to <9 years at screening",
    ],
)
def test_unsupported_age_text_stays_unknown_through_the_complete_verifier(text):
    _, case, source = load_pairs(FIXTURE)[0]
    parsed = parse_eligibility(source.model_copy(update={"text": "Inclusion Criteria:\n- " + text}))
    assessment = verify(extract_profile(case), parsed)
    assert assessment.criteria[0].outcome == "unknown"


@pytest.mark.parametrize(
    "patient",
    [
        "40-year-old man. Platelets -1 x10^9/L.",
        "40-year-old man. Platelets 150 x10^9/L unless repeated.",
        "40-year-old man. Platelets 150 x10^9/L per minute.",
        "40-year-old man. Planned platelets 150 x10^9/L.",
        "40-year-old man. His spouse has platelets 150 x10^9/L.",
    ],
)
def test_unsafe_platelet_contexts_remain_unknown(patient):
    _, case, source = next(
        r for r in load_pairs(FIXTURE) if r[0]["id"] == "coverage-platelets-pass"
    )
    assessment = verify(
        extract_profile(case.model_copy(update={"text": patient})), parse_eligibility(source)
    )
    assert assessment.criteria[0].outcome == "unknown"


def test_coverage_report_detects_tampered_output_and_refuses_overwrite(tmp_path):
    from evaluation.screening_coverage import VERSION, evaluate, validate_report
    from pipelines.connectors.snapshots import write_json
    from pipelines.embeddings import file_record

    _, case, source = load_pairs(FIXTURE)[0]
    a = verify(extract_profile(case), parse_eligibility(source))
    baseline = tmp_path / "before"
    baseline.mkdir()
    write_json(baseline / "assessments.json", [a.model_dump(mode="json")])
    write_json(
        baseline / "manifest.json",
        {"version": VERSION, "files": [file_record(baseline / "assessments.json", baseline)]},
    )
    output = tmp_path / "after"
    evaluate(baseline, output)
    assert validate_report(baseline, output)["status"] == "verified"
    with pytest.raises(FileExistsError):
        evaluate(baseline, output)
    (output / "changed-decisions.json").write_text("altered")
    with pytest.raises(ValueError, match="checksum"):
        validate_report(baseline, output)


def test_frozen_fixture_labels_and_old_supported_outcomes_remain_intact():
    metrics = evaluate_fixture()
    assert (metrics["pairs"], metrics["exact_pairs"], metrics["criterion_count"]) == (34, 34, 41)
    assert metrics["supported_outcome_precision"] == 1.0


def test_paired_coverage_audit_rejects_unaligned_sources():
    _, case, source = load_pairs(FIXTURE)[0]
    a = verify(extract_profile(case), parse_eligibility(source))
    assert compare([a], [a])["changed_previous_supported_outcomes"] == 0
    changed = a.model_copy(
        update={
            "profile": a.profile.model_copy(
                update={"case": case.model_copy(update={"case_id": "different"})}
            )
        }
    )
    with pytest.raises(ValueError, match="identity"):
        compare([a], [changed])
    with pytest.raises(ValueError, match="length"):
        compare([a], [])
