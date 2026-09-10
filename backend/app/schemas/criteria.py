"""Lossless eligibility-field provenance and conservative criterion parse contracts."""

from typing import Literal

from pydantic import Field, model_validator

from backend.app.schemas.patient import Span, StrictModel, text_hash

SectionLabel = Literal["inclusion", "exclusion", "unknown"]


class EligibilitySource(StrictModel):
    trial_id: str = Field(pattern=r"^NCT[0-9]{8}$")
    text: str = Field(max_length=100000)
    source_kind: Literal["invented_trial_fixture", "public_historical_xml"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_locator: str = Field(min_length=1)
    provenance: dict[str, str]


class Section(StrictModel):
    ordinal: int = Field(ge=1)
    label: SectionLabel
    evidence: Span
    body_start: int = Field(ge=0)


class NumericConstraint(StrictModel):
    name: str
    operator: Literal["eq", "ge", "gt", "le", "lt", "range"]
    value: float
    upper: float | None = None
    unit: str
    evidence: Span
    method: Literal["deterministic_rule"] = "deterministic_rule"

    @model_validator(mode="after")
    def valid_range(self):
        if self.value < 0 or (self.upper is not None and self.upper < self.value):
            raise ValueError("invalid numeric constraint")
        if (self.operator == "range") != (self.upper is not None):
            raise ValueError("range requires exactly two bounds")
        return self


class Criterion(StrictModel):
    criterion_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    ordinal: int = Field(ge=1)
    section_ordinal: int = Field(ge=1)
    section: SectionLabel
    parent_id: str | None
    evidence: Span
    types: tuple[
        Literal[
            "age", "sex", "condition", "medication", "treatment", "measurement", "consent", "other"
        ],
        ...,
    ]
    logic: Literal["and", "or", "mixed", "unspecified"]
    negation_cues: tuple[Span, ...]
    constraints: tuple[NumericConstraint, ...]
    review_reasons: tuple[str, ...]
    method: Literal["deterministic_rule"] = "deterministic_rule"
    eligibility_assessment: Literal["not_performed"] = "not_performed"


class ParsedEligibility(StrictModel):
    schema_version: Literal["parsed-eligibility-v1"] = "parsed-eligibility-v1"
    parser_version: str
    parser_sha256: str
    source: EligibilitySource
    text_sha256: str
    sections: tuple[Section, ...]
    criteria: tuple[Criterion, ...]
    issues: tuple[str, ...]
    coverage: Literal["bounded_rules_requires_review"] = "bounded_rules_requires_review"

    @model_validator(mode="after")
    def source_alignment(self):
        text = self.source.text
        if self.text_sha256 != text_hash(text):
            raise ValueError("eligibility text hash mismatch")
        cursor = 0
        for ordinal, section in enumerate(self.sections, 1):
            e = section.evidence
            if (
                section.ordinal != ordinal
                or e.start != cursor
                or not e.start <= section.body_start <= e.end
            ):
                raise ValueError("section coverage/order mismatch")
            if text[e.start : e.end] != e.text:
                raise ValueError("section source mismatch")
            cursor = e.end
        if cursor != len(text):
            raise ValueError("sections must preserve the entire original field")
        seen, previous_end = set(), -1
        for ordinal, criterion in enumerate(self.criteria, 1):
            e = criterion.evidence
            if (
                criterion.ordinal != ordinal
                or criterion.criterion_id in seen
                or e.start < previous_end
            ):
                raise ValueError("criterion order/identity mismatch")
            if criterion.parent_id is not None and criterion.parent_id not in seen:
                raise ValueError("parent must precede its child")
            if not 1 <= criterion.section_ordinal <= len(self.sections):
                raise ValueError("invalid criterion section")
            section = self.sections[criterion.section_ordinal - 1]
            if (
                criterion.section != section.label
                or not section.body_start <= e.start < e.end <= section.evidence.end
            ):
                raise ValueError("criterion outside its section")
            spans = [e, *criterion.negation_cues, *(c.evidence for c in criterion.constraints)]
            if any(
                text[s.start : s.end] != s.text or not e.start <= s.start < s.end <= e.end
                for s in spans
            ):
                raise ValueError("criterion evidence mismatch")
            seen.add(criterion.criterion_id)
            previous_end = e.end
        return self
