import { expect, test } from "@playwright/test";

test.use({
  colorScheme: "light",
  video: { mode: "on", size: { width: 1280, height: 900 } },
  viewport: { width: 1280, height: 900 },
});

test("record the synthetic research portfolio walkthrough", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_RELEASE_DEMO !== "1",
    "Explicit local demo recording opt-in",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("Services ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dark mode", exact: true }).click();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page
    .getByRole("button", { name: "Search trials", exact: true })
    .click();
  await expect(page.getByText("0.4734", { exact: true })).toBeVisible({
    timeout: 60000,
  });
  await page.mouse.move(100, 80);
  await page
    .getByRole("heading", { name: /^Retrieved trials/ })
    .evaluate((element) => {
      window.scrollTo(
        0,
        element.getBoundingClientRect().top + window.scrollY - 90,
      );
    });
  await page.screenshot({
    path: "test-results/demo/01-search.png",
    fullPage: false,
  });
  await page.waitForTimeout(5000);
  await page.getByRole("button", { name: "View trial NCT01726751" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: "test-results/demo/02-trial-source.png" });
  await page.waitForTimeout(5000);
  await page.keyboard.press("Escape");

  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("reranking-demo");
  await page
    .getByRole("button", { name: "Eligibility evidence", exact: true })
    .click();
  await page.getByLabel("Trial to screen").selectOption("NCT90009001");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Screen selected pair" }).click();
  await expect(
    page.getByText("insufficient information", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await page.mouse.move(100, 80);
  await page
    .getByRole("heading", { name: "Eligibility evidence", exact: true })
    .evaluate((element) => {
      window.scrollTo(
        0,
        element.getBoundingClientRect().top + window.scrollY - 90,
      );
    });
  await page.screenshot({
    path: "test-results/demo/03-screening.png",
    fullPage: false,
  });
  await page
    .getByText("Learned NLI advisory · NOT PROMOTED")
    .last()
    .scrollIntoViewIfNeeded();
  await page.waitForTimeout(5000);

  await page
    .getByRole("button", { name: "Retrieval laboratory", exact: true })
    .click();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByText("Observed ranking comparison")).toBeVisible({
    timeout: 60000,
  });
  await page.getByText("Observed ranking comparison").evaluate((element) => {
    window.scrollTo(
      0,
      element.getBoundingClientRect().top + window.scrollY - 90,
    );
  });
  await page.mouse.move(100, 80);
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "test-results/demo/04-comparison.png",
  });
  await page.waitForTimeout(5000);

  await page
    .getByRole("button", { name: "Experiment dashboard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run authored screening evaluation" })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "exact pairs" }),
  ).toContainText("34/34 exact pairs; 41 criteria", { timeout: 60000 });
  await page
    .getByText("Authored screening evaluation", { exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/demo/05-experiment.png",
  });
  await page.waitForTimeout(5000);
  await page
    .getByRole("button", { name: "About the project", exact: true })
    .click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(
    page.getByRole("heading", { name: "The purpose behind the project." }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/demo/06-about-dark.png" });
  await page.waitForTimeout(5000);
  await page.getByRole("button", { name: "Dark mode", exact: true }).click();
  await page.screenshot({ path: "test-results/demo/07-about-light.png" });
  await page.waitForTimeout(5000);
  expect(errors).toEqual([]);
});
