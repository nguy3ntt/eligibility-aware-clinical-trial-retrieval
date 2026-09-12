import { expect, test } from "@playwright/test";

test("real evidence, optional NLI, ranking comparisons and persisted experiments", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit local model/database opt-in",
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("reranking-demo");
  await page
    .getByRole("button", { name: "Eligibility evidence", exact: true })
    .click();
  await page.getByLabel("Trial to screen").selectOption("NCT90009002");
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(page.getByText("potential match", { exact: true })).toBeVisible({
    timeout: 180000,
  });
  await expect(page.getByText("Synthetic fact evidence").first()).toBeVisible();
  await page.getByLabel("Trial to screen").selectOption("NCT90009003");
  await expect(page.getByText("potential match", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(page.getByText("likely exclusion", { exact: true })).toBeVisible(
    { timeout: 180000 },
  );
  await page.getByLabel("Trial to screen").selectOption("NCT90009001");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(
    page.getByText("insufficient information", { exact: true }),
  ).toBeVisible({ timeout: 180000 });
  await expect(
    page.getByText("Learned NLI advisory · NOT PROMOTED").first(),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/eligibility-evidence.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Retrieval laboratory", exact: true })
    .click();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByText("Observed ranking comparison")).toBeVisible({
    timeout: 180000,
  });
  await expect(
    page.getByText("RRF score · not eligibility").first(),
  ).toBeVisible();
  await page
    .getByText("Baseline results and evidence", { exact: true })
    .click();
  const ids = await page
    .locator("[id]")
    .evaluateAll((nodes) => nodes.map((n) => n.id));
  expect(new Set(ids).size).toBe(ids.length);
  await page.getByLabel("Retrieval method").selectOption("sparse");
  await page.getByLabel("Metadata filter").selectOption("none");
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(
    page.getByText("BM25 score · not eligibility").first(),
  ).toBeVisible({ timeout: 30000 });
  await page.getByLabel("Metadata filter").selectOption("age_sex");
  await page.getByLabel("Retrieval method").selectOption("dense");
  await page.getByLabel("Fact extractor").selectOption("profile");
  await page
    .getByRole("checkbox", { name: "Opt into cross-encoder reranking" })
    .check();
  await page.getByLabel("Reranked prefix").selectOption("10");
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(
    page.getByText("Learned cross-encoder:", { exact: false }).first(),
  ).toBeVisible({ timeout: 180000 });
  await page.screenshot({
    path: "test-results/retrieval-laboratory.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await expect(page.getByText("No reranking", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Legacy age / sex", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Experiment dashboard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run authored screening evaluation" })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "exact pairs" }),
  ).toContainText("34/34 exact pairs; 41 criteria", { timeout: 180000 });
  await expect(
    page.getByText("Authored screening evaluation", { exact: true }),
  ).toBeVisible();
  const sourceId = await page
    .getByLabel("Stored operation identity")
    .innerText();
  await page.reload();
  await page
    .getByRole("button", { name: "Experiment dashboard", exact: true })
    .click();
  await page.getByLabel("Saved operation ID").fill(sourceId);
  await page
    .getByRole("button", { name: "Open saved operation", exact: true })
    .click();
  await expect(
    page.getByText("Authored screening evaluation", { exact: true }),
  ).toBeVisible();
  // Inspect an existing immutable imported report, without importing or rerunning it.
  let historical = "";
  for (let offset = 0; offset < 10000; offset += 20) {
    const p = await (
      await page.request.get(`/v1/experiments?limit=20&offset=${offset}`)
    ).json();
    historical =
      p.items.find((v: { kind: string }) => v.kind === "reviewed_experiment")
        ?.operation_id ?? "";
    if (historical || offset + 20 >= p.total) break;
  }
  expect(historical).toMatch(/^[a-f0-9]{64}$/);
  await page.getByLabel("Saved operation ID").fill(historical);
  await page
    .getByRole("button", { name: "Open saved operation", exact: true })
    .click();
  await expect(
    page.getByText("Historical experiment", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "0.5584", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/experiment-dashboard.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
