"""Lossless parsing, safe ambiguity, provenance corruption and development labels."""

import copy
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.app.schemas.criteria import EligibilitySource, ParsedEligibility
from backend.app.schemas.patient import text_hash
from evaluation.criteria import evaluate_fixture
from pipelines.criteria.artifacts import load_parses, save_parses
from pipelines.criteria.parser import parse_eligibility
from pipelines.criteria_parse import DEFAULT_FIXTURE


def source(text):
    return EligibilitySource(
        trial_id="NCT00000001",
        text=text,
        source_kind="invented_trial_fixture",
        source_sha256=text_hash(text),
        source_locator="/trial/eligibility",
        provenance={"invented": "true"},
    )


def test_labelled_development_sample():
    result = evaluate_fixture(DEFAULT_FIXTURE)
    assert result["exact_trials"] == result["trials"] == 10
    assert result["criterion_metrics"] == {
        "tp": 27,
        "fp": 0,
        "fn": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \r\n",
        "No labelled section.",
        "Introduction.\nInclusion Criteria:\n- Age >= 18 years.\nExclusion Criteria:\n- Asthma.",
        "Inclusion Criteria\r\n- Written consent\r\n  and follow-up.\r\n"
        "Exclusion Criteria\r\n- No insulin.",
    ],
)
def test_entire_field_and_criterion_offsets_roundtrip(text):
    parsed = parse_eligibility(source(text))
    assert "".join(s.evidence.text for s in parsed.sections) == text
    assert ParsedEligibility.model_validate_json(parsed.model_dump_json()) == parsed
    assert parse_eligibility(source(text)) == parsed
    for c in parsed.criteria:
        assert text[c.evidence.start : c.evidence.end] == c.evidence.text


def test_boolean_exception_and_orphan_bounds_are_not_detached():
    text = (
        "Inclusion Criteria:\n- Disease A or disease B and consent.\n"
        "- Age >= 18 years; <= 65 years.\n- No surgery unless minor."
    )
    criteria = parse_eligibility(source(text)).criteria
    assert len(criteria) == 3
    assert criteria[0].logic == "mixed"
    assert "compound_logic_preserved" in criteria[0].review_reasons
    assert "unsplit_semicolon" in criteria[1].review_reasons
    assert "conditional_or_exception" in criteria[2].review_reasons
    assert criteria[2].negation_cues[0].text == "No"


def test_nested_parents_wrapped_lines_and_section_reset():
    text = (
        "Inclusion Criteria:\n- Laboratory requirements:\n  - Hemoglobin >= 9 g/dL\n"
        "    on two visits.\n- Consent.\nExclusion Criteria:\n  - No chemotherapy."
    )
    parsed = parse_eligibility(source(text))
    assert len(parsed.criteria) == 4
    assert parsed.criteria[1].parent_id == parsed.criteria[0].criterion_id
    assert "on two visits" in parsed.criteria[1].evidence.text
    assert parsed.criteria[-1].parent_id is None


@pytest.mark.parametrize(
    "text,operator,value,upper,unit",
    [
        ("Age >= 18 years.", "ge", 18, None, "year"),
        ("Age at most 6 months.", "le", 6, None, "month"),
        ("Age between 2 and 8 weeks.", "range", 2, 8, "week"),
        ("Creatinine ≤ 90 µmol/L.", "le", 90, None, "umol/L"),
        ("Hemoglobin no less than 9 g/dL.", "ge", 9, None, "g/dL"),
    ],
)
def test_numeric_operators_and_canonical_units(text, operator, value, upper, unit):
    c = parse_eligibility(source("Inclusion Criteria: " + text)).criteria[0].constraints[0]
    assert (c.operator, c.value, c.upper, c.unit) == (operator, value, upper, unit)


@pytest.mark.parametrize(
    "text",
    [
        "Age 65 to 18 years.",
        "Age >= -1 years.",
        "Creatinine > 2 widgets.",
        "Creatinine > 1.2 mg/dL/min.",
        "Creatinine > " + "9" * 400 + " mg/dL.",
    ],
)
def test_bad_numeric_constraints_are_retained_for_review(text):
    c = parse_eligibility(source("Inclusion Criteria: " + text)).criteria[0]
    assert not c.constraints
    assert any("numeric" in r for r in c.review_reasons)


