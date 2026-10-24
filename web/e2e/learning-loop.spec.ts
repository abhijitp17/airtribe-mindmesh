import { expect, test } from "@playwright/test";
import { signUp, uploadSample } from "./helpers";

test("upload a PDF, ask the tutor, take a quiz", async ({ page }) => {
  await signUp(page, "learner");
  // Upload: rights confirmation is required before the file is accepted.
  await uploadSample(page);

  // Tutor: the answer is checked against the pages, and its citation opens the reader.
  await page.getByPlaceholder("Ask about this document…").fill("What is Little's Law?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText("Checked against your pages")).toBeVisible();
  const cite = page.getByRole("button", { name: /^Source: p\. 1\. Show in reader/ }).first();
  await expect(cite).toBeVisible();
  await cite.click();
  // The reader scrolls to the cited sentence and highlights it.
  const highlight = page.getByRole("region", { name: "Source document" }).locator("mark");
  await expect(highlight).toBeInViewport();
  await expect(highlight).toContainText(/Little/i);

  // Quiz: make 3 questions, answer them one at a time, reach the results.
  await page.getByRole("tab", { name: "Practise" }).click();
  // Concepts from the extraction job are offered as quiz topics; picking one fills the focus field.
  const topics = page.getByRole("group", { name: "Topics in this document:" });
  await expect(topics.getByRole("button").first()).toBeVisible();
  const first = topics.getByRole("button").first();
  const name = (await first.textContent())!.trim();
  await first.click();
  await expect(page.getByLabel("Focus topic (optional)")).toHaveValue(name);
  await expect(first).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Questions").selectOption("3");
  await page.getByRole("button", { name: "Make a quiz" }).click();
  await expect(page).toHaveURL(/\/quiz\//);

  for (let i = 0; i < 3; i++) {
    // Wait for the question to render before deciding whether it's multiple choice.
    const options = page.getByRole("radio");
    await expect(options.first().or(page.getByLabel("Your answer"))).toBeVisible();
    if (await options.count()) await options.first().check();
    else await page.getByLabel("Your answer").fill("Work in process equals throughput times cycle time.");
    await page.getByRole("button", { name: "Check answer" }).click();
    await page.getByRole("button", { name: /Next question|See your results/ }).click();
  }
  await expect(page.getByRole("heading", { name: "Quiz done" })).toBeVisible();
});
