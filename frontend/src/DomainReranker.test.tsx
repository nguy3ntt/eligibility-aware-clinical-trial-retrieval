import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { retrievalSchema } from "./api/contracts";
import { defaults, workbench } from "./api/workbench";
import { Results } from "./components/Results";
import { RetrievalLab } from "./components/RetrievalLab";
import { caseId, hash, search } from "./test/fixtures";

function adapted() {
  const packet = structuredClone(search);
  packet.request.rerank = true;
  packet.request.reranker_variant = "domain_hard";
  packet.result.reranker = {
    variant: "domain_hard",
    promoted: false,
    adapter_manifest_sha256: hash,
    selected_epoch: 0,
    case_exposure: "train",
  };
  packet.result.results[0].relevance.ranking.reranker = {
    score: 1.2,
    base_score: 1.2,
    method: "learned_cross_encoder",
    input: {},
    variant: "domain_hard",
    promoted: false,
    adapter_manifest_sha256: hash,
  };
  return packet;
}
it("validates explicit model identity and rejects silently substituted or promoted heads", () => {
  const p = adapted();
  expect(retrievalSchema.safeParse(p).success).toBe(true);
  expect(
    retrievalSchema.safeParse({
      ...p,
      request: { ...p.request, reranker_variant: "base" },
    }).success,
  ).toBe(false);
  expect(
    retrievalSchema.safeParse({
      ...p,
      request: { ...p.request, rerank: false },
    }).success,
  ).toBe(false);
  const broken = adapted();
  broken.result.reranker!.promoted = true;
  expect(retrievalSchema.safeParse(broken).success).toBe(false);
  const mismatch = adapted();
  mismatch.result.results[0].relevance.ranking.reranker!.adapter_manifest_sha256 =
    "b".repeat(64);
  expect(retrievalSchema.safeParse(mismatch).success).toBe(false);
});
it("shows case exposure and retained-original-head selection without implying improvement", () => {
  render(<Results search={adapted()} openTrial={() => {}} />);
  expect(screen.getByText(/Case exposure: train/)).toBeVisible();
  expect(
    screen.getByText(/retained the original head \(epoch 0\)/),
  ).toBeVisible();
  expect(screen.getByText(/NOT PROMOTED/)).toBeVisible();
});
it("requires opt-in and resets the model when reranking is disabled", async () => {
  const user = userEvent.setup();
  const stub = vi.spyOn(workbench, "retrieve").mockResolvedValue(search);
  render(<RetrievalLab caseId={caseId} openTrial={() => {}} />);
  expect(screen.getByLabelText("Reranker model")).toBeDisabled();
  await user.click(screen.getByLabelText("Opt into cross-encoder reranking"));
  await user.selectOptions(
    screen.getByLabelText("Reranker model"),
    "domain_hard",
  );
  expect(
    screen.getByText(/relevance-layer adaptation with a frozen/),
  ).toBeVisible();
  await user.click(screen.getByLabelText("Opt into cross-encoder reranking"));
  expect(screen.getByLabelText("Reranker model")).toHaveValue("base");
  expect(stub).not.toHaveBeenCalled();
  expect(defaults.rerank).toBe(false);
  expect(defaults.reranker_variant).toBeUndefined();
});
