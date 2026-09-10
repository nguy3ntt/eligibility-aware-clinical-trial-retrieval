"""Evidence-linked research screening outcomes; never confirmed eligibility."""

from typing import Literal

from pydantic import Field, model_validator

from backend.app.schemas.criteria import ParsedEligibility
from backend.app.schemas.patient import PatientProfile, Span, StrictModel

Outcome = Literal["satisfied", "violated", "unknown", "not_applicable"]


class CriterionAssessment(StrictModel):
    criterion_id: str
    outcome: Outcome
    reason: str
    method: Literal["deterministic_rule"] = "deterministic_rule"
    rule_id: str
    fact_ids: tuple[str, ...]
    evidence: Span
    missing_information: tuple[str, ...] = ()
    confidence: None = None  # Rules have no empirical per-case probability.


class TrialAssessment(StrictModel):
    schema_version: Literal["research-screening-v1"] = "research-screening-v1"
    assessment_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    verifier_version: str
    verifier_sha256: str
    profile: PatientProfile
    parsed: ParsedEligibility
    criteria: tuple[CriterionAssessment, ...]
    status: Literal["potential_match", "likely_exclusion", "insufficient_information"]
    blocking_criterion_ids: tuple[str, ...]
    unknown_criterion_ids: tuple[str, ...]
    missing_information: tuple[str, ...]
    requires_professional_review: Literal[True] = True
    notice: str = "Research screening only; not confirmed medical eligibility."

    @model_validator(mode="after")
    def aligned_evidence(self):
        if [c.criterion_id for c in self.criteria] != [
            c.criterion_id for c in self.parsed.criteria
        ]:
            raise ValueError("screening must retain every criterion in source order")
        facts = {f.fact_id for f in self.profile.facts}
        for assessment, criterion in zip(self.criteria, self.parsed.criteria, strict=True):
            if assessment.evidence != criterion.evidence or not set(assessment.fact_ids) <= facts:
                raise ValueError("screening evidence is not source-aligned")
            if assessment.outcome != "unknown" and not assessment.fact_ids:
                raise ValueError("a supported outcome requires patient evidence")
        blocking = tuple(c.criterion_id for c in self.criteria if c.outcome == "violated")
        unknown = tuple(c.criterion_id for c in self.criteria if c.outcome == "unknown")
        if self.blocking_criterion_ids != blocking or self.unknown_criterion_ids != unknown:
            raise ValueError("screening summary disagrees with criterion outcomes")
        missing = tuple(
            dict.fromkeys(item for c in self.criteria for item in c.missing_information)
        )
        if self.missing_information != missing:
            raise ValueError("missing-information summary disagrees with criterion evidence")
        status = (
            "likely_exclusion"
            if blocking
            else "insufficient_information"
            if unknown or not any(c.outcome == "satisfied" for c in self.criteria)
            else "potential_match"
        )
        if self.status != status:
            raise ValueError("screening status disagrees with evidence")
        return self
