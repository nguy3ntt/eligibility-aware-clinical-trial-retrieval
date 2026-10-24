import { expect, test } from "@playwright/test";

test("actual review worklist preserves blockers, separates interpretation and replays evidence", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit prepared local-service opt-in",
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
  await page.getByLabel("Trial to screen").selectOption("NCT90009001");
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/v1/screening") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  const packet = await (await response).json();
  const plan = packet.result.review_plan;
  expect(plan.schema_version).toBe("missing-information-review-v1");
  expect(plan.changes_screening).toBe(false);
  expect(plan.basis[0].assessment_id).toBe(
    packet.result.assessment.assessment_id,
  );
  await expect(
    page.getByRole("heading", { name: "Prioritised information review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "1. Verify creatinine (mg/dL)" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(page.getByText(/Saved replay/).first()).toBeVisible();
  await page.getByLabel("Trial to screen").selectOption("NCT90009003");
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(
    page.getByText(/Existing likely exclusion blockers remain/),
  ).toBeVisible();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page.getByLabel("Trial to screen").selectOption("NCT00258570");
  await page
    .getByLabel("Compare experimental grouped eligibility logic")
    .check();
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(
    page.getByRole("heading", { name: "Prioritised information review" }),
  ).toBeVisible();
  await expect(page.getByText(/Criterion interpretation first/)).toBeVisible();
  expect(errors).toEqual([]);
});
