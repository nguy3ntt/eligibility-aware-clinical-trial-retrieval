import { z } from "zod";
import type { Assessment } from "./workbenchContracts";
import type { Grouped, LogicNode } from "./groupedContracts";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const span = z.object({
  start: z.number().int().min(0),
  end: z.number().int().positive(),
  text: z.string(),
});
const reference = z.object({
  reference_id: hash,
  assessment_id: hash,
  trial_id: z.string(),
  criterion_ids: z.array(hash).min(1),
  node_id: hash.nullable(),
  evidence: span,
  fact_ids: z.array(hash),
  reason: z.string(),
  missing_information: z.array(z.string()),
});
export const reviewPlanSchema = z.object({
  schema_version: z.literal("missing-information-review-v1"),
  plan_id: hash,
  implementation_sha256: hash,
  case_id: z.string(),
  case_text_sha256: hash,
  mode: z.enum(["ordinary", "grouped"]),
  basis: z
    .array(
      z.object({
        assessment_id: hash,
        trial_id: z.string(),
        source_sha256: hash,
        source_text_sha256: hash,
        status: z.enum([
          "potential_match",
          "likely_exclusion",
          "insufficient_information",
        ]),
        blocking_ids: z.array(hash),
        grouped_sha256: hash.nullable(),
        scope_review_required: z.boolean(),
      }),
    )
    .min(1)
    .max(10),
  items: z.array(
    z.object({
      item_id: hash,
      rank: z.number().int().positive(),
      fact_name: z.enum([
        "age",
        "sex",
        "hemoglobin",
        "hba1c",
        "creatinine",
        "bmi",
        "platelets",
      ]),
      requested_unit: z.string().nullable(),
      prompt: z.string(),
      unblocked_trial_count: z.number().int().min(0),
      trial_count: z.number().int().positive(),
      criterion_count: z.number().int().positive(),
      references: z.array(reference).min(1),
    }),
  ),
  interpretation_reviews: z.array(reference),
  settled_branch_reviews: z.array(reference),
  ordering: z.literal(
    "unblocked_trials_then_source_criteria_then_trials_then_fact_key",
  ),
  method: z.literal("deterministic_review_order"),
  changes_screening: z.literal(false),
  clinical_urgency: z.literal(false),
  estimated_information_gain: z.null(),
  requires_professional_review: z.literal(true),
});
export type ReviewPlan = z.infer<typeof reviewPlanSchema>;
type Reference = z.infer<typeof reference>;
const same = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
const sameSpan = (a: Reference["evidence"], b: Reference["evidence"]) =>
  a.start === b.start && a.end === b.end && a.text === b.text;
const factReasons = new Set([
  "missing_uncertain_or_unanchored_patient_evidence",
  "conflicting_patient_evidence",
  "units_differ_no_conversion",
]);

