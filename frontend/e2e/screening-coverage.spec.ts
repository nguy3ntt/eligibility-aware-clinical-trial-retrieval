import { expect, test } from "@playwright/test";

test("actual v2 age checks retain evidence and unresolved requirements", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit actual-service opt-in",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page
    .getByRole("button", { name: "Eligibility evidence", exact: true })
    .click();
  await page.getByLabel("Trial to screen").selectOption("NCT00258570");
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/v1/screening") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  const packet = await (await response).json();
  expect(packet.result.assessment.verifier_version).toBe(
    "bounded-screening-rules-v2",
  );
  expect(packet.result.assessment.status).toBe("insufficient_information");
  const checks = page
    .locator(".criteria-list > li")
    .filter({ hasText: "whole-age-predicate-v2" });
  await expect(checks).toHaveCount(2);
  await expect(
    checks
      .first()
      .getByText(/The age rule checked the complete quoted requirement/),
  ).toBeVisible();
  await expect(
    checks.first().getByText("57-year-old", { exact: true }),
  ).toBeVisible();
  await checks.first().scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/screening-coverage-current.png",
  });
  expect(errors).toEqual([]);
});
