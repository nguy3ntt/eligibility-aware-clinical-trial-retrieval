import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeToggle } from "./components/ThemeToggle";
import { About } from "./components/About";
import { Results } from "./components/Results";
import { titleSegments } from "./components/ResultInsights";
import { search, trialId } from "./test/fixtures";

beforeEach(() => localStorage.clear());
afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

it("uses system dark mode and remembers an explicit choice across remounts", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const user = userEvent.setup();
  const view = render(<ThemeToggle />);
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  await user.click(screen.getByRole("button", { name: "Dark mode" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(localStorage.getItem("themis-trial-theme")).toBe("light");
  view.unmount();
  render(<ThemeToggle />);
  expect(screen.getByRole("button", { name: "Dark mode" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

it("still toggles safely when storage is blocked", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  render(<ThemeToggle />);
  await userEvent.click(screen.getByRole("button", { name: "Dark mode" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});

it("preserves original title text and highlights only whole source-topic words", () => {
  const title = "A trial of Bowel Pain: Painful disease and café.";
  const parts = titleSegments(title, "bowel pain café disease trial");
  expect(parts.map((p) => p.text).join("")).toBe(title);
  expect(parts.filter((p) => p.highlighted).map((p) => p.text)).toEqual([
    "Bowel Pain",
    "café",
  ]);
  expect(
    titleSegments("No supplied topics", "").every((p) => !p.highlighted),
  ).toBe(true);
});

it("shows honest raw-score context on hover and supports touch, keyboard and dismissal", async () => {
  const packet = structuredClone(search);
  packet.result.results[0].relevance.fields.brief_title.normalized =
    "An asthma trial";
  packet.result.results[0].relevance.fields.conditions = {
    normalized: "Asthma",
  };
  const original = structuredClone(packet);
  const user = userEvent.setup();
  const { container } = render(<Results search={packet} openTrial={vi.fn()} />);
  expect(container.querySelector("mark")).toHaveTextContent("asthma");
  const card = container.querySelector(".result-card")!;
  fireEvent.mouseEnter(card);
  const panel = screen.getByRole("region", {
    name: `Result details for ${trialId}`,
  });
  expect(
    within(panel).getByText(/not calibrated match percentages/),
  ).toBeInTheDocument();
  expect(within(panel).getByText("0.4321")).toBeInTheDocument();
  expect(within(panel).queryByText(/43.21%/)).not.toBeInTheDocument();
  fireEvent.mouseLeave(card);
  expect(
    screen.queryByRole("region", { name: /Result details for/ }),
  ).not.toBeInTheDocument();
  const button = screen.getByRole("button", { name: /Result details/ });
  button.focus();
  await user.keyboard("{Enter}");
  expect(button).toHaveAttribute("aria-expanded", "true");
  await user.keyboard("{Escape}");
  expect(button).toHaveAttribute("aria-expanded", "false");
  await user.click(button);
  await user.click(
    screen.getByRole("button", { name: "Close result details" }),
  );
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(packet).toEqual(original);
  expect(button).toHaveFocus();
});

it("keeps About independent of services and uses the repository owner's public links", () => {
  render(<About />);
  expect(
    screen.getByText(/academic portfolio and research demonstration/),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /GitHub profile/ })).toHaveAttribute(
    "href",
    "https://github.com/nguy3ntt",
  );
  expect(
    screen.getByRole("link", { name: /Explore the source/ }),
  ).toHaveAttribute("rel", "noopener noreferrer");
  expect(
    screen.getByText(/not held-out or clinical validation/),
  ).toBeInTheDocument();
});

it.each(["dense", "sparse", "hybrid"] as const)(
  "keeps %s scores separate from negative reranker logits",
  (method) => {
    const packet = structuredClone(search);
    packet.request.method = packet.result.method = method;
    packet.request.rerank = true;
    packet.result.reranker = { version: "invented" };
    packet.result.results[0].relevance.ranking.reranker = {
      score: -2.5,
      method: "learned_cross_encoder",
      input: {},
    };
    const { container } = render(
      <Results search={packet} openTrial={vi.fn()} />,
    );
    fireEvent.mouseEnter(container.querySelector(".result-card")!);
    const panel = screen.getByRole("region", { name: /Result details for/ });
    expect(
      within(panel).getByText(
        {
          dense: "Cosine similarity",
          sparse: "BM25 score",
          hybrid: "RRF score",
        }[method],
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/-2.5000 · original rank 1/),
    ).toBeInTheDocument();
    expect(within(panel).getByText("0.4321")).toBeInTheDocument();
  },
);
