import { expect, test } from "@playwright/test";
import { SAMPLE_JD, SAMPLE_RESUME } from "./fixtures/samples";

// Knowledge graph (P2): a skill on the gap report links to the concept in the learner's own
// material that teaches it, and the link opens the reader on that page.
test("a skill links to the concept and page in your material", async ({ page }) => {
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await page.getByLabel("Email").fill(`e2e-links-${Date.now()}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-1");
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/library");
  await page.getByRole("checkbox", { name: /right to use these files/ }).check();
  await page.locator('input[type="file"]').setInputFiles("e2e/fixtures/analytics-notes.pdf");
  await expect(page.getByRole("link", { name: /analytics-notes/i }).first()).toBeVisible();

  await page.goto("/prep");
  await page.getByRole("link", { name: /Analytics Manager/ }).first().click();
  await expect(page).toHaveURL(/\/interview\//);
  const card = page.getByRole("listitem").filter({ hasText: /forecasting/i }).first();
  await card.getByRole("button").first().click();
  await expect(card.getByRole("heading", { name: "Concepts to study in your material" })).toBeVisible();
  const link = card.getByRole("link", { name: /Demand forecasting/ });
  await expect(card.getByText(/analytics-notes, p\. 1/)).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f]+\?page=1$/);
  await expect(page.getByText(/Demand forecasting is covered here/).first()).toBeVisible();

  // The same links show up on the shared skill list (P3 taxonomy) under Progress.
  await page.goto("/progress");
  const skills = page.getByRole("region", { name: "Your skills" });
  await expect(skills.getByText("Demand forecasting", { exact: true })).toBeVisible();
  await expect(skills.getByText(/Needed for: Analytics Manager/).first()).toBeVisible();
});
