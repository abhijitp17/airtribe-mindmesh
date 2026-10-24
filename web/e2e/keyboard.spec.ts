import { expect, test, type Page } from "@playwright/test";
import { SAMPLE_JD, SAMPLE_RESUME } from "./fixtures/samples";
import { signUp, uploadSample } from "./helpers";

// The keyboard and layout part of the manual accessibility checklist (docs/accessibility.md),
// automated so it stays true: visible focus on every Tab stop, no focus traps, key flows done
// with the keyboard only, reflow at 320px, and motion off with prefers-reduced-motion.
// Screen-reader checks still need a person with VoiceOver / TalkBack.

type Stop = { label: string; visible: boolean };

/** Tab through the page; every stop must show a focus indicator, and focus must keep moving. */
async function tabAudit(page: Page, screen: string, maxStops = 60) {
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  const seen: string[] = [];
  const bad: string[] = [];
  for (let i = 0; i < maxStops; i++) {
    await page.keyboard.press("Tab");
    const stop: Stop | null = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2;
      // A ring on the element, or on the wrapper it sits in (e.g. the tutor composer), via :focus-within.
      const wrap = el.parentElement;
      const ring = cs.boxShadow !== "none" || (!!wrap && wrap.matches(":focus-within") && getComputedStyle(wrap).boxShadow !== "none");
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.tagName).trim().slice(0, 40);
      const path = `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}:${name}`;
      return { label: path, visible: outline || ring };
    });
    if (!stop) break;  // left the page: no trap
    if (!stop.visible) bad.push(stop.label);
    if (seen.length > 3 && stop.label === seen[0]) break;  // wrapped around
    seen.push(stop.label);
  }
  expect(seen.length, `${screen}: nothing focusable`).toBeGreaterThan(0);
  expect(new Set(seen).size, `${screen}: focus stuck on one element`).toBeGreaterThan(Math.min(3, seen.length - 1));
  expect(bad, `${screen}: Tab stops without a visible focus indicator`).toEqual([]);
}

async function noHorizontalScroll(page: Page, screen: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${screen}: page scrolls sideways at 320px`).toBeLessThanOrEqual(1);
}

test("gap report with the keyboard only; focus moves to the result", async ({ page }) => {
  await page.goto("/welcome");
  await tabAudit(page, "welcome");
  await page.getByLabel("Job description").focus();
  await page.keyboard.insertText(SAMPLE_JD);
  await page.keyboard.press("Tab");  // to the resume
  await expect(page.getByLabel("Your resume")).toBeFocused();
  await page.keyboard.insertText(SAMPLE_RESUME);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Show my gap report" })).toBeFocused();
  await page.keyboard.press("Enter");
  const heading = page.getByRole("heading", { level: 2 }).first();
  await expect(heading).toBeFocused();  // the new report, announced
});

test("signed-in screens: visible focus everywhere and the learning loop by keyboard", async ({ page }) => {
  await signUp(page, "keys");
  await tabAudit(page, "today (onboarding)");
  await uploadSample(page);
  await tabAudit(page, "document workspace");

  // Ask the tutor by keyboard.
  const question = page.getByRole("textbox").last();
  await question.focus();
  await page.keyboard.insertText("What is Little's Law?");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Verified|p\. \d/).first()).toBeVisible();

  // Make a quiz and answer the first question by keyboard.
  await page.getByRole("tab", { name: "Practise" }).focus();
  await page.keyboard.press("Enter");
  await page.getByLabel("Questions").focus();
  await page.getByLabel("Questions").selectOption("3");
  await page.getByRole("button", { name: "Make a quiz" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/quiz\//);
  await tabAudit(page, "quiz");

  for (const path of ["/library", "/prep", "/progress", "/settings", "/goals/new", "/ask", "/map"]) {
    await page.goto(path);
    await expect(page.locator("main, #main").first()).toBeVisible();
    await tabAudit(page, path);
  }
});

test("menus and dialogs close with Escape and give focus back", async ({ page }) => {
  await signUp(page, "escape");
  await uploadSample(page);
  await page.goto("/library");
  const more = page.getByRole("button", { name: /More actions for/ }).first();
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Delete document" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Delete document" })).toHaveCount(0);
  await expect(more).toBeFocused();
});

test("reflow at 320px: no sideways scrolling", async ({ page }) => {
  await signUp(page, "narrow");
  await uploadSample(page);  // at desktop width: the "Ready" badge is desktop-only
  const docUrl = page.url();
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto(docUrl);
  await expect(page.getByRole("tablist", { name: "Workspace" })).toBeVisible();
  await noHorizontalScroll(page, "document");
  await page.goto("/");
  await noHorizontalScroll(page, "today");
  for (const path of ["/library", "/prep", "/progress", "/settings", "/goals/new", "/ask", "/map"]) {
    await page.goto(path);
    await expect(page.locator("main, #main").first()).toBeVisible();
    await noHorizontalScroll(page, path);
  }
  await page.context().clearCookies();
  await page.evaluate(() => localStorage.clear());
  for (const path of ["/about", "/welcome", "/login"]) {
    await page.goto(path);
    await noHorizontalScroll(page, path);
  }
});

test("reduced motion turns animations off", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");
  const moving = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("*")]
    .filter((el) => {
      const cs = getComputedStyle(el);
      const dur = (s: string) => Math.max(...s.split(",").map((x) => parseFloat(x) || 0));
      return cs.animationName !== "none" && dur(cs.animationDuration) > 0.05 && cs.animationIterationCount === "infinite";
    })
    .map((el) => el.className || el.tagName));
  expect(moving).toEqual([]);
});
