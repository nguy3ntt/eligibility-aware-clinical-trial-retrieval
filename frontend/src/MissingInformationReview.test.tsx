import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { reviewAligns, type ReviewPlan } from "./api/reviewContracts";
import { screeningSchema } from "./api/workbenchContracts";
import { MissingInformationReview } from "./components/MissingInformationReview";
import { assessment, screening } from "./test/workbenchFixtures";
import { hash } from "./test/fixtures";

function example() {
  const a = structuredClone(assessment),
    text = "Creatinine <= 1.5 mg/dL.";
  const evidence = { start: 0, end: text.length, text };
  a.parsed.source.text = text;
  a.parsed.text_sha256 = hash;
  a.parsed.criteria[0].evidence = evidence;
  a.parsed.criteria[0].constraints = [
    { name: "creatinine", unit: "mg/dL", evidence },
  ];
  a.criteria[0].evidence = evidence;
  a.criteria[0].reason = "missing_uncertain_or_unanchored_patient_evidence";
  a.criteria[0].missing_information = ["reliable current patient creatinine"];
  a.missing_information = a.criteria[0].missing_information;
  const ref = {
    reference_id: "b".repeat(64),
    assessment_id: a.assessment_id,
    trial_id: a.parsed.source.trial_id,
    criterion_ids: [hash],
    node_id: null,
    evidence,
    fact_ids: [],
    reason: a.criteria[0].reason,
    missing_information: a.criteria[0].missing_information,
  };
  const plan: ReviewPlan = {
    schema_version: "missing-information-review-v1",
    plan_id: "c".repeat(64),
    implementation_sha256: hash,
    case_id: a.profile.case.case_id,
    case_text_sha256: a.profile.narrative_sha256,
    mode: "ordinary",
    basis: [
      {
        assessment_id: a.assessment_id,
        trial_id: ref.trial_id,
        source_sha256: hash,
        source_text_sha256: hash,
        status: a.status,
        blocking_ids: [],
        grouped_sha256: null,
        scope_review_required: false,
      },
    ],
    items: [
      {
        item_id: "d".repeat(64),
        rank: 1,
        fact_name: "creatinine",
        requested_unit: "mg/dL",
        prompt: "Review existing synthetic evidence; do not order a test.",
        unblocked_trial_count: 1,
        trial_count: 1,
        criterion_count: 1,
        references: [ref],
      },
    ],
    interpretation_reviews: [],
    settled_branch_reviews: [],
    ordering: "unblocked_trials_then_source_criteria_then_trials_then_fact_key",
    method: "deterministic_review_order",
    changes_screening: false,
    clinical_urgency: false,
    estimated_information_gain: null,
    requires_professional_review: true,
  };
  return {
    ...structuredClone(screening),
    result: {
      assessment: a,
      explanation: {},
      semantic: null,
      review_plan: plan,
    },
  };
}

it("accepts source-aligned review plans and keeps historical packets readable", () => {
  expect(screeningSchema.safeParse(example()).success).toBe(true);
  expect(screeningSchema.safeParse(screening).success).toBe(true);
});
it.each([
  "case_hash",
  "source",
  "reason",
  "fact",
  "unit",
  "count",
  "duplicate",
  "omitted",
  "settled",
  "rank",
  "clinical",
])("rejects damaged review evidence: %s", (damage) => {
  const p = example(),
    plan = p.result.review_plan,
    item = plan.items[0];
  if (damage === "case_hash") plan.case_text_sha256 = "e".repeat(64);
  if (damage === "source") item.references[0].evidence.text = "Changed source";
  if (damage === "reason") item.references[0].reason = "unsupported_predicate";
  if (damage === "fact") item.fact_name = "age";
  if (damage === "unit") item.requested_unit = "g/dL";
  if (damage === "count") item.criterion_count = 10;
  if (damage === "duplicate") plan.interpretation_reviews = item.references;
  if (damage === "omitted") plan.items = [];
  if (damage === "settled") {
    plan.settled_branch_reviews = item.references;
    plan.items = [];
  }
  if (damage === "rank") item.rank = 2;
  if (damage === "clinical") Object.assign(plan, { clinical_urgency: true });
  expect(screeningSchema.safeParse(p).success).toBe(false);
});
it("presents evidence counts without implying urgency or eligibility", () => {
  render(<MissingInformationReview plan={example().result.review_plan} />);
  expect(
    screen.getByRole("heading", { name: "Prioritised information review" }),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "1. Verify creatinine (mg/dL)" }),
  ).toBeVisible();
  expect(screen.getByText(/not clinical urgency/)).toBeVisible();
  expect(screen.getByText(/Only the selected case–trial pair/)).toBeVisible();
});
it("does not manufacture a plan when opening historical evidence", () => {
  render(<MissingInformationReview />);
  expect(screen.getByText(/No review ordering was recorded/)).toBeVisible();
});
it("keeps unsupported interpretation separate from missing facts", () => {
  const p = example(),
    ref = p.result.review_plan.items[0].references[0];
  ref.reason = p.result.assessment.criteria[0].reason =
    "unsupported_or_incomplete_predicate";
  ref.missing_information =
    p.result.assessment.criteria[0].missing_information = [
      "criterion interpretation",
    ];
  p.result.assessment.missing_information = ["criterion interpretation"];
  p.result.review_plan.items = [];
  p.result.review_plan.interpretation_reviews = [ref];
  expect(reviewAligns(p.result.review_plan, p.result.assessment)).toBe(true);
  render(<MissingInformationReview plan={p.result.review_plan} />);
  expect(
    screen.getByText(/not requests for additional patient facts/),
  ).toBeVisible();
  expect(screen.getByText(/No active fact-review items/)).toBeVisible();
});
