import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { groupedAligns, type Grouped } from "./api/groupedContracts";
import { retrievalSchema } from "./api/contracts";
import { screeningSchema } from "./api/workbenchContracts";
import { workbench } from "./api/workbench";
import { GroupedEvidence } from "./components/GroupedEvidence";
import { ScreeningWorkspace } from "./components/ScreeningWorkspace";
import { RetrievalLab } from "./components/RetrievalLab";
import { Results } from "./components/Results";
import { assessment, screening } from "./test/workbenchFixtures";
import { hash, search, caseId, trialId } from "./test/fixtures";

function grouped(): Grouped {
  return {
    schema_version: "grouped-screening-v1",
    implementation_sha256: hash,
    baseline_assessment_id: assessment.assessment_id,
    case_id: caseId,
    trial_id: trialId,
    source_sha256: assessment.parsed.source.source_sha256,
    source_text_sha256: String(assessment.parsed.text_sha256 ?? hash),
    parser_sha256: assessment.parsed.parser_sha256,
    sections: [
      {
        section: "inclusion",
        ordinal: 1,
        root: {
          node_id: hash,
          operator: "unknown",
          evidence: assessment.parsed.criteria[0].evidence,
          criterion_ids: [hash],
          children: [],
          truth: "unknown",
          fact_ids: [],
          reason: "unsupported_invented_predicate",
          missing_information: ["criterion interpretation"],
        },
      },
    ],
    status: "insufficient_information",
    blocking_node_ids: [],
    unknown_section_node_ids: [hash],
    missing_information: ["criterion interpretation"],
    scope_review_required: true,
    applicable_inclusion_supported: false,
    requires_professional_review: true,
    default_screening_changed: false,
    clinical_validation: false,
  };
}
function alignedAssessment() {
  const a = structuredClone(assessment);
  a.parsed.text_sha256 = hash;
  return a;
}
it("validates grouped source identity and rejects tampered spans or summaries", () => {
  const a = alignedAssessment(),
    g = grouped();
  expect(groupedAligns(g, a)).toBe(true);
  expect(groupedAligns({ ...g, trial_id: "NCT00000001" }, a)).toBe(false);
  const wrong = structuredClone(g);
  wrong.sections[0].root.evidence.text = "invented replacement";
  expect(groupedAligns(wrong, a)).toBe(false);
  expect(groupedAligns({ ...g, status: "potential_match" }, a)).toBe(false);
  const p = {
    ...screening,
    request: { ...screening.request, grouped: true },
    result: { ...screening.result, assessment: a, grouped: g },
  };
  expect(screeningSchema.safeParse(p).success).toBe(true);
  expect(
    screeningSchema.safeParse({ ...p, request: screening.request }).success,
  ).toBe(false);
});
it("shows grouped logic as a separate experimental interpretation", () => {
  render(
    <GroupedEvidence grouped={grouped()} assessment={alignedAssessment()} />,
  );
  expect(screen.getByText(/Grouped screening/)).toBeVisible();
  expect(
    screen.getByText(/all section conclusions remain unknown/),
  ).toBeVisible();
  expect(
    screen.getByText(/false OR branch alone is not a blocker/),
  ).toBeVisible();
});
it("requests grouped screening only after explicit selection", async () => {
  const user = userEvent.setup();
  vi.spyOn(workbench, "trialChoices").mockResolvedValue([
    {
      trial_id: trialId,
      title: "Invented",
      source_kind: "invented_trial_fixture",
    },
  ]);
  const stub = vi.spyOn(workbench, "screen").mockResolvedValue(screening);
  render(<ScreeningWorkspace caseId={caseId} openTrial={() => {}} />);
  await user.selectOptions(
    await screen.findByLabelText("Trial to screen"),
    trialId,
  );
  await user.click(
    screen.getByLabelText("Compare experimental grouped eligibility logic"),
  );
  await user.click(
    screen.getByRole("button", { name: "Screen selected pair" }),
  );
  expect(stub).toHaveBeenCalledWith(
    caseId,
    trialId,
    false,
    expect.any(AbortSignal),
    true,
  );
});
it("offers passage retrieval without changing ordinary defaults", async () => {
  const user = userEvent.setup();
  render(<RetrievalLab caseId={caseId} openTrial={() => {}} />);
  await user.selectOptions(
    screen.getByLabelText("Retrieval method"),
    "field_passages",
  );
  expect(screen.getByText(/separately prepared 443-trial/)).toBeVisible();
});
function passageSearch() {
  const p = structuredClone(search);
  p.request.method = p.result.method = "field_passages";
  p.result.passage_retrieval = {
    version: "field-passages-v1",
    benchmark_comparable: false,
  };
  const r = p.result.results[0];
  r.relevance.ranking.score_kind = "reciprocal_rank_fusion";
  r.relevance.ranking.branches = {
    brief_summary: {
      rank: 1,
      raw_score: 0.5,
      score_kind: "cosine_similarity",
      rrf_contribution: 1 / 61,
      segment: {
        trial_id: r.trial_id,
        field: "brief_summary",
        text: "An invented retrieved passage.",
        source_sha256: hash,
        locator: "/clinical_study/brief_summary/textblock",
        original_item: 0,
        start: 0,
        end: 29,
      },
    },
  };
  return p;
}
it("shows source-linked contributing passages and keeps raw scales separate", async () => {
  const p = passageSearch();
  expect(retrievalSchema.safeParse(p).success).toBe(true);
  const user = userEvent.setup();
  render(<Results search={p} openTrial={() => {}} />);
  await user.click(screen.getByText("Contributing fields and passages"));
  expect(screen.getByText("An invented retrieved passage.")).toBeVisible();
  expect(screen.getByText(/Cosine 0.5000 · RRF contribution/)).toBeVisible();
  const wrong = structuredClone(p);
  const branch = wrong.result.results[0].relevance.ranking.branches as Record<
    string,
    { rrf_contribution: number }
  >;
  branch.brief_summary.rrf_contribution = 100;
  expect(retrievalSchema.safeParse(wrong).success).toBe(false);
});
