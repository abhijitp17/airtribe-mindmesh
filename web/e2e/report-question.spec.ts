import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

test("report a bad question, find it in the Library, and undo", async ({ page }) => {
  await signUp(page, "reporter");
  await uploadSample(page);
  await page.getByRole("tab", { name: "Practise" }).click();
  await page.getByLabel("Questions").selectOption("3");
  await page.getByRole("button", { name: "Make a quiz" }).click();
  await expect(page).toHaveURL(/\/quiz\//);

  await page.getByRole("button", { name: "Report a problem with this question" }).click();
  const send = page.getByRole("button", { name: "Send report" });
  await expect(send).toBeDisabled();  // a reason is required
  await page.getByRole("button", { name: "The question is unclear" }).click();
  await page.getByLabel(/Anything to add/).fill("Two options say the same thing");
  await send.click();
  await expect(page.getByText(/Thanks, reported/)).toBeVisible();

  await page.goto("/library");
  const section = page.getByRole("region", { name: "Reported questions" });
  await expect(section).toBeVisible();
  await expect(section.getByText("The question is unclear")).toBeVisible();
  await expect(section.getByText(/Two options say the same thing/)).toBeVisible();
  await section.getByRole("button", { name: /^Undo report/ }).click();
  await expect(page.getByRole("heading", { name: "Reported questions" })).toHaveCount(0);
});
