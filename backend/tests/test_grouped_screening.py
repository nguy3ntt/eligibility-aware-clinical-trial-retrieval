"""Source-preserving grouped rules, exhaustive truth tables and deliberate abstention."""

import copy
import itertools
from pathlib import Path

import pytest

from backend.app.services.eligibility.grouped import combine, validate_grouped, verify_grouped, walk
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.criteria.parser import parse_eligibility
from pipelines.screening_data import load_pairs

FIXTURE = Path("evaluation/data/fixtures/grouped_screening.json")


@pytest.mark.parametrize(
    "row,case,source", load_pairs(FIXTURE), ids=lambda x: x["id"] if isinstance(x, dict) else None
)
def test_grouped_contracts_and_every_source_span(row, case, source):
    profile, parsed = extract_profile(case), parse_eligibility(source)
    packet = verify_grouped(profile, parsed)
    assert packet["status"] == row["status"]
    assert validate_grouped(packet, profile, parsed) == packet
    nodes = list(walk([s["root"] for s in packet["sections"]]))
    assert {i for n in nodes for i in n["criterion_ids"]} == {
        c.criterion_id for c in parsed.criteria
    }
    facts = {f.fact_id for f in profile.facts}
    for node in nodes:
        e = node["evidence"]
        assert source.text[e["start"] : e["end"]] == e["text"]
        assert set(node["fact_ids"]) <= facts
        assert node["truth"] == "unknown" or node["fact_ids"]
        for child in node["children"]:
            assert e["start"] <= child["evidence"]["start"] < child["evidence"]["end"] <= e["end"]
    modified = copy.deepcopy(packet)
    modified["status"] = "tampered"
    with pytest.raises(ValueError, match="reproduction"):
        validate_grouped(modified, profile, parsed)


@pytest.mark.parametrize("values", itertools.product(("true", "false", "unknown"), repeat=3))
def test_exhaustive_logic_agrees_with_possible_boolean_worlds(values):
    # Independent oracle: enumerate both possible values for every unknown operand.
    worlds = list(
        itertools.product(*[([True, False] if v == "unknown" else [v == "true"]) for v in values])
    )
    for operator, evaluate in (("and", all), ("or", any)):
        outcomes = {evaluate(world) for world in worlds}
        expected = "true" if outcomes == {True} else "false" if outcomes == {False} else "unknown"
        assert combine(operator, list(values)) == expected
    for operator, evaluate in (
        ("implies", lambda a, b: not a or b),
        ("waiver", lambda a, b: a or b),
        ("except", lambda a, b: a and not b),
    ):
        outcomes = {evaluate(w[0], w[1]) for w in worlds}
        expected = "true" if outcomes == {True} else "false" if outcomes == {False} else "unknown"
        assert combine(operator, list(values[:2])) == expected


def test_or_failure_does_not_become_a_trial_blocker():
    row, case, source = next(
        p for p in load_pairs(FIXTURE) if p[0]["id"] == "group-local-false-not-global"
    )
    packet = verify_grouped(extract_profile(case), parse_eligibility(source))
    assert packet["blocking_node_ids"] == []
    assert "false" in {n["truth"] for n in walk([s["root"] for s in packet["sections"]])}


def test_grouping_rejects_stale_profile_and_limits_complexity():
    _, case, source = load_pairs(FIXTURE)[0]
    profile = extract_profile(case)
    with pytest.raises(ValueError):
        verify_grouped(profile.model_copy(update={"facts": ()}), parse_eligibility(source))
    text = "Inclusion Criteria:\n- " + "(" * 20 + "Age >=18 years" + ")" * 20
    with pytest.raises(ValueError, match="depth"):
        verify_grouped(profile, parse_eligibility(source.model_copy(update={"text": text})))


@pytest.mark.parametrize(
    "wording", ["OR", "Age >=18 years AND", "()", "For female participants:", "."]
)
def test_empty_logical_operands_abstain_without_invalid_source_spans(wording):
    _, case, source = load_pairs(FIXTURE)[0]
    parsed = parse_eligibility(
        source.model_copy(update={"text": "Inclusion Criteria:\n- " + wording})
    )
    packet = verify_grouped(extract_profile(case), parsed)
    assert packet["status"] == "insufficient_information"


def test_balanced_parenthetical_in_separate_unsupported_clause_does_not_erase_age_blocker():
    _, case, source = load_pairs(FIXTURE)[2]
    parsed = parse_eligibility(
        source.model_copy(
            update={
                "text": "Inclusion Criteria:\n- Age >=18 years.\n- Prepubertal (Tanner stage I)."
            }
        )
    )
    packet = verify_grouped(extract_profile(case), parsed)
    assert not packet["scope_review_required"]
    assert packet["status"] == "likely_exclusion"