export function reviewAligns(
  p: ReviewPlan,
  a: Assessment,
  g?: Grouped | null,
): boolean {
  const basis = p.basis[0];
  if (
    p.basis.length !== 1 ||
    p.case_id !== a.profile.case.case_id ||
    p.case_text_sha256 !== a.profile.narrative_sha256 ||
    p.mode !== (g ? "grouped" : "ordinary") ||
    basis.assessment_id !== a.assessment_id ||
    basis.trial_id !== a.parsed.source.trial_id ||
    basis.source_sha256 !== a.parsed.source.source_sha256 ||
    basis.source_text_sha256 !== a.parsed.text_sha256 ||
    basis.status !== (g?.status ?? a.status) ||
    !same(
      basis.blocking_ids,
      g?.blocking_node_ids ?? a.blocking_criterion_ids,
    ) ||
    basis.scope_review_required !== Boolean(g?.scope_review_required) ||
    Boolean(basis.grouped_sha256) !== Boolean(g)
  )
    return false;
  const expected = new Map<
    string,
    {
      source: {
        evidence: Reference["evidence"];
        fact_ids: string[];
        reason: string;
        missing_information: string[];
      };
      ids: string[];
      settled: boolean;
    }
  >();
  if (g && !g.scope_review_required) {
    const visit = (node: LogicNode, active: boolean) => {
      active = active && node.truth === "unknown";
      if (node.children.length) node.children.forEach((c) => visit(c, active));
      else if (node.truth === "unknown")
        expected.set(node.node_id, {
          source: node,
          ids: node.criterion_ids,
          settled: !active,
        });
    };
    g.sections.forEach((s) => visit(s.root, true));
  } else {
    a.criteria
      .filter((c) => c.outcome === "unknown")
      .forEach((c) =>
        expected.set(c.criterion_id, {
          source: c,
          ids: [c.criterion_id],
          settled: false,
        }),
      );
  }
  const seen = new Set<string>(),
    refIds = new Set<string>();
  const aligned = (
    r: Reference,
    disposition: "fact" | "interpretation" | "settled",
  ) => {
    const key = r.node_id ?? r.criterion_ids[0],
      e = expected.get(key);
    if (
      !e ||
      seen.has(key) ||
      refIds.has(r.reference_id) ||
      r.assessment_id !== a.assessment_id ||
      r.trial_id !== basis.trial_id ||
      !same(r.criterion_ids, e.ids) ||
      !sameSpan(r.evidence, e.source.evidence) ||
      !same(r.fact_ids, e.source.fact_ids) ||
      r.reason !== e.source.reason ||
      !same(r.missing_information, e.source.missing_information) ||
      (disposition === "settled") !== e.settled ||
      (g?.scope_review_required && disposition !== "interpretation")
    )
      return false;
    seen.add(key);
    refIds.add(r.reference_id);
    return true;
  };
  const itemIds = new Set<string>(),
    factKeys = new Set<string>();
  for (const [index, item] of p.items.entries()) {
    const criteria = new Set(item.references.flatMap((r) => r.criterion_ids));
    const factKey = JSON.stringify([item.fact_name, item.requested_unit]);
    if (
      item.rank !== index + 1 ||
      itemIds.has(item.item_id) ||
      factKeys.has(factKey) ||
      item.trial_count !== 1 ||
      item.criterion_count !== criteria.size ||
      item.unblocked_trial_count !== (basis.blocking_ids.length ? 0 : 1)
    )
      return false;
    itemIds.add(item.item_id);
    factKeys.add(factKey);
    for (const ref of item.references) {
      if (
        !aligned(ref, "fact") ||
        !factReasons.has(ref.reason) ||
        ref.missing_information.length !== 1
      )
        return false;
      const gap = ref.missing_information[0];
      if (
        gap !== `reliable current patient ${item.fact_name}` &&
        gap !== `${item.fact_name} in ${item.requested_unit}`
      )
        return false;
      if (
        item.fact_name === "sex"
          ? item.requested_unit !== null
          : !item.requested_unit
      )
        return false;
      if (
        gap === `reliable current patient ${item.fact_name}` &&
        item.fact_name !== "sex"
      ) {
        const quantity = z.object({
          name: z.string(),
          unit: z.string(),
          evidence: span,
        });
        const units = new Set(
          a.parsed.criteria
            .filter((c) => ref.criterion_ids.includes(c.criterion_id))
            .flatMap((c) => c.constraints)
            .flatMap((c) => {
              const parsed = quantity.safeParse(c);
              return parsed.success &&
                parsed.data.name === item.fact_name &&
                parsed.data.evidence.start >= ref.evidence.start &&
                parsed.data.evidence.end <= ref.evidence.end
                ? [parsed.data.unit]
                : [];
            }),
        );
        if (item.fact_name === "age" && units.size === 0) {
          for (const m of ref.evidence.text
            .toLowerCase()
            .matchAll(/\b(year|month|week|day)s?\b/g))
            units.add(m[1]);
        }
        if (units.size !== 1 || !units.has(item.requested_unit!)) return false;
      }
    }
  }
  const compareText = (x: string, y: string) => (x < y ? -1 : x > y ? 1 : 0);
  const ordered = [...p.items].sort(
    (x, y) =>
      y.unblocked_trial_count - x.unblocked_trial_count ||
      y.criterion_count - x.criterion_count ||
      y.trial_count - x.trial_count ||
      compareText(x.fact_name, y.fact_name) ||
      compareText(x.requested_unit ?? "", y.requested_unit ?? ""),
  );
  return (
    same(
      ordered.map((i) => i.item_id),
      p.items.map((i) => i.item_id),
    ) &&
    p.interpretation_reviews.every((r) => aligned(r, "interpretation")) &&
    p.settled_branch_reviews.every((r) => aligned(r, "settled")) &&
    seen.size === expected.size
  );
}
