import { z } from "zod";
import { profileSchema, screeningStatus } from "./contracts";
import type { Assessment } from "./workbenchContracts";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const span = profileSchema.shape.facts.element.shape.evidence;
export type LogicNode = {
  node_id: string;
  operator:
    "atom" | "unknown" | "and" | "or" | "not" | "implies" | "waiver" | "except";
  evidence: z.infer<typeof span>;
  criterion_ids: string[];
  children: LogicNode[];
  truth: "true" | "false" | "unknown";
  fact_ids: string[];
  reason: string;
  missing_information: string[];
};
const node: z.ZodType<LogicNode> = z.lazy(() =>
  z.object({
    node_id: hash,
    operator: z.enum([
      "atom",
      "unknown",
      "and",
      "or",
      "not",
      "implies",
      "waiver",
      "except",
    ]),
    evidence: span,
    criterion_ids: z.array(hash),
    children: z.array(node).max(256),
    truth: z.enum(["true", "false", "unknown"]),
    fact_ids: z.array(hash),
    reason: z.string(),
    missing_information: z.array(z.string()),
  }),
);
export const groupedSchema = z.object({
  schema_version: z.literal("grouped-screening-v1"),
  implementation_sha256: hash,
  baseline_assessment_id: hash,
  case_id: z.string(),
  trial_id: z.string(),
  source_sha256: hash,
  source_text_sha256: hash,
  parser_sha256: hash,
  sections: z.array(
    z.object({
      section: z.enum(["inclusion", "exclusion", "unknown"]),
      ordinal: z.number().int().positive(),
      root: node,
    }),
  ),
  status: screeningStatus,
  blocking_node_ids: z.array(hash),
  unknown_section_node_ids: z.array(hash),
  missing_information: z.array(z.string()),
  scope_review_required: z.boolean(),
  applicable_inclusion_supported: z.boolean(),
  requires_professional_review: z.literal(true),
  default_screening_changed: z.literal(false),
  clinical_validation: z.literal(false),
});
export type Grouped = z.infer<typeof groupedSchema>;

export function groupedAligns(g: Grouped, a: Assessment): boolean {
  if (
    g.baseline_assessment_id !== a.assessment_id ||
    g.case_id !== a.profile.case.case_id ||
    g.trial_id !== a.parsed.source.trial_id ||
    g.source_sha256 !== a.parsed.source.source_sha256 ||
    g.source_text_sha256 !== a.parsed.text_sha256 ||
    g.parser_sha256 !== a.parsed.parser_sha256
  )
    return false;
  const facts = new Set(a.profile.facts.map((f) => f.fact_id));
  const ids = new Set(a.parsed.criteria.map((c) => c.criterion_id));
  const retained = new Set<string>();
  let count = 0;
  const visit = (n: LogicNode, depth: number): boolean => {
    if (++count > 256 || depth > 40) return false;
    const e = n.evidence;
    if (
      Array.from(a.parsed.source.text).slice(e.start, e.end).join("") !==
        e.text ||
      n.fact_ids.some((id) => !facts.has(id)) ||
      n.criterion_ids.some((id) => !ids.has(id)) ||
      (n.truth !== "unknown" && n.fact_ids.length === 0)
    )
      return false;
    n.criterion_ids.forEach((id) => retained.add(id));
    return n.children.every(
      (c) =>
        e.start <= c.evidence.start &&
        c.evidence.end <= e.end &&
        visit(c, depth + 1),
    );
  };
  if (!g.sections.every((s) => visit(s.root, 0)) || retained.size !== ids.size)
    return false;
  const blockers = g.sections
    .filter((s) =>
      s.section === "inclusion"
        ? s.root.truth === "false"
        : s.section === "exclusion" && s.root.truth === "true",
    )
    .map((s) => s.root.node_id);
  const unknown = g.sections
    .filter((s) => s.root.truth === "unknown")
    .map((s) => s.root.node_id);
  const status = blockers.length
    ? "likely_exclusion"
    : unknown.length ||
        !g.applicable_inclusion_supported ||
        !g.sections.some((s) => s.section === "inclusion")
      ? "insufficient_information"
      : "potential_match";
  return (
    status === g.status &&
    JSON.stringify(blockers) === JSON.stringify(g.blocking_node_ids) &&
    JSON.stringify(unknown) === JSON.stringify(g.unknown_section_node_ids) &&
    (!g.scope_review_required ||
      (blockers.length === 0 &&
        g.sections.every((s) => s.root.truth === "unknown")))
  );
}
