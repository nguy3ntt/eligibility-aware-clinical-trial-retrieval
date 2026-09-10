"""Validated synthetic narrative, mention evidence, and extraction output contracts."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["age", "sex", "condition", "medication", "treatment", "measurement"]
KINDS = ("age", "sex", "condition", "medication", "treatment", "measurement")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SyntheticCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9:_-]{1,120}$")
    synthetic: Literal[True]
    text: str = Field(min_length=1, max_length=20000)
    source: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_locator: str = Field(min_length=1, max_length=300)

    @field_validator("synthetic", mode="before")
    @classmethod
    def explicit_flag(cls, value):
        if value is not True:
            raise ValueError("synthetic must be explicitly true")
        return value

    @model_validator(mode="after")
    def validate_narrative(self):
        if not self.text.strip() or self.synthetic is not True:
            raise ValueError("a nonempty explicitly synthetic case is required")
        return self


class Span(StrictModel):
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("invalid character span")
        return self


class Fact(StrictModel):
    fact_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Kind
    name: str
    value: str | float
    unit: str | None = None
    operator: Literal["eq", "lt", "le", "gt", "ge", "approx"] = "eq"
    assertion: Literal["present", "absent", "uncertain"]
    temporality: Literal["current", "historical", "planned", "unknown"]
    certainty: Literal["asserted", "uncertain"]
    experiencer: Literal["patient", "family", "other", "unknown"]
    evidence: Span
    context: Span
    rule_id: str
    method: Literal["deterministic_rule"] = "deterministic_rule"

    @model_validator(mode="after")
    def value_contract(self):
        if self.kind in {"age", "measurement"} and (
            not isinstance(self.value, float) or self.value < 0 or not self.unit
        ):
            raise ValueError("numeric facts require a nonnegative quantity and explicit unit")
        if self.kind == "age" and self.unit not in {"day", "week", "month", "year"}:
            raise ValueError("unsupported age unit")
        if self.kind == "sex" and (self.value not in {"Male", "Female"} or self.unit is not None):
            raise ValueError("invalid narrative sex label")
        if self.kind in {"condition", "medication", "treatment"} and (
            self.value != self.name or self.unit is not None or self.operator != "eq"
        ):
            raise ValueError("named concept must retain its canonical label")
        if (self.assertion == "uncertain") != (self.certainty == "uncertain"):
            raise ValueError("uncertain assertion and certainty disagree")
        return self


class Issue(StrictModel):
    code: str
    message: str
    evidence: Span | None = None


class PatientProfile(StrictModel):
    schema_version: Literal["synthetic-profile-v1"] = "synthetic-profile-v1"
    extractor_version: str
    rules_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case: SyntheticCase
    narrative_sha256: str
    facts: tuple[Fact, ...]
    issues: tuple[Issue, ...]
    missing_categories: tuple[Kind, ...]
    coverage: Literal["bounded_rules_not_exhaustive"] = "bounded_rules_not_exhaustive"
    eligibility_assessment: Literal["not_performed"] = "not_performed"

    @model_validator(mode="after")
    def validate_evidence(self):
        text = self.case.text
        if self.narrative_sha256 != text_hash(text):
            raise ValueError("narrative hash mismatch")
        if len({f.fact_id for f in self.facts}) != len(self.facts):
            raise ValueError("duplicate fact identifier")
        for fact in self.facts:
            if (
                not fact.context.start
                <= fact.evidence.start
                < fact.evidence.end
                <= fact.context.end
            ):
                raise ValueError("mention outside its context")
        spans = [s for f in self.facts for s in (f.evidence, f.context)]
        spans.extend(i.evidence for i in self.issues if i.evidence is not None)
        if any(text[s.start : s.end] != s.text for s in spans):
            raise ValueError("evidence does not match original narrative")
        expected = tuple(k for k in KINDS if not any(f.kind == k for f in self.facts))
        if self.missing_categories != expected:
            raise ValueError("missing categories disagree with extracted mentions")
        return self
