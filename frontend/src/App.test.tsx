import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { api } from "./api/client";
import {
  caseId,
  caseItem,
  profile,
  search,
  trial,
  trialId,
} from "./test/fixtures";

beforeEach(() => {
  vi.spyOn(api, "cases").mockResolvedValue([
    caseItem,
    { ...caseItem, case_id: "other-case" },
  ]);
  vi.spyOn(api, "ready").mockResolvedValue({
    status: "ready",
    catalog_id: "invented",
    model_loading: "lazy",
  });
  vi.spyOn(api, "profile").mockImplementation(async (id) => ({
    ...profile,
    case: { ...profile.case, case_id: id },
  }));
  vi.spyOn(api, "search").mockResolvedValue(search);
  vi.spyOn(api, "trial").mockResolvedValue(trial);
  vi.spyOn(api, "trials").mockResolvedValue({
    total: 1,
    limit: 20,
    offset: 0,
    items: [
      {
        trial_id: trialId,
        title: "Invented research trial",
        source_kind: "invented_trial_fixture",
      },
    ],
  });
});
async function selectCase() {
  const user = userEvent.setup();
  render(<App />);
  await user.selectOptions(
    await screen.findByLabelText("Choose a synthetic case"),
    caseId,
  );
  await screen.findByText(profile.case.text);
  return user;
}
it("requires a catalog choice, exposes no narrative input and renders fact uncertainty", async () => {
  const user = await selectCase();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getByText("present")).toBeInTheDocument();
  expect(screen.getByText("current")).toBeInTheDocument();
  expect(
    screen.getByText(/condition, medication, measurement/),
  ).toBeInTheDocument();
  await user.click(screen.getByText("Source evidence"));
  expect(screen.getByText("40 year old")).toBeInTheDocument();
});
it("searches the selected case and keeps relevance, unknown screening and replay separate", async () => {
  vi.mocked(api.search).mockResolvedValue({ ...search, replayed: true });
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  expect(await screen.findByText("Saved replay")).toBeInTheDocument();
  expect(screen.getByText("0.4321")).toBeInTheDocument();
  expect(screen.getByText("insufficient information")).toBeInTheDocument();
  expect(api.search).toHaveBeenCalledWith(caseId, 3, expect.any(AbortSignal));
  expect(
    screen.getByText("Cosine similarity · not eligibility"),
  ).toBeInTheDocument();
});
it("clears old results when changing the case", async () => {
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  await screen.findByText("Invented research trial");
  await user.selectOptions(
    screen.getByLabelText("Choose a synthetic case"),
    "other-case",
  );
  expect(screen.queryByText("Invented research trial")).not.toBeInTheDocument();
});
it("discards a late search response after switching cases", async () => {
  let finish!: (value: typeof search) => void;
  vi.mocked(api.search).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  await user.selectOptions(
    screen.getByLabelText("Choose a synthetic case"),
    "other-case",
  );
  await act(async () => finish(search));
  expect(screen.queryByText("Invented research trial")).not.toBeInTheDocument();
  expect(vi.mocked(api.search).mock.calls[0][2].aborted).toBe(true);
});
it("does not submit a second expensive request while busy", async () => {
  vi.mocked(api.search).mockImplementation(() => new Promise(() => {}));
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  expect(screen.getByRole("button", { name: /Searching/ })).toBeDisabled();
  expect(api.search).toHaveBeenCalledTimes(1);
});
it("shows a retryable service error and recovers", async () => {
  vi.mocked(api.search).mockRejectedValueOnce(
    new Error("A local service is unavailable."),
  );
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByText("Invented research trial"),
  ).toBeInTheDocument();
});
it("shows empty results without claiming there are no relevant trials", async () => {
  vi.mocked(api.search).mockResolvedValue({
    ...search,
    result: { ...search.result, results: [], candidate_count: 0 },
  });
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  expect(await screen.findByText("No candidates returned")).toBeInTheDocument();
  expect(
    screen.getByText(/does not establish that no relevant trial exists/),
  ).toBeInTheDocument();
});
it("opens full trial criteria and closes the dialog", async () => {
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  await user.click(
    await screen.findByRole("button", { name: `View trial ${trialId}` }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByText("Parsed criteria"),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByText(/not a patient–criterion assessment/),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByText("Requires review: requires context"),
  ).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "Close detail" }),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("shows trial lookup failures rather than a stale detail", async () => {
  vi.mocked(api.trial).mockRejectedValue(
    new Error("Evidence validation failed."),
  );
  const user = await selectCase();
  await user.click(screen.getByRole("button", { name: /Search trials/ }));
  await user.click(
    await screen.findByRole("button", { name: `View trial ${trialId}` }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Evidence validation failed",
  );
});
it("supports trial browsing independently of case selection", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /Trial catalog/ }));
  await waitFor(() =>
    expect(screen.getByText("1–1 of 1 trials")).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "Next trials" })).toBeDisabled();
});
