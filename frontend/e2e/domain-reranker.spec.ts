import { expect, test } from "@playwright/test";

test("actual domain head exposes retained baseline, provenance and unchanged screening", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_UI_INTEGRATION !== "1",
    "Explicit local model/database opt-in",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByLabel("Choose a synthetic case")
    .selectOption("trec-ct-2022:29");
  await page
    .getByRole("button", { name: "Retrieval laboratory", exact: true })
    .click();
  await page.getByLabel("Retrieval method").selectOption("dense");
  await page.getByLabel("Opt into cross-encoder reranking").check();
  await page.getByLabel("Reranker model").selectOption("domain_hard");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/v1/search") &&
      r.request().method() === "POST" &&
      r.request().postDataJSON()?.reranker_variant === "domain_hard",
  );
  await page.getByRole("button", { name: "Run comparison" }).click();
  const packet = await (await response).json();
  expect(packet.result.reranker.variant).toBe("domain_hard");
  expect(packet.result.reranker.selected_epoch).toBe(0);
  expect(packet.result.reranker.promoted).toBe(false);
  expect(packet.provenance.domain_adapter_manifest_sha256).toMatch(
    /^[a-f0-9]{64}$/,
  );
  await expect(page.getByText("Observed ranking comparison")).toBeVisible({
    timeout: 180000,
  });
  await expect(
    page.getByText(/Development selection retained the original head/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(
    page.getByText("Saved replay", { exact: true }).first(),
  ).toBeVisible({ timeout: 180000 });
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await expect(page.getByText("No reranking", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
