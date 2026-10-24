import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { SAMPLE_JD, SAMPLE_RESUME } from "./fixtures/samples";

test("share a prep plan read-only, open it signed out, then turn the link off", async ({ page, browser }) => {
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await page.getByLabel("Email").fill(`e2e-share-${Date.now()}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-1");
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/prep");
  await page.getByRole("link", { name: /Analytics Manager/ }).first().click();

  await page.getByRole("button", { name: "Create a link" }).click();
  const url = await page.getByLabel("Share link").inputValue();
  expect(url).toMatch(/\/share\/[\w-]{20,}$/);

  const visitor = await (await browser.newContext()).newPage();  // signed out
  await visitor.goto(url.replace(/^https?:\/\/[^/]+/, ""));
  await expect(visitor.getByRole("heading", { level: 1, name: /Analytics Manager/ })).toBeVisible();
  await expect(visitor.getByRole("heading", { name: "The plan" })).toBeVisible();
  await expect(visitor.getByText(/Northwind|Priya|example\.com/)).toHaveCount(0);  // nothing from the resume
  const { violations } = await new AxeBuilder({ page: visitor }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => v.id)).toEqual([]);

  await page.getByRole("button", { name: /Turn off the link/ }).click();
  await expect(page.getByText(/Link turned off/)).toBeVisible();
  await visitor.reload();
  await expect(visitor.getByRole("heading", { name: "This link isn't available" })).toBeVisible();
});
