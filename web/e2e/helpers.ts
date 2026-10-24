import { expect, type Page } from "@playwright/test";
import { PASSWORD, SAMPLE_PDF, uniqueEmail } from "./fixtures/samples";

/** Create a fresh account through the real sign-up form and land on Today. */
export async function signUp(page: Page, tag: string): Promise<string> {
  const email = uniqueEmail(tag);
  await page.goto("/login?mode=signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);
  return email;
}

/** Upload the sample PDF from the Library and wait until it's processed. Leaves you on the document. */
export async function uploadSample(page: Page): Promise<void> {
  await page.goto("/library");
  await page.getByRole("checkbox", { name: /right to use these files/ }).check();
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
  const doc = page.getByRole("link", { name: /factory-physics-sample/i }).first();
  await expect(doc).toBeVisible();
  await doc.click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f]+$/);  // "Ready" also shows on the Library card
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
}
