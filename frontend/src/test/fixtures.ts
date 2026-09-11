// Deliberately tiny invented contracts; never copied from real patient records.
import type { Profile, Search, Trial } from "../api/contracts";
export const hash = "a".repeat(64);
export const caseId = "invented-case";
export const trialId = "NCT90009002";
export const caseItem = {
  case_id: caseId,
  synthetic: true as const,
  source: "invented_fixture",
};
export const profile: Profile = {
  schema_version: "synthetic-profile-v1",
  extractor_version: "fixture-v1",
  rules_sha256: hash,
  case: {
    ...caseItem,
    text: "A 40 year old woman.",
    source_sha256: hash,
    source_locator: "invented-case",
  },
  narrative_sha256: hash,
  facts: [
    {
      fact_id: hash,
      kind: "age",
      name: "age",
      value: 40,
      unit: "year",
      operator: "eq",
      assertion: "present",
      temporality: "current",
      certainty: "asserted",
      experiencer: "patient",
      evidence: { start: 2, end: 13, text: "40 year old" },
      context: { start: 0, end: 20, text: "A 40 year old woman." },
      rule_id: "age-v1",
      method: "deterministic_rule",
    },
  ],
  missing_categories: ["condition", "medication", "measurement"],
  issues: [{ code: "bounded", message: "Invented bounded extraction note." }],
  coverage: "bounded_rules_not_exhaustive",
  eligibility_assessment: "not_performed",
};
export const search: Search = {
  schema_version: "research-api-v1",
  operation_id: hash,
  kind: "search",
  status: "complete",
  replayed: false,
  notice: "Synthetic research only.",
  request: {
    case_id: caseId,
    method: "dense",
    filter: "age_sex",
    fact_extractor: "legacy",
    rerank: false,
    top_k: 3,
  },
  provenance: {
    catalog_id: "invented-v1",
    catalog_sha256: hash,
    implementation_sha256: hash,
  },
  result: {
    method: "dense",
    filter: "age_sex",
    fact_extractor: "legacy",
    dense_mode: "exact",
    reranker: null,
    candidate_count: 1,
    query_truncated: false,
    default_retrieval_changed: false,
    semantic_promotion: false,
    results: [
      {
        trial_id: trialId,
        eligibility_assessment: "insufficient_information",
        relevance: {
          ranking: { rank: 1, original_rank: 1, score: 0.4321 },
          fields: {
            brief_title: { normalized: "Invented research trial" },
            brief_summary: {
              normalized: "An invented trial used to exercise the interface.",
            },
          },
        },
        screening: { status: "insufficient_information" },
      },
    ],
  },
};
export const trial: Trial = {
  evidence: {
    trial_id: trialId,
    source_kind: "invented_trial_fixture",
    source_sha256: hash,
    fields: {
      brief_title: { normalized: "Invented research trial" },
      brief_summary: { normalized: "Invented trial summary." },
      eligibility: { normalized: "Adults only." },
    },
  },
  criteria: {
    schema_version: "parsed-eligibility-v1",
    parser_version: "fixture-parser-v1",
    parser_sha256: hash,
    source: {
      trial_id: trialId,
      text: "Adults only.",
      source_kind: "invented_trial_fixture",
      source_sha256: hash,
      source_locator: "fixture",
    },
    criteria: [
      {
        criterion_id: hash,
        ordinal: 1,
        section: "inclusion",
        parent_id: null,
        evidence: { start: 0, end: 12, text: "Adults only." },
        types: ["age"],
        logic: "unspecified",
        review_reasons: ["requires_context"],
        constraints: [],
        eligibility_assessment: "not_performed",
      },
    ],
    issues: [],
    coverage: "bounded_rules_requires_review",
  },
};
