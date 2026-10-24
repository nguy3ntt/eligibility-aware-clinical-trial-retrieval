"""Versioned HTTP request contracts; arbitrary patient text is deliberately absent."""

from typing import Literal

from pydantic import Field, model_validator

from backend.app.schemas.criteria import ParsedEligibility
from backend.app.schemas.eligibility import TrialAssessment
from backend.app.schemas.patient import StrictModel
from backend.app.schemas.review import ReviewPlan


class SearchRequest(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9:_-]{1,120}$")
    method: Literal["dense", "sparse", "hybrid", "field_passages"] = "dense"
    filter: Literal["age_sex", "none"] = "age_sex"
    fact_extractor: Literal["legacy", "profile"] = "legacy"
    top_k: int = Field(default=3, ge=1, le=10, strict=True)
    rerank: bool = Field(default=False, strict=True)
    rerank_depth: int = Field(default=20, ge=1, le=50, strict=True)
    reranker_variant: Literal["base", "domain_hard"] = "base"

    @model_validator(mode="after")
    def explicit_adaptation(self):
        if self.reranker_variant != "base" and not self.rerank:
            raise ValueError("experimental reranker requires explicit reranking")
        return self


class ScreeningRequest(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9:_-]{1,120}$")
    trial_id: str = Field(pattern=r"^NCT[0-9]{8}$")
    semantic: bool = Field(default=False, strict=True)
    grouped: bool = Field(default=False, strict=True)


class ExperimentRequest(StrictModel):
    configuration: Literal["screening-fixtures-v1"] = "screening-fixtures-v1"


class ErrorDetail(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetail


class OperationResponse(StrictModel):
    schema_version: Literal["research-api-v1"] = "research-api-v1"
    operation_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["search", "screening", "experiment"]
    status: Literal["complete"] = "complete"
    replayed: bool = False
    request: dict
    result: dict
    provenance: dict
    notice: str = (
        "Synthetic research only; not confirmed medical eligibility. Requires professional review."
    )


class ScreeningResult(StrictModel):
    assessment: TrialAssessment
    explanation: dict
    semantic: dict | None
    grouped: dict | None = None
    review_plan: ReviewPlan | None = None


class SearchResult(StrictModel):
    method: Literal["dense", "sparse", "hybrid", "field_passages"]
    filter: Literal["age_sex", "none"]
    fact_extractor: Literal["legacy", "profile"]
    filter_facts: dict | None
    filter_plan: dict | None
    dense_mode: Literal["exact"]
    contract: dict
    encoder: dict
    reranker: dict | None
    lexical_query: dict
    candidate_count: int = Field(ge=0, le=100)
    query_truncated: bool
    results: list[dict] = Field(max_length=10)
    benchmark_comparable: Literal[False]
    semantic_promotion: Literal[False]
    default_retrieval_changed: Literal[False]
    passage_retrieval: dict | None = None


class SearchResponse(OperationResponse):
    kind: Literal["search"]
    result: SearchResult


class ScreeningResponse(OperationResponse):
    kind: Literal["screening"]
    result: ScreeningResult


class TrialResponse(StrictModel):
    evidence: dict
    criteria: ParsedEligibility
