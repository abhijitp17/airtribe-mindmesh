import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

test("notebook cover: sample chapter, trail, continue ribbon, ⌘K and the docked chat", async ({ page }) => {
  await signUp(page, "notebook");
  // Onboarding is covered elsewhere; mark it done so the cover shows.
  const token = await page.evaluate(() => localStorage.getItem("mindmesh_token"));
  expect((await page.request.patch("http://localhost:8100/api/me/prefs", { headers: { Authorization: `Bearer ${token}` }, data: { onboarded: true } })).ok()).toBe(true);
  await page.goto("/");
  const trail = page.getByRole("list", { name: "Your trail" });
  await expect(trail).toBeVisible();
  await expect(trail.getByRole("link", { name: /^Learn: you are here/ })).toHaveAttribute("href", "/library");
  await expect(trail.getByRole("link", { name: /^Interview: not yet/ })).toBeVisible();  // later stops are links too: nothing is locked

  await page.getByRole("button", { name: "Explore a sample chapter" }).click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f]+/);
  await expect(page.getByText("How Learning Sticks").first()).toBeVisible();

  await page.getByRole("link", { name: "Today" }).first().click();
  await expect(trail.getByRole("link", { name: /^Learn: done/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Continue where you left off/ })).toHaveAttribute("href", /\/documents\//);
  await expect(page.getByRole("complementary", { name: "Your next step" })).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);

  // ⌘K: find a concept from the sample and open it on the map.
  await page.keyboard.press("ControlOrMeta+k");
  const box = page.getByRole("combobox", { name: "Search or ask" });
  await box.fill("retrieval");
  await expect(page.getByRole("option", { name: /Retrieval Practice/i }).first()).toBeVisible();
  await page.getByRole("option", { name: /Retrieval Practice/i }).first().click();
  await expect(page).toHaveURL(/\/map\?c=/);
  await expect(page.getByRole("complementary", { name: "Concept details" })).toContainText(/Retrieval Practice/i);

  // ⌘K → ask: the docked chat answers notes-first; Escape closes the bar and gives focus back.
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.press("Escape");
  await expect(box).toBeHidden();
  await page.keyboard.press("ControlOrMeta+k");
  await box.fill("What is the forgetting curve?");
  await page.keyboard.press("Enter");
  const dock = page.getByRole("region", { name: "Ask your notes" });
  await expect(dock).toContainText(/no AI used|Explain with AI|don't cover this/);
  await expect(dock).not.toContainText("AI answer, cited");
});
