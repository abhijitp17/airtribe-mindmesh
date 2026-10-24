import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers";

// The server assigns each user an arm by a stable hash; here the experiments response is pinned
// so both arms are covered every run. Event recording itself is covered by backend tests.
async function pinArm(page: Page, arm: "goal_first" | "upload_first") {
  await page.route(/\/api\/me\/experiments$/, (route) => route.fulfill({ json: { onboarding: arm } }));
}

async function noViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test("goal-first arm asks what you're preparing for, then the weekly target", async ({ page }) => {
  await pinArm(page, "goal_first");
  const shown = page.waitForRequest((r) => r.url().endsWith("/api/events") && r.postDataJSON()?.name === "onboarding_shown");
  await signUp(page, "goalfirst");
  await expect(page.getByRole("heading", { name: "What are you preparing for?" })).toBeVisible();
  await shown;
  await noViolations(page);
  await page.getByRole("button", { name: /An exam/ }).click();
  await expect(page.getByRole("heading", { name: /How many sessions a week/ })).toBeVisible();
});

test("upload-first arm starts with the material and goes straight to the Library", async ({ page }) => {
  await pinArm(page, "upload_first");
  await signUp(page, "uploadfirst");
  await expect(page.getByRole("heading", { name: "Start with your own material" })).toBeVisible();
  await expect(page.getByText("What are you preparing for?")).toHaveCount(0);
  await noViolations(page);
  const choice = page.waitForRequest((r) => r.url().endsWith("/api/events") && r.postDataJSON()?.name === "onboarding_choice");
  await page.getByRole("link", { name: /Upload a document/ }).click();
  expect((await choice).postDataJSON().props).toEqual({ variant: "upload_first", choice: "upload" });
  await expect(page).toHaveURL(/\/library$/);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Start with your own material" })).toHaveCount(0);  // onboarded
});