def test_changed_source_or_parser_values_are_rejected(tmp_path):
    save_parses(tmp_path, [source("Inclusion Criteria:\n- Age >= 18 years.")])
    _, parsed = load_parses(tmp_path)
    raw = parsed[0].model_dump()
    raw["criteria"][0]["evidence"]["text"] = "X" * len(raw["criteria"][0]["evidence"]["text"])
    with pytest.raises(ValidationError):
        ParsedEligibility.model_validate(raw)
    original = json.loads((tmp_path / "parsed.json").read_bytes())
    changed = copy.deepcopy(original)
    changed[0]["criteria"][0]["constraints"][0]["value"] = 21
    (tmp_path / "parsed.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_parses(tmp_path)
    # Even editing the checksum cannot legitimize a changed deterministic parse.
    from pipelines.criteria.artifacts import file_hash

    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest["files"]["parsed.json"] = file_hash(tmp_path / "parsed.json")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="deterministic"):
        load_parses(tmp_path)


def test_source_size_and_duplicate_identity_contracts(tmp_path):
    with pytest.raises(ValidationError):
        source("x" * 100001)
    with pytest.raises(ValueError, match="unique"):
        save_parses(tmp_path, [source("A"), source("B")])


def test_parser_does_not_require_optional_ml_packages():
    command = (
        "import sys; sys.modules.update({k:None for k in ('numpy','bm25s','torch')}); "
        "from evaluation.criteria import evaluate_fixture; "
        "from pipelines.criteria_parse import DEFAULT_FIXTURE; "
        "assert evaluate_fixture(DEFAULT_FIXTURE)['exact_trials']==10"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_colonless_crlf_headers_and_paragraphs_preserve_offsets():
    text = "Inclusion Criteria\r\nAge >= 18 years.\r\n\r\nConsent.\r\nExclusion Criteria\r\nNone."
    parsed = parse_eligibility(source(text))
    assert [c.section for c in parsed.criteria] == ["inclusion", "inclusion", "exclusion"]
    assert [c.evidence.text for c in parsed.criteria] == ["Age >= 18 years.", "Consent.", "None."]
    assert "placeholder_statement" in parsed.criteria[-1].review_reasons
    assert "".join(s.evidence.text for s in parsed.sections) == text


def test_paragraph_alternative_stays_attached_and_bullet_subheadings_are_flagged():
    parsed = parse_eligibility(source("Inclusion Criteria:\nDisease A.\n\nOR disease B."))
    assert len(parsed.criteria) == 1
    assert parsed.criteria[0].logic == "or"
    parsed = parse_eligibility(source("Inclusion Criteria:\n- Consent.\n\nAllowed:\n- Drug A."))
    assert len(parsed.criteria) == 2
    assert "embedded_heading_requires_review" in parsed.criteria[0].review_reasons


def test_cli_rejects_unknown_trial_and_protects_existing_reports(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.criteria_parse", "demo", "--trial-id", "NCT99999999"],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert b"Criteria parsing failed" in result.stderr
    output = tmp_path / "evaluation" / "reports" / "existing"
    output.mkdir(parents=True)
    marker = output / "keep.txt"
    marker.write_text("keep")
    # Invoke the installed package from a temporary working directory.
    result = subprocess.run(
        [sys.executable, "-m", "evaluation.criteria", "--output-id", "existing"],
        cwd=tmp_path,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert b"fresh output ID" in result.stderr
    assert marker.read_text() == "keep"


@pytest.mark.parametrize(
    "text",
    [
        "Age >= 18 years; Hemoglobin >= 10 g/dL unless waived.",
        "If assigned to arm A: Age >= 18 years; Hemoglobin >= 10 g/dL.",
        "Disease A or age >= 18 years; Hemoglobin >= 10 g/dL.",
    ],
)
def test_semicolon_never_detaches_shared_exception_condition_or_alternative(text):
    parsed = parse_eligibility(source("Inclusion Criteria:\n- " + text))
    assert len(parsed.criteria) == 1
    assert parsed.criteria[0].evidence.text == text
    assert "unsplit_semicolon" in parsed.criteria[0].review_reasons
