import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { workbench, defaults } from "./api/workbench";
import { ScreeningWorkspace } from "./components/ScreeningWorkspace";
import { RetrievalLab } from "./components/RetrievalLab";
import { Experiments } from "./components/Experiments";
import { EvidencePanel } from "./components/EvidencePanel";
import { OperationView } from "./components/OperationView";
import { caseId, hash, search, trialId } from "./test/fixtures";
import {
  assessment,
  fixtureExperiment,
  screening,
} from "./test/workbenchFixtures";

beforeEach(() => {
  vi.spyOn(workbench, "trialChoices").mockResolvedValue([
    {
      trial_id: trialId,
      title: "Invented trial",
      source_kind: "invented_trial_fixture",
    },
  ]);
  vi.spyOn(workbench, "screen").mockResolvedValue(screening);
  vi.spyOn(workbench, "retrieve").mockImplementation(async (id, options) => ({
    ...search,
    request: { case_id: id, ...options },
    result: {
      ...search.result,
      method: options.method,
      filter: options.filter,
      fact_extractor: options.fact_extractor,
    },
  }));
  vi.spyOn(workbench, "operations").mockResolvedValue({
    total: 1,
    limit: 20,
    offset: 0,
    items: [
      {
        operation_id: fixtureExperiment.operation_id,
        kind: "experiment",
        status: "complete",
      },
    ],
  });
  vi.spyOn(workbench, "operation").mockResolvedValue(fixtureExperiment);
  vi.spyOn(workbench, "experiment").mockResolvedValue(fixtureExperiment);
});
it("shows historical negative findings with model identity and limitations without rerunning", () => {
  render(
    <OperationView
      openTrial={() => {}}
      operation={{
        operation_id: hash,
        kind: "reviewed_experiment",
        status: "complete",
        source: { report_id: "invented-report", sha256: hash },
        notice: "Research only",
        result: {
          metrics: {
            baseline: { ndcg_at_10: 0.5 },
            candidate: { ndcg_at_10: 0.4 },
          },
          limitations: "Invented development diagnostic only.",
          promotion: { enabled: false, reason: "not_held_out" },
          model: { repository: "invented-model", revision: "pinned-demo" },
        },
      }}
    />,
  );
  expect(screen.getByRole("cell", { name: "0.4000" })).toBeInTheDocument();
  expect(screen.getByText(/not enabled/)).toBeInTheDocument();
  expect(
    screen.getByText(/Invented development diagnostic only/, { selector: "p" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/revision pinned-demo/)).toBeInTheDocument();
  expect(workbench.experiment).not.toHaveBeenCalled();
});
it("screens a selected pair and clears evidence when NLI selection changes", async () => {
  const user = userEvent.setup();
  render(<ScreeningWorkspace caseId={caseId} openTrial={() => {}} />);
  await user.selectOptions(
    await screen.findByLabelText("Trial to screen"),
    trialId,
  );
  await user.click(
    screen.getByRole("button", { name: "Screen selected pair" }),
  );
  expect(await screen.findByText("Eligibility evidence")).toBeInTheDocument();
  expect(
    screen.getAllByText(/invented missing measurement/).length,
  ).toBeGreaterThan(0);
  expect(workbench.screen).toHaveBeenCalledWith(
    caseId,
    trialId,
    false,
    expect.any(AbortSignal),
  );
  await user.click(screen.getByRole("checkbox"));
  expect(screen.queryByText("Eligibility evidence")).not.toBeInTheDocument();
});
it("keeps learned advice separate from unknown deterministic outcomes", () => {
  render(
    <EvidencePanel
      assessment={assessment}
      semantic={{
        model: {},
        advisories: [
          {
            criterion_id: hash,
            method: "learned_nli",
            promoted: false,
            status: "scored",
            proposed_outcome: "satisfied",
            patient_evidence: assessment.profile.case.text,
            criterion_evidence: assessment.criteria[0].evidence,
            probabilities: { entailment: 0.99 },
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("insufficient information")).toBeInTheDocument();
  expect(screen.getByText(/NOT PROMOTED/)).toBeInTheDocument();
  expect(screen.getByText("unknown", { exact: true })).toBeInTheDocument();
});
it("runs lab requests sequentially and shows distinct score meanings", async () => {
  const user = userEvent.setup();
  let release!: (v: typeof search) => void;
  vi.mocked(workbench.retrieve).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  render(<RetrievalLab caseId={caseId} openTrial={() => {}} />);
  await user.click(screen.getByRole("button", { name: "Run comparison" }));
  expect(workbench.retrieve).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Comparing…" })).toBeDisabled();
  await act(async () =>
    release({ ...search, request: { case_id: caseId, ...defaults } }),
  );
  expect(
    await screen.findByText("Observed ranking comparison"),
  ).toBeInTheDocument();
  expect(workbench.retrieve).toHaveBeenCalledTimes(2);
  expect(screen.getByText("RRF score · not eligibility")).toBeInTheDocument();
  expect(
    screen.getByText(/cached and fresh timings are not comparable/),
  ).toBeInTheDocument();
});
it("withholds a lab result if the second request fails and can retry", async () => {
  const user = userEvent.setup();
  vi.mocked(workbench.retrieve)
    .mockResolvedValueOnce(search)
    .mockRejectedValueOnce(new Error("Local service unavailable."));
  render(<RetrievalLab caseId={caseId} openTrial={() => {}} />);
  await user.click(screen.getByRole("button", { name: "Run comparison" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  expect(
    screen.queryByText("Observed ranking comparison"),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByText("Observed ranking comparison"),
  ).toBeInTheDocument();
});
it("cancels pending lab work when the case view unmounts", async () => {
  let signal!: AbortSignal;
  vi.mocked(workbench.retrieve).mockImplementation((_id, _opts, s) => {
    signal = s;
    return new Promise(() => {});
  });
  const user = userEvent.setup();
  const view = render(<RetrievalLab caseId={caseId} openTrial={() => {}} />);
  await user.click(screen.getByRole("button", { name: "Run comparison" }));
  view.unmount();
  expect(signal.aborted).toBe(true);
});
it("opens saved operations and runs only the authored experiment", async () => {
  const user = userEvent.setup();
  render(<Experiments openTrial={() => {}} />);
  await user.click(
    await screen.findByRole("button", {
      name: `Open ${fixtureExperiment.operation_id}`,
    }),
  );
  expect(
    await screen.findByText("Authored screening evaluation"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/not held-out or clinical validation/),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Run authored screening evaluation" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("2/2 exact pairs"),
  );
  expect(workbench.experiment).toHaveBeenCalledTimes(1);
});
it("shows empty saved history and a retryable lookup failure", async () => {
  vi.mocked(workbench.operations).mockResolvedValue({
    total: 0,
    limit: 20,
    offset: 0,
    items: [],
  });
  vi.mocked(workbench.operation).mockRejectedValue(
    new Error("Record unavailable."),
  );
  const user = userEvent.setup();
  render(<Experiments openTrial={() => {}} />);
  expect(
    await screen.findByText(/No saved operations yet/),
  ).toBeInTheDocument();
  await user.type(screen.getByLabelText("Saved operation ID"), hash);
  await user.click(
    screen.getByRole("button", { name: "Open saved operation" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Record unavailable",
  );
});
