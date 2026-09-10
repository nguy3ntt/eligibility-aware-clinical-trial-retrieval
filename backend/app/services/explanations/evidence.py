"""Deterministic explanations of stored evidence, never invented model rationales."""

import math

from backend.app.schemas.patient import SyntheticCase, text_hash
from backend.app.services.eligibility.rules import validate_assessment
from pipelines.render_trials import REPRESENTATIONS
from pipelines.reranking_data import eligibility_source, validate_record

VERSION = "evidence-explanation-v1"
NOTICE = "Research only; not confirmed medical eligibility. Requires professional review."
OUTCOMES = {
    "satisfied": "The supported deterministic rule is satisfied by the cited synthetic facts.",
    "violated": "The supported deterministic rule identifies a likely exclusion.",
    "unknown": "Insufficient information or unsupported interpretation; no satisfaction inferred.",
    "not_applicable": "The supported conditional rule does not apply to the cited synthetic facts.",
}


def explain_screening(assessment) -> dict:
    assessment = validate_assessment(assessment)
    facts = {f.fact_id: f.model_dump(mode="json") for f in assessment.profile.facts}
    return {
        "version": VERSION,
        "status": assessment.status,
        "notice": NOTICE,
        "blocking_criterion_ids": list(assessment.blocking_criterion_ids),
        "missing_information": list(assessment.missing_information),
        "criteria": [
            {
                "criterion_id": c.criterion_id,
                "outcome": c.outcome,
                "statement": OUTCOMES[c.outcome],
                "reason": c.reason,
                "rule_id": c.rule_id,
                "method": c.method,
                "trial_evidence": c.evidence.model_dump(),
                "patient_facts": [facts[f] for f in c.fact_ids],
            }
            for c in assessment.criteria
        ],
        "assessment": assessment.model_dump(mode="json"),
    }


def explain_result(case: SyntheticCase, result: dict, record: dict, assessment=None) -> dict:
    case = SyntheticCase.model_validate(case.model_dump())
    validate_record(record)
    if result["trial_id"] != record["trial_id"]:
        raise ValueError("explanation trial identity mismatch")
    if not math.isfinite(result["score"]):
        raise ValueError("explanation candidate score must be finite")
    model_result = result.get("reranker")
    if model_result is not None:
        if model_result.get("method") != "learned_cross_encoder" or not math.isfinite(
            model_result.get("score", float("nan"))
        ):
            raise ValueError("invalid learned relevance result")
        for key, text in (
            ("query", case.text),
            ("document", record["row"]["representations"]["summary"]),
        ):
            span = model_result["input"][key]
            if (
                span["source_sha256"] != text_hash(text)
                or not 0 <= span["start"] < span["end"] <= len(text)
                or text[span["start"] : span["end"]] != span["text"]
                or type(span["used_tokens"]) is not int
                or type(span["total_tokens"]) is not int
                or not 1 <= span["used_tokens"] <= span["total_tokens"]
                or span["truncated"] is not (span["used_tokens"] < span["total_tokens"])
            ):
                raise ValueError("reranker evidence differs from source")
        query_count = model_result["input"]["query"]["used_tokens"]
        document_count = model_result["input"]["document"]["used_tokens"]
        if query_count > 192 or query_count + document_count + 3 > 512:
            raise ValueError("reranker input exceeds the recorded template")
    screening = None
    if assessment is not None:
        if assessment.profile.case != case or assessment.parsed.source != eligibility_source(
            record
        ):
            raise ValueError("screening belongs to different patient or trial evidence")
        screening = explain_screening(assessment)
    return {
        "version": VERSION,
        "trial_id": result["trial_id"],
        "notice": NOTICE,
        "relevance": {
            "statement": (
                "Ordered by a learned query-summary relevance score within the candidate prefix; "
                "this score is not an eligibility probability or a causal explanation."
                if model_result
                else "Retained candidate order; no cross-encoder score was applied to this result."
            ),
            "ranking": result,
            "patient_source": case.model_dump(mode="json"),
            "trial_source": record["row"]["source"],
            "trial_xml_sha256": record["source_sha256"],
            "rendered_content_sha256": record["row"]["content_sha256"],
            "fields": {name: record["fields"][name] for name in REPRESENTATIONS["summary"]},
        },
        "screening": screening,
        "eligibility_assessment": screening["status"] if screening else "not_performed",
        "semantic_advisories": "not_used_for_ranking_or_explanations",
    }
