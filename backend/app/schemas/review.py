"""Non-clinical review ordering, separate from immutable screening outcomes."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.app.schemas.patient import Span, StrictModel

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ReviewReference(StrictModel):
    reference_id: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    assessment_id: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    trial_id: str = Field(pattern=r"^NCT[0-9]{8}$")
    criterion_ids: tuple[Hash, ...] = Field(min_length=1)
    node_id: Hash | None
    evidence: Span
    fact_ids: tuple[Hash, ...]
    reason: str
    missing_information: tuple[str, ...]


class ReviewBasis(StrictModel):
    assessment_id: Hash
    trial_id: str
    source_sha256: Hash
    source_text_sha256: Hash
    status: Literal["potential_match", "likely_exclusion", "insufficient_information"]
    blocking_ids: tuple[Hash, ...]
    grouped_sha256: Hash | None
    scope_review_required: bool


class ReviewItem(StrictModel):
    item_id: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    rank: int = Field(ge=1, strict=True)
    fact_name: str
    requested_unit: str | None
    prompt: str
    unblocked_trial_count: int = Field(ge=0, strict=True)
    trial_count: int = Field(ge=1, strict=True)
    criterion_count: int = Field(ge=1, strict=True)
    references: tuple[ReviewReference, ...] = Field(min_length=1)


class ReviewPlan(StrictModel):
    schema_version: Literal["missing-information-review-v1"] = "missing-information-review-v1"
    plan_id: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_sha256: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    case_id: str
    case_text_sha256: Hash
    mode: Literal["ordinary", "grouped"]
    basis: tuple[ReviewBasis, ...] = Field(min_length=1, max_length=10)
    items: tuple[ReviewItem, ...]
    interpretation_reviews: tuple[ReviewReference, ...]
    settled_branch_reviews: tuple[ReviewReference, ...]
    ordering: Literal["unblocked_trials_then_source_criteria_then_trials_then_fact_key"] = (
        "unblocked_trials_then_source_criteria_then_trials_then_fact_key"
    )
    method: Literal["deterministic_review_order"] = "deterministic_review_order"
    changes_screening: Literal[False] = False
    clinical_urgency: Literal[False] = False
    estimated_information_gain: None = None
    requires_professional_review: Literal[True] = True

    @model_validator(mode="after")
    def consistent_counts(self):
        trials = {b.trial_id: b for b in self.basis}
        if len(trials) != len(self.basis):
            raise ValueError("review basis has duplicate trials")
        ids = [r.reference_id for item in self.items for r in item.references]
        ids += [
            r.reference_id for r in (*self.interpretation_reviews, *self.settled_branch_reviews)
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("every review reference must have one disposition")
        if len({i.item_id for i in self.items}) != len(self.items):
            raise ValueError("duplicate review item")
        for rank, item in enumerate(self.items, 1):
            tids = {r.trial_id for r in item.references}
            if (
                item.rank != rank
                or not tids <= trials.keys()
                or item.trial_count != len(tids)
                or item.criterion_count
                != len({(r.trial_id, c) for r in item.references for c in r.criterion_ids})
                or item.unblocked_trial_count != sum(not trials[t].blocking_ids for t in tids)
            ):
                raise ValueError("review priority counts disagree with source references")
        for ref in [r for item in self.items for r in item.references] + list(
            (*self.interpretation_reviews, *self.settled_branch_reviews)
        ):
            if (
                ref.trial_id not in trials
                or ref.assessment_id != trials[ref.trial_id].assessment_id
            ):
                raise ValueError("review reference differs from assessment basis")
        return self
