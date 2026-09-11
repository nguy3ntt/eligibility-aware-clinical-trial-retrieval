import { z } from "zod";

const text = z.string();
const hash = text.regex(/^[a-f0-9]{64}$/);
const trialId = text.regex(/^NCT[0-9]{8}$/);
const span = z.object({
  start: z.number().int().nonnegative(),
  end: z.number().int().positive(),
  text,
});
const sourceKind = z.enum(["public_historical_xml", "invented_trial_fixture"]);
const field = z.object({ normalized: text }).passthrough();
const caseRecord = z
  .object({
    case_id: text,
    synthetic: z.literal(true),
    text,
    source: text,
    source_sha256: hash,
    source_locator: text,
  })
  .passthrough();
export const profileSchema = z
  .object({
    schema_version: z.literal("synthetic-profile-v1"),
    extractor_version: text,
    rules_sha256: hash,
    case: caseRecord,
    narrative_sha256: hash,
    facts: z.array(
      z
        .object({
          fact_id: hash,
          kind: text,
          name: text,
          value: z.union([text, z.number().finite()]),
          unit: text.nullable(),
          operator: text,
          assertion: text,
          temporality: text,
          certainty: text,
          experiencer: text,
          evidence: span,
          context: span,
          rule_id: text,
          method: z.literal("deterministic_rule"),
        })
        .passthrough(),
    ),
    issues: z.array(z.object({ code: text, message: text }).passthrough()),
    missing_categories: z.array(text),
    coverage: z.literal("bounded_rules_not_exhaustive"),
    eligibility_assessment: z.literal("not_performed"),
  })
  .passthrough();
export const casePageSchema = z.object({
  total: z.number().int().nonnegative(),
  limit: z.number(),
  offset: z.number(),
  items: z.array(
    z.object({ case_id: text, synthetic: z.literal(true), source: text }),
  ),
});
export const trialPageSchema = z.object({
  total: z.number().int().nonnegative(),
  limit: z.number(),
  offset: z.number(),
  items: z.array(
    z.object({ trial_id: trialId, title: text, source_kind: sourceKind }),
  ),
});
export const trialSchema = z
  .object({
    evidence: z
      .object({
        trial_id: trialId,
        source_kind: sourceKind,
        source_sha256: hash,
        fields: z.record(text, field),
      })
      .passthrough(),
    criteria: z
      .object({
        schema_version: z.literal("parsed-eligibility-v1"),
        parser_version: text,
        parser_sha256: hash,
        source: z
          .object({
            trial_id: trialId,
            text,
            source_kind: sourceKind,
            source_sha256: hash,
            source_locator: text,
          })
          .passthrough(),
        criteria: z.array(
          z
            .object({
              criterion_id: hash,
              ordinal: z.number().int(),
              section: text,
              parent_id: text.nullable(),
              evidence: span,
              types: z.array(text),
              logic: text,
              review_reasons: z.array(text),
              constraints: z.array(z.unknown()),
              eligibility_assessment: z.literal("not_performed"),
            })
            .passthrough(),
        ),
        issues: z.array(text),
        coverage: z.literal("bounded_rules_requires_review"),
      })
      .passthrough(),
  })
  .passthrough();
export const screeningStatus = z.enum([
  "potential_match",
  "likely_exclusion",
  "insufficient_information",
]);
export const searchSchema = z
  .object({
    schema_version: z.literal("research-api-v1"),
    operation_id: hash,
    kind: z.literal("search"),
    status: z.literal("complete"),
    replayed: z.boolean(),
    notice: text,
    request: z
      .object({
        case_id: text,
        method: z.literal("dense"),
        filter: z.literal("age_sex"),
        fact_extractor: z.literal("legacy"),
        rerank: z.literal(false),
        top_k: z.number().int(),
      })
      .passthrough(),
    provenance: z
      .object({
        catalog_id: text,
        catalog_sha256: hash,
        implementation_sha256: hash,
      })
      .passthrough(),
    result: z
      .object({
        method: z.literal("dense"),
        filter: z.literal("age_sex"),
        fact_extractor: z.literal("legacy"),
        dense_mode: z.literal("exact"),
        reranker: z.null(),
        candidate_count: z.number().int().nonnegative(),
        query_truncated: z.boolean(),
        default_retrieval_changed: z.literal(false),
        semantic_promotion: z.literal(false),
        results: z
          .array(
            z
              .object({
                trial_id: trialId,
                eligibility_assessment: screeningStatus,
                relevance: z
                  .object({
                    ranking: z
                      .object({
                        rank: z.number().int().positive(),
                        original_rank: z.number().int().positive(),
                        score: z.number().finite(),
                      })
                      .passthrough(),
                    fields: z.record(text, field),
                  })
                  .passthrough(),
                screening: z.object({ status: screeningStatus }).passthrough(),
              })
              .passthrough(),
          )
          .max(10),
      })
      .passthrough(),
  })
  .passthrough();
export const readySchema = z
  .object({ status: z.literal("ready"), catalog_id: text, model_loading: text })
  .passthrough();
export type Profile = z.infer<typeof profileSchema>;
export type Trial = z.infer<typeof trialSchema>;
export type Search = z.infer<typeof searchSchema>;
export type TrialPage = z.infer<typeof trialPageSchema>;
