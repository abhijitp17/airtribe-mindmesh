import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { SAMPLE_JD, SAMPLE_RESUME } from "./fixtures/samples";
import { signUp, uploadSample } from "./helpers";

// Automated WCAG 2.2 A/AA checks (axe-core) on every main screen, in a filled-in state.
// Automated checks catch roughly a third of real issues; keyboard and screen-reader passes
// are still part of the manual audit (docs/accessibility.md).
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectNoViolations(page: Page, label: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const summary = violations.map((v) => `${v.id} (${v.impact}): ${v.help} -> ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  expect(summary, `${label} accessibility violations`).toEqual([]);
}

test("signed-out pages", async ({ page }) => {
  await page.goto("/roles");
  await expectNoViolations(page, "roles index");
  await page.goto("/roles/data-analyst");
  await expectNoViolations(page, "role landing page");
  await page.goto("/welcome");
  await expectNoViolations(page, "welcome (empty)");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await expect(page.getByText("Close these gaps before the interview")).toBeVisible();
  await expectNoViolations(page, "welcome (report)");
  await page.goto("/login");
  await expectNoViolations(page, "login");
});

test("interview prep from a saved report", async ({ page }) => {
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await page.getByLabel("Email").fill(`e2e-a11y-prep-${Date.now()}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-1");
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/prep");
  await page.getByRole("link", { name: /Analytics Manager/ }).first().click();
  await expect(page).toHaveURL(/\/interview\//);
  await page.waitForLoadState("networkidle");
  await expectNoViolations(page, "interview prep (skill matrix)");
});

test("signed-in screens", async ({ page }) => {
  await signUp(page, "a11y");
  await expectNoViolations(page, "today (onboarding)");
  await uploadSample(page);
  await expectNoViolations(page, "document + tutor");
  await page.getByRole("tab", { name: "Practise" }).click();
  await page.getByRole("button", { name: "Make a quiz" }).click();
  await expect(page).toHaveURL(/\/quiz\//);
  await page.waitForLoadState("networkidle");
  await expectNoViolations(page, "quiz");
  for (const [path, label] of [["/", "today"], ["/library", "library"], ["/prep", "prep"], ["/goals/new", "new goal"],
                               ["/progress", "progress"], ["/settings", "settings"]] as const) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expectNoViolations(page, label);
  }
});
