import { z } from "zod";
import {
  profileSchema,
  retrievalSchema,
  screeningStatus,
  trialSchema,
} from "./contracts";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const outcome = z.enum(["satisfied", "violated", "unknown", "not_applicable"]);
const evidence = profileSchema.shape.facts.element.shape.evidence;
const sameSpan = (a: z.infer<typeof evidence>, b: z.infer<typeof evidence>) =>
  a.start === b.start && a.end === b.end && a.text === b.text;
export const assessmentSchema = z
  .object({
    schema_version: z.literal("research-screening-v1"),
    assessment_id: hash,
    verifier_version: z.string(),
    verifier_sha256: hash,
    profile: profileSchema,
    parsed: trialSchema.shape.criteria,
    criteria: z.array(
      z
        .object({
          criterion_id: hash,
          outcome,
          reason: z.string(),
          method: z.literal("deterministic_rule"),
          rule_id: z.string(),
          fact_ids: z.array(hash),
          evidence,
          missing_information: z.array(z.string()),
          confidence: z.null(),
        })
        .passthrough(),
    ),
    status: screeningStatus,
    blocking_criterion_ids: z.array(hash),
    unknown_criterion_ids: z.array(hash),
    missing_information: z.array(z.string()),
    requires_professional_review: z.literal(true),
    notice: z.string(),
  })
  .passthrough()
  .refine((a) => {
    const aligned = (source: string, s: z.infer<typeof evidence>) =>
      Array.from(source).slice(s.start, s.end).join("") === s.text;
    if (
      a.criteria.some((c) => !aligned(a.parsed.source.text, c.evidence)) ||
      a.profile.facts.some(
        (f) =>
          !aligned(a.profile.case.text, f.evidence) ||
          !aligned(a.profile.case.text, f.context),
      )
    )
      return false;
    const facts = new Set(a.profile.facts.map((f) => f.fact_id));
    const same = (x: string[], y: string[]) =>
      JSON.stringify(x) === JSON.stringify(y);
    if (
      a.criteria.length !== a.parsed.criteria.length ||
      new Set(a.criteria.map((c) => c.criterion_id)).size !== a.criteria.length
    )
      return false;
    if (
      a.criteria.some(
        (c, i) =>
          c.criterion_id !== a.parsed.criteria[i].criterion_id ||
          !sameSpan(c.evidence, a.parsed.criteria[i].evidence) ||
          c.fact_ids.some((id) => !facts.has(id)) ||
          (c.outcome !== "unknown" && !c.fact_ids.length),
      )
    )
      return false;
    const blockers = a.criteria
      .filter((c) => c.outcome === "violated")
      .map((c) => c.criterion_id);
    const unknown = a.criteria
      .filter((c) => c.outcome === "unknown")
      .map((c) => c.criterion_id);
    const status = blockers.length
      ? "likely_exclusion"
      : unknown.length || !a.criteria.some((c) => c.outcome === "satisfied")
        ? "insufficient_information"
        : "potential_match";
    return (
      a.status === status &&
      same(blockers, a.blocking_criterion_ids) &&
      same(unknown, a.unknown_criterion_ids) &&
      same(
        [...new Set(a.criteria.flatMap((c) => c.missing_information))],
        a.missing_information,
      )
    );
  }, "Screening evidence and summary must agree");
export const semanticSchema = z
  .object({
    model: z.record(z.string(), z.unknown()),
    advisories: z.array(
      z
        .object({
          criterion_id: hash,
          method: z.literal("learned_nli"),
          promoted: z.literal(false),
          status: z.enum(["scored", "not_run", "abstained"]),
          proposed_outcome: outcome,
          reason: z.string().optional(),
          patient_evidence: z.string(),
          criterion_evidence: evidence,
          probabilities: z
            .record(z.string(), z.number().min(0).max(1))
            .optional(),
        })
        .passthrough(),
    ),
  })
  .passthrough();
const envelope = z
  .object({
    schema_version: z.literal("research-api-v1"),
    operation_id: hash,
    status: z.literal("complete"),
    replayed: z.boolean(),
    notice: z.string(),
    provenance: retrievalSchema.shape.provenance,
  })
  .passthrough();
export const screeningSchema = envelope
  .extend({
    kind: z.literal("screening"),
    request: z
      .object({
        case_id: z.string(),
        trial_id: z.string(),
        semantic: z.boolean(),
      })
      .passthrough(),
    result: z
      .object({
        assessment: assessmentSchema,
        explanation: z.record(z.string(), z.unknown()),
        semantic: semanticSchema.nullable(),
      })
      .passthrough(),
  })
  .refine((p) => {
    const a = p.result.assessment,
      s = p.result.semantic;
    if (
      a.profile.case.case_id !== p.request.case_id ||
      a.parsed.source.trial_id !== p.request.trial_id ||
      p.request.semantic !== (s !== null)
    )
      return false;
    return (
      !s ||
      (s.advisories.length === a.criteria.length &&
        s.advisories.every(
          (n, i) =>
            n.criterion_id === a.criteria[i].criterion_id &&
            sameSpan(n.criterion_evidence, a.criteria[i].evidence) &&
            n.patient_evidence === a.profile.case.text,
        ))
    );
  });
export const fixtureExperimentSchema = envelope
  .extend({
    kind: z.literal("experiment"),
    request: z
      .object({ configuration: z.literal("screening-fixtures-v1") })
      .passthrough(),
    result: z
      .object({
        configuration: z.literal("screening-fixtures-v1"),
        clinical_validation: z.literal(false),
        status: z.enum(["passed", "failed"]),
        fixture_sha256: hash,
        evaluation: z
          .object({
            pairs: z.number().int().nonnegative(),
            exact_pairs: z.number().int().nonnegative(),
            criterion_count: z.number().int().nonnegative(),
          })
          .passthrough(),
      })
      .passthrough(),
  })
  .refine(
    (p) =>
      p.result.evaluation.exact_pairs <= p.result.evaluation.pairs &&
      (p.result.status === "passed") ===
        (p.result.evaluation.pairs === p.result.evaluation.exact_pairs),
  );
export const historicalSchema = z
  .object({
    operation_id: hash,
    kind: z.literal("reviewed_experiment"),
    status: z.literal("complete"),
    source: z.object({ report_id: z.string(), sha256: hash }),
    notice: z.string(),
    result: z.record(z.string(), z.unknown()),
  })
  .passthrough();
export const operationSchema = z.union([
  retrievalSchema,
  screeningSchema,
  fixtureExperimentSchema,
  historicalSchema,
]);
export const operationPageSchema = z.object({
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  items: z.array(
    z.object({
      operation_id: hash,
      kind: z.enum([
        "search",
        "screening",
        "experiment",
        "reviewed_experiment",
      ]),
      status: z.literal("complete"),
    }),
  ),
});
export type Assessment = z.infer<typeof assessmentSchema>;
export type Semantic = z.infer<typeof semanticSchema>;
export type Screening = z.infer<typeof screeningSchema>;
export type Operation = z.infer<typeof operationSchema>;
export type FixtureExperiment = z.infer<typeof fixtureExperimentSchema>;
