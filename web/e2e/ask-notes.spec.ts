import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

test("ask my notes: free answers from notes, AI only when chosen, savings shown", async ({ page }) => {
  await signUp(page, "asknotes");
  await uploadSample(page);
  await page.goto("/ask");  // the full page; day to day, asking lives in the dock and ⌘K

  await page.getByLabel("Your question").fill("What is Little's Law?");
  await page.getByRole("button", { name: "Ask my notes" }).click();
  await expect(page.getByText("Quoted from your notes · no AI used")).toBeVisible();
  await expect(page.getByRole("list", { name: "Sources" }).getByRole("link").first()).toHaveAttribute("href", /\/documents\/[0-9a-f]+\?page=\d+/);
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => v.id)).toEqual([]);

  await page.getByLabel("Your question").fill("Who painted the Mona Lisa?");
  await page.getByRole("button", { name: "Ask my notes" }).click();
  await expect(page.getByText("Your notes don't cover this yet.")).toBeVisible();
  await page.getByRole("button", { name: /Ask the AI: general knowledge \(about .* tokens\)/ }).click();
  await expect(page.getByText("General AI answer · not from your notes")).toBeVisible();
  await expect(page.getByLabel("Savings this month")).toContainText("1 answered from your notes, 1 with the AI");
});
