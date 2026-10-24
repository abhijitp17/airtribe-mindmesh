import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("turn on email reminders and set quiet hours", async ({ page }) => {
  await signUp(page, "reminders");
  await page.goto("/settings");
  const toggle = page.getByRole("switch", { name: "Email reminders" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByLabel("From")).toBeDisabled();  // quiet hours only matter when reminders are on

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.getByLabel("From").fill("22:30");
  // Exact: "Your work stays saved." (Sign out section) would also match a substring search.
  await expect(page.getByText("Saved.", { exact: true })).toBeAttached();

  await page.reload();  // saved on the server, not just on screen
  await expect(page.getByRole("switch", { name: "Email reminders" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByLabel("From")).toHaveValue("22:30");
});
