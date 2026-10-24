import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

test("signed-out visitors get the front page, which leads to sign-up and the gap report", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/about$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Your learning,\s*finally connected\./);
  await expect(page.getByText("EXAMPLE", { exact: true })).toBeVisible();  // the hero picture is labelled as an example
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  await expect(page.getByRole("link", { name: "Try a free gap report" })).toHaveAttribute("href", "/welcome");
  await page.getByRole("link", { name: "Start your map" }).first().click();
  await expect(page).toHaveURL(/\/login\?mode=signup$/);
});

test("knowledge map: concepts from the library, traced to pages, with the notes chat docked", async ({ page }) => {
  await signUp(page, "kmap");
  await page.goto("/map");
  await expect(page.getByText("Your map starts with your first document")).toBeVisible();

  await uploadSample(page);
  await page.getByRole("link", { name: "Map" }).first().click();
  await expect(page).toHaveURL(/\/map$/);
  await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();
  const concepts = page.locator('svg g[role="button"]');
  await expect(concepts.first()).toBeVisible();

  // Every concept says its level in words; picking one shows where it comes from.
  await expect(concepts.first()).toHaveAttribute("aria-label", /: (Strong|Developing|Needs work|Not practised yet)/);
  await concepts.first().focus();
  await page.keyboard.press("Enter");
  const details = page.getByRole("complementary", { name: "Concept details" });
  await expect(details.getByText("Where it comes from")).toBeVisible();
  await expect(details.getByRole("link").first()).toHaveAttribute("href", /\/documents\/[0-9a-f]+(\?page=\d+)?/);
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);

  // The same concepts as a list (the text alternative to the picture).
  await page.getByRole("tab", { name: "List" }).click();
  await expect(page.locator(".map-list button").first()).toBeVisible();

  // "Ask my notes" opens the docked chat, answered notes-first (the AI is only offered).
  await details.getByRole("button", { name: "Ask my notes" }).click();
  const chat = page.getByRole("region", { name: "Ask your notes" });
  await expect(chat.getByLabel("Your question")).toHaveValue(/^What is .+\?$/);
  await expect(chat).toContainText(/no AI used|Explain with AI|don't cover this/);
  await expect(chat).not.toContainText("AI answer, cited");
});
