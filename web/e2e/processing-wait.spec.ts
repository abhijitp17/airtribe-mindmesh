import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

// Processing a small PDF takes well under a second, so the document's progress is stubbed
// over a real, processed document: the wait screen, its quiz and the early workspace all hit the real API.
test("a long document being read: progress, 3 quick questions, and starting early", async ({ page }) => {
  await signUp(page, "waiter");
  await uploadSample(page);
  const docUrl = page.url();
  const id = docUrl.split("/documents/")[1];
  const started = new Date(Date.now() - 30_000).toISOString();

  await page.route(new RegExp(`/api/documents/${id}$`), async (route) => {
    const res = await route.fetch();
    const doc = await res.json();
    await route.fulfill({ response: res, json: { ...doc, status: "processing", page_count: 300, pages_done: 12, processing_started_at: started } });
  });
  await page.goto(docUrl);

  await expect(page.getByText(/Read 12 of 300 pages, about \d+ minutes left/)).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Pages read" })).toHaveAttribute("aria-valuenow", "12");
  await expect(page.getByText(/This is a long one/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "The first 12 pages are ready" })).toBeVisible();
  await expect(page.getByText("What it covers so far")).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);

  await page.getByRole("button", { name: "Read and ask now" }).click();
  await expect(page.getByText(/Still reading the rest: 12 of 300 pages/)).toBeVisible();

  await page.goto(docUrl);
  await page.getByRole("button", { name: "Try 3 quick questions" }).click();
  await expect(page).toHaveURL(/\/quiz\//);
});
