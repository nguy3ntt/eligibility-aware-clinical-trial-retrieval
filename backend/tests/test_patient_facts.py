"""Evidence integrity, difficult context, abstention, and source failure contracts."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.patient import PatientProfile, SyntheticCase, text_hash
from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.patient_extraction.filters import build_filter_plan
from evaluation.patient_facts import DEFAULT_FIXTURE, evaluate_fixture
from pipelines.connectors.synthetic_cases import load_cases


def case(text):
    return SyntheticCase(
        case_id="invented-test",
        synthetic=True,
        text=text,
        source="invented-unit-test",
        source_sha256=text_hash(text),
        source_locator="/case",
    )


def test_hand_labelled_development_contracts():
    result = evaluate_fixture(DEFAULT_FIXTURE)
    assert result["cases"] == result["exact_cases"] == result["correct_filter_cases"] == 16
    assert result["fact_metrics"]["tp"] == 59
    assert result["fact_metrics"]["fp"] == result["fact_metrics"]["fn"] == 0


def test_reproducible_unicode_offsets_and_serialization():
    source = case("  A 38-year-old woman has asthma.\nCreatinine 90 µmol/L.")
    first = extract_profile(source)
    assert first == extract_profile(source)
    assert PatientProfile.model_validate_json(first.model_dump_json()) == first
    for fact in first.facts:
        assert source.text[fact.evidence.start : fact.evidence.end] == fact.evidence.text
        assert source.text[fact.context.start : fact.context.end] == fact.context.text
    changed = extract_profile(case(source.text + " "))
    assert not {f.fact_id for f in first.facts} & {f.fact_id for f in changed.facts}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A 70-year-old man has asthma.", {"age_days": 70 * 365.2425, "sex": "Male"}),
        ("His 70-year-old father has asthma.", {}),
        ("The patient was a 70-year-old man at diagnosis.", {}),
        ("The patient may be 70-year-old.", {}),
        ("The patient is 45-50-year-old.", {}),
        ("The patient is -7-year-old.", {}),
        ("The patient is 170-year-old.", {}),
        ("The patient reports a 70-year-old friend.", {}),
        ("A 40-year-old woman. Sex: male.", {"age_days": 40 * 365.2425}),
        ("A 40-year-old woman. Sex unknown.", {"age_days": 40 * 365.2425}),
        ("A 40-year-old man. The patient is 170-year-old.", {"sex": "Male"}),
        ("He has asthma.", {}),
    ],
)
def test_demographic_filter_abstention(text, expected):
    assert build_filter_plan(extract_profile(case(text)))["demographics"] == expected


@pytest.mark.parametrize(
    "text,name,assertion,temporal,experiencer",
    [
        ("No diabetes or asthma.", "asthma", "absent", "current", "patient"),
        ("Cannot rule out asthma.", "asthma", "uncertain", "current", "patient"),
        ("Asthma is suspected.", "asthma", "uncertain", "current", "patient"),
        ("No history of asthma.", "asthma", "absent", "historical", "patient"),
        ("He denies asthma, takes metformin.", "metformin", "present", "current", "patient"),
        (
            "His father denies asthma and takes metformin.",
            "metformin",
            "present",
            "current",
            "family",
        ),
        (
            "Her mother has asthma and the patient has diabetes.",
            "diabetes",
            "present",
            "current",
            "patient",
        ),
        ("Asthma resolved.", "asthma", "present", "historical", "patient"),
        ("Surgery is planned.", "surgery", "present", "planned", "patient"),
        ("He underwent surgery in 2020.", "surgery", "present", "historical", "patient"),
        ("Not only asthma but diabetes.", "asthma", "present", "current", "patient"),
    ],
)
def test_context_scope(text, name, assertion, temporal, experiencer):
    fact = next(f for f in extract_profile(case(text)).facts if f.name == name)
    assert (fact.assertion, fact.temporality, fact.experiencer) == (
        assertion,
        temporal,
        experiencer,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Creatinine 1.5",
        "Creatinine -1 mg/dL",
        "Creatinine 1e3 mg/dL",
        "Creatinine 1,5 mg/dL",
        "Creatinine 1-2 mg/dL",
        "BP 120/80",
    ],
)
def test_unsupported_numeric_inputs_remain_inspectable(text):
    profile = extract_profile(case(text))
    assert not any(f.kind == "measurement" for f in profile.facts)
    assert any(i.code == "unsupported_measurement" for i in profile.issues)


def test_no_symptom_diagnosis_or_missing_medication_inference():
    profile = extract_profile(case("Thirst, frequent urination, no medication list. Glucose high."))
    assert profile.facts == ()
    assert "condition" in profile.missing_categories and "medication" in profile.missing_categories
    assert len(profile.issues) >= 1
    assert build_filter_plan(profile)["qdrant_filter"] == {}


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_non_synthetic_flags_rejected(value):
    raw = case("Invented text.").model_dump()
    raw["synthetic"] = value
    with pytest.raises(ValidationError):
        SyntheticCase.model_validate(raw)


@pytest.mark.parametrize("text", ["", "   ", "a" * 20001])
def test_empty_or_oversized_inputs_rejected(text):
    with pytest.raises(ValidationError):
        case(text)


def test_edited_values_hashes_spans_and_missing_categories_rejected():
    profile = extract_profile(case("A 50-year-old man has asthma."))
    for change in ("hash", "span", "missing"):
        raw = profile.model_dump()
        if change == "hash":
            raw["narrative_sha256"] = "0" * 64
        elif change == "span":
            raw["facts"][0]["evidence"]["text"] = "X" * len(raw["facts"][0]["evidence"]["text"])
        else:
            raw["missing_categories"] = []
        with pytest.raises(ValidationError):
            PatientProfile.model_validate(raw)
    raw = profile.model_dump()
    raw["facts"][0]["value"] = 21
    edited = PatientProfile.model_validate(raw)
    with pytest.raises(ValueError, match="re-extract"):
        build_filter_plan(edited)
    assert all(d["fact_ids"] for d in build_filter_plan(profile)["decisions"])


def test_loader_retains_invalid_positions_and_rejects_duplicates(tmp_path):
    data = {
        "schema_version": "synthetic-cases-v1",
        "dataset_id": "test",
        "synthetic": True,
        "cases": [
            {"case_id": "one", "text": "Invented."},
            {"case_id": "one", "text": "Invented."},
            {"case_id": "two", "text": 3},
        ],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=r"positions \[1, 2\]"):
        load_cases(path)
    data["synthetic"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        load_cases(path)


def test_fixtures_require_no_optional_model_or_database():
    cases = load_cases(Path(DEFAULT_FIXTURE))
    assert len(cases) == 16
    for source in cases:
        result = build_filter_plan(extract_profile(source))
        assert result["eligibility_assessment"] == "not_performed"


def test_partners_children_and_explicit_patient_presentation():
    profile = extract_profile(
        case(
            "The patient is a 38-year-old woman. She has male partners. "
            "Her children are 9 years old."
        )
    )
    assert build_filter_plan(profile)["demographics"] == {
        "age_days": 38 * 365.2425,
        "sex": "Female",
    }
    male = next(f for f in profile.facts if f.value == "Male")
    assert male.experiencer == "other"
    child_age = next(f for f in profile.facts if f.value == 9)
    assert child_age.experiencer == "family"


def test_real_server_profile_filters_keep_unknowns_and_age_boundaries():
    url = os.environ.get("QDRANT_TEST_URL")
    if not url:
        pytest.skip("set QDRANT_TEST_URL for isolated profile-to-search integration")
    pytest.importorskip("numpy")
    from backend.app.repositories.qdrant import QdrantRepository
    from evaluation.tests.test_qdrant import fixture_data

    profile = extract_profile(case("A 70-year-old man has asthma. His father had diabetes."))
    plan = build_filter_plan(profile)
    contract, points = fixture_data()
    with QdrantRepository(url, "test_profile_" + uuid4().hex[:12]) as repo:
        try:
            repo.ensure_collection(contract)
            repo.upsert(points)
            hits = repo.search([1, 0, 0], contract, demographics=plan["demographics"])
            assert [h["payload"]["trial_id"] for h in hits] == ["NCT00000001", "NCT00000003"]
            unknown = build_filter_plan(extract_profile(case("The patient reports fatigue.")))
            assert len(repo.search([1, 0, 0], contract, demographics=unknown["demographics"])) == 5
        finally:
            repo.request("DELETE", repo.path)


def test_overflow_measurement_is_an_issue_not_a_dropped_or_infinite_fact():
    profile = extract_profile(case("Creatinine " + "9" * 400 + " mg/dL."))
    assert profile.facts == ()
    assert any(i.code == "unsupported_measurement" for i in profile.issues)


def test_fact_evaluation_imports_without_optional_ml_packages():
    command = (
        "import sys; "
        "sys.modules.update({k:None for k in ('numpy','torch','bm25s','sentence_transformers')}); "
        "from evaluation.patient_facts import evaluate_fixture, DEFAULT_FIXTURE; "
        "assert evaluate_fixture(DEFAULT_FIXTURE)['correct_filter_cases'] == 16"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_evaluation_records_real_misses_instead_of_assuming_success(tmp_path):
    data = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    data["cases"] = [
        {
            "case_id": "invented-miss",
            "text": "Unknowncondition.",
            "expected": [
                ["condition", "unknowncondition", "unknowncondition", None, "Unknowncondition"]
            ],
            "expected_filters": {},
        }
    ]
    path = tmp_path / "miss.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = evaluate_fixture(path)
    assert result["fact_metrics"]["fn"] == 1
    assert result["exact_cases"] == 0


def test_evaluation_preserves_reports_and_rejects_traversal(monkeypatch, tmp_path, capsys):
    from evaluation.patient_facts import main, report_id

    fixture = DEFAULT_FIXTURE.resolve()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["evaluate", "--fixture", str(fixture), "--output-id", "check"]
    )
    # Evaluation hashes use repository code paths; the full CLI smoke runs from the repo.
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert (tmp_path / "evaluation/reports/check/failure.json").is_file()
    before = (tmp_path / "evaluation/reports/check/labelled-results.json").read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert (tmp_path / "evaluation/reports/check/labelled-results.json").read_bytes() == before
    assert "fresh output ID" in capsys.readouterr().err
    with pytest.raises(argparse.ArgumentTypeError):
        report_id("../outside")
