import { expect, test } from "@playwright/test";
import {
  caseItem,
  profile,
  search,
  trial,
  trialId,
} from "../src/test/fixtures";

test("browser recovers from a catalog outage without exposing error payloads", async ({
  page,
}) => {
  let unavailable = true;
  await page.route("**/v1/**", (route) => {
    if (new URL(route.request().url()).pathname === "/v1/ready")
      return route.fulfill({
        json: {
          status: "ready",
          catalog_id: "invented",
          model_loading: "lazy",
        },
      });
    return unavailable
      ? route.fulfill({
          status: 503,
          json: { error: "INVENTED_DO_NOT_REFLECT" },
        })
      : route.fulfill({
          json: { total: 1, limit: 50, offset: 0, items: [caseItem] },
        });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("unavailable");
  await expect(page.getByText("INVENTED_DO_NOT_REFLECT")).toHaveCount(0);
  unavailable = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByLabel("Choose a synthetic case")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("keyboard workflow preserves meaning, dialog focus and mobile layout", async ({
  page,
}) => {
  await page.route("**/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const body =
      path === "/v1/ready"
        ? { status: "ready", catalog_id: "invented", model_loading: "lazy" }
        : path === "/v1/cases"
          ? { total: 1, limit: 50, offset: 0, items: [caseItem] }
          : path.startsWith("/v1/cases/")
            ? profile
            : path.startsWith("/v1/trials/")
              ? trial
              : search;
    return route.fulfill({ json: body });
  });
  await page.goto("/");
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption(caseItem.case_id);
  await page.getByRole("button", { name: "Search trials" }).click();
  await expect(
    page.getByText("insufficient information", { exact: true }),
  ).toBeVisible();
  const trigger = page.getByRole("button", { name: `View trial ${trialId}` });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText("Parsed criteria", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Search trials" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("real catalog, default search, facts and complete trial evidence", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit real PostgreSQL/Qdrant/model opt-in",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto("/");
  await expect(page.getByText("51 verified synthetic cases")).toBeVisible();
  await expect(page.getByText("Services ready", { exact: true })).toBeVisible();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await expect(
    page.getByText("Extracted facts", { exact: false }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Search trials" }).click();
  await expect(
    page.getByRole("button", { name: "View trial NCT01726751" }),
  ).toBeVisible({ timeout: 180000 });
  const cards = page.locator(".result-card");
  await expect(cards).toHaveCount(3);
  for (const [index, id] of [
    "NCT01726751",
    "NCT03325374",
    "NCT02749071",
  ].entries())
    await expect(cards.nth(index)).toContainText(id);
  await page.getByRole("button", { name: "Search trials" }).click();
  await expect(page.getByText("Saved replay", { exact: true })).toBeVisible({
    timeout: 180000,
  });
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "View trial NCT01726751" }).click();
  await expect(
    page.getByRole("dialog").getByText("Parsed criteria", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Complete original eligibility wording", { exact: true })
    .click();
  await expect(
    page.getByRole("dialog").locator(".criteria-list > li").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close detail" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/workspace-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Trial catalog", exact: true })
    .click();
  await expect(page.getByText("1–20 of 446 trials")).toBeVisible();
  await page.getByRole("button", { name: "Next trials" }).click();
  await expect(page.getByText("21–40 of 446 trials")).toBeVisible();
  expect(failures).toEqual([]);
});
