import { expect, test } from "@playwright/test";
import { PASSWORD, SAMPLE_JD, SAMPLE_RESUME, uniqueEmail } from "./fixtures/samples";

test("signed-out gap report, then sign up and keep it", async ({ page }) => {
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();

  await expect(page.getByText("Close these gaps before the interview")).toBeVisible();
  await expect(page.getByText(/We couldn't find clear requirements/)).toHaveCount(0);
  // Evidence-linked: a resume line is quoted back.
  await expect(page.getByText(/forecast accuracy by 8%/).first()).toBeVisible();

  // Signing up from the report keeps it (report_token is passed to /auth/signup).
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await expect(page).toHaveURL(/\/login\?mode=signup&report=/);
  await page.getByLabel("Email").fill(uniqueEmail("report"));
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/prep");
  await expect(page.getByText(/Analytics Manager/).first()).toBeVisible();
});

test("a report with no readable skills says what to fix, and offers nothing to save", async ({ page }) => {
  await page.goto("/welcome");
  const para = (s: string) => s.replace(/\s+/g, " ");  // everything on one line: nothing for the parser to split
  await page.getByPlaceholder(/Paste the full job ad/).fill(para("Program manager role. ".repeat(20)));
  await page.getByPlaceholder(/Paste your resume/).fill(para("Analyst with five years of operations experience. ".repeat(8)));
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await expect(page.getByText("We couldn't pick out this role's skills yet")).toBeVisible();
  await expect(page.getByText(/The top 0 skills/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Save this and build my plan" })).toHaveCount(0);
});

test("job ad link import refuses internal addresses with a clear message", async ({ page }) => {
  await page.goto("/welcome");
  await page.getByLabel(/Job ad link/).fill("http://169.254.169.254/latest/meta-data/");
  await page.getByRole("button", { name: "Import" }).click();
  await expect(page.getByRole("status").filter({ hasText: "can't be imported" })).toBeVisible();
  await expect(page.getByLabel("Job description")).toHaveValue("");
});

test("a role landing page pre-fills a typical job ad for the gap report", async ({ page }) => {
  await page.goto("/roles");
  await page.getByRole("link", { name: /Data Analyst/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Data Analyst interview prep" })).toBeVisible();
  await page.getByRole("link", { name: "Check my resume against this role" }).click();
  await expect(page).toHaveURL(/\/welcome\?role=data-analyst$/);
  await expect(page.getByText(/We've filled in a typical Data Analyst job ad/)).toBeVisible();
  await expect(page.getByLabel("Job description")).toHaveValue(/Data Analyst - Commercial Insights/);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await expect(page.getByText("Close these gaps before the interview")).toBeVisible();
});
