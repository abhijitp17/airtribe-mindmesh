import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

test("create a study goal and get a day-by-day plan", async ({ page }) => {
  await signUp(page, "planner");
  await uploadSample(page);

  await page.goto("/goals/new");
  await page.getByLabel("Title").fill("Understand factory physics");
  await page.getByRole("checkbox", { name: /factory-physics-sample/i }).check();
  // Study every day, so "today" always has plan items whatever day the test runs.
  for (const day of ["Sat", "Sun"]) {
    const toggle = page.getByRole("button", { name: day, exact: true });
    if ((await toggle.getAttribute("aria-pressed")) !== "true") await toggle.click();
  }
  await page.getByRole("button", { name: "Create plan" }).click();

  await expect(page).toHaveURL(/\/goals\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Your plan, day by day" })).toBeVisible();
  await expect(page.getByText(/Little's Law|Variability/).first()).toBeVisible();

  // The plan shows up on Today. No "What are you preparing for?": uploading and planning already said it.
  await page.goto("/");
  await expect(page.getByText("What are you preparing for?")).toHaveCount(0);
  await expect(page.getByText(/Understand factory physics|Little's Law|Variability/).first()).toBeVisible();
});
