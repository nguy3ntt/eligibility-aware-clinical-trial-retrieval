import { expect, test } from "@playwright/test";
import { caseItem, profile, search, trial } from "../src/test/fixtures";

test("actual source-topic emphasis and scores stay intact in dark mode", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit actual-service opt-in",
  );
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page
    .getByRole("button", { name: "Search trials", exact: true })
    .click();
  const card = page.locator(".result-card").first();
  await expect(card.getByText("0.4734", { exact: true })).toBeVisible({
    timeout: 60000,
  });
  await expect(card.locator(".eyebrow")).toHaveText("NCT01726751");
  await expect(card.locator("mark").first()).toBeVisible();
  await card.locator(".title-button").hover();
  const panel = page.getByRole("region", {
    name: "Result details for NCT01726751",
  });
  await expect(panel).toContainText("0.4734");
  await panel.getByText("Related source topics").click();
  await expect(panel).toContainText("Irritable Bowel Syndrome");
  await page.screenshot({
    path: "test-results/presentation/actual-details-dark.png",
  });
  await panel.getByRole("button", { name: "Close result details" }).click();
  await expect(
    card.getByText("insufficient information", { exact: true }),
  ).toBeVisible();
});

test("Themis branding, persistent dark mode, About and accessible source highlights", async ({
  page,
}) => {
  const packet = structuredClone(search);
  packet.result.results[0].relevance.fields.brief_title.normalized =
    "An asthma research trial";
  packet.result.results[0].relevance.fields.conditions = {
    normalized: "Asthma",
  };
  await page.emulateMedia({ colorScheme: "light" });
  await page.route("**/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({
      json:
        path === "/v1/ready"
          ? { status: "ready", catalog_id: "invented", model_loading: "lazy" }
          : path === "/v1/cases"
            ? { total: 1, limit: 50, offset: 0, items: [caseItem] }
            : path.startsWith("/v1/cases/")
              ? profile
              : path.startsWith("/v1/trials/")
                ? trial
                : packet,
    });
  });
  await page.goto("/");
  await expect(page).toHaveTitle(/Themis Trial/);
  await page.getByRole("button", { name: "Dark mode", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "About the project" }).click();
  await expect(
    page.getByRole("link", { name: /GitHub profile/ }),
  ).toHaveAttribute("href", "https://github.com/nguy3ntt");
  await page.screenshot({
    path: "test-results/presentation/about-dark.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption(caseItem.case_id);
  await page
    .getByRole("button", { name: "Search trials", exact: true })
    .click();
  const card = page.locator(".result-card").first();
  await expect(card.locator("mark")).toHaveText("asthma");
  await card.locator(".title-button").hover();
  await expect(
    page.getByRole("region", { name: /Result details for/ }),
  ).toBeVisible();
  await card.locator(".title-button").focus();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("region", { name: /Result details for/ }),
  ).toHaveCount(0);
  const details = card.getByRole("button", { name: /Result details/ });
  await details.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("region", { name: /Result details for/ }),
  ).toContainText("not calibrated match percentages");
  await page.screenshot({ path: "test-results/presentation/details-dark.png" });
  await page.keyboard.press("Escape");
  await card.locator(".title-button").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: "test-results/presentation/dialog-dark.png" });
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await details.click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/presentation/mobile-dark.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Dark mode", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "About the project" }).click();
  await page.screenshot({
    path: "test-results/presentation/about-light.png",
    fullPage: true,
  });
});
