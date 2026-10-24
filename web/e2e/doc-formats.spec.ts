import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

const MD = `# Queueing notes

Little's Law relates the average work in process to throughput and cycle time in any stable system.
Variability in arrivals and processing makes queues longer and less predictable.

| Station | Rate |
|---|---|
| Drill | 12 |
`;

test("a Markdown file becomes a readable, citable document", async ({ page }) => {
  await signUp(page, "formats");
  await page.goto("/library");
  await page.getByRole("checkbox", { name: /right to use these files/ }).check();
  await page.locator('input[type="file"]').setInputFiles({ name: "queueing-notes.md", mimeType: "text/markdown", buffer: Buffer.from(MD) });
  const doc = page.getByRole("link", { name: /queueing-notes/i }).first();
  await expect(doc).toBeVisible();
  await doc.click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f]+$/);
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
  await expect(page.locator("main, #main").first()).toContainText("| Drill | 12 |");  // the table kept its rows
  await page.getByRole("tab", { name: "Original file" }).click();
  await expect(page.getByRole("link", { name: "Download queueing-notes.md" })).toBeVisible();
});

test("an unsupported file is refused in the browser with a clear message", async ({ page }) => {
  await signUp(page, "formats2");
  await page.goto("/library");
  await page.getByRole("checkbox", { name: /right to use these files/ }).check();
  await page.locator('input[type="file"]').setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: Buffer.from([137, 80, 78, 71]) });
  await expect(page.getByText(/file type isn't supported/)).toBeVisible();
});
