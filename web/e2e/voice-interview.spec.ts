import { expect, test } from "@playwright/test";
import { SAMPLE_JD, SAMPLE_RESUME } from "./fixtures/samples";

// Browsers' speech engines aren't available headless, so a fake SpeechRecognition / speechSynthesis
// stands in: it records what was read aloud and "hears" a fixed answer.
const FAKE_SPEECH = `
  window.__spoken = [];
  Object.defineProperty(window, "speechSynthesis", { configurable: true, value: { speak: (u) => window.__spoken.push(u.text), cancel: () => {} } });
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  window.SpeechRecognition = function () {
    const self = this;
    this.start = () => setTimeout(() => {
      self.onresult && self.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "Um, at Northwind I led a pricing review with finance and merchandising, and we cut markdown waste by 6 percent." }], { isFinal: true })] });
    }, 50);
    this.stop = () => setTimeout(() => self.onend && self.onend(), 10);
    this.abort = this.stop;
  };
`;

test("voice mode reads the question aloud and turns a spoken answer into editable text", async ({ page }) => {
  await page.addInitScript(FAKE_SPEECH);
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await page.getByLabel("Email").fill(`e2e-voice-${Date.now()}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-1");
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/prep");
  await page.getByRole("link", { name: /Analytics Manager/ }).first().click();
  await page.getByRole("button", { name: "Start mock interview" }).click();
  await expect(page).toHaveURL(/\/session\//);

  const question = (await page.locator("#current-q").textContent())!.trim();
  await page.getByRole("button", { name: /Voice mode off/ }).click();
  await expect(page.getByRole("button", { name: /Voice mode on/ })).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => (window as unknown as { __spoken: string[] }).__spoken)).toContain(question);
  await expect(page.getByText(/Mindmesh only receives the text you submit/)).toBeVisible();

  await page.getByRole("button", { name: "Answer out loud" }).click();
  await expect(page.getByLabel("Your answer")).toHaveValue(/led a pricing review/);
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText(/You spoke for .* words a minute.* 1 filler word \(mostly "um"\)/)).toBeVisible();

  await page.getByLabel("Your answer").fill((await page.getByLabel("Your answer").inputValue()).replace(/^Um, /, ""));
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByRole("list", { name: "Answered questions" })).toBeVisible();
});

test("without speech recognition, voice mode still reads questions and explains", async ({ page }) => {
  await page.addInitScript(`window.__spoken=[];Object.defineProperty(window,"speechSynthesis",{configurable:true,value:{speak:(u)=>window.__spoken.push(u.text),cancel:()=>{}}});
    window.SpeechSynthesisUtterance=function(t){this.text=t};delete window.SpeechRecognition;delete window.webkitSpeechRecognition;`);
  await page.goto("/welcome");
  await page.getByPlaceholder(/Paste the full job ad/).fill(SAMPLE_JD);
  await page.getByPlaceholder(/Paste your resume/).fill(SAMPLE_RESUME);
  await page.getByRole("button", { name: "Show my gap report" }).click();
  await page.getByRole("link", { name: "Save this and build my plan" }).click();
  await page.getByLabel("Email").fill(`e2e-voice2-${Date.now()}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-1");
  await page.locator("form").getByRole("button").first().click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/prep");
  await page.getByRole("link", { name: /Analytics Manager/ }).first().click();
  await page.getByRole("button", { name: "Start mock interview" }).click();
  await page.getByRole("button", { name: /Voice mode off/ }).click();
  await expect(page.getByText(/can't take spoken answers/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Answer out loud" })).toHaveCount(0);
});
