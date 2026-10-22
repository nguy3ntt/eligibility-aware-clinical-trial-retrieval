import { expect, test } from "@playwright/test";

test("actual grouped evidence, field passages and saved replay preserve defaults", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit actual-service opt-in",
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
  await page
    .getByLabel("Compare experimental grouped eligibility logic")
    .check();
  const screened = page.waitForResponse(
    (r) => r.url().endsWith("/v1/screening") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  const packet = await (await screened).json();
  expect(packet.result.grouped.schema_version).toBe("grouped-screening-v1");
  expect(packet.result.assessment.verifier_version).toBe(
    "bounded-screening-rules-v2",
  );
  await expect(
    page.getByRole("heading", { name: "Grouped screening · experimental" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Retrieval laboratory", exact: true })
    .click();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page.getByLabel("Retrieval method").selectOption("field_passages");
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByText("Observed ranking comparison")).toBeVisible({
    timeout: 180000,
  });
  await page.getByText("Contributing fields and passages").first().click();
  await expect(page.getByText(/Best passage per field/).first()).toBeVisible();
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByText("Observed ranking comparison")).toBeVisible({
    timeout: 180000,
  });
  await expect(
    page.getByText("Saved replay", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await expect(page.getByText("No reranking", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Legacy age / sex", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
