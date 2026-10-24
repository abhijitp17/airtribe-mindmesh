# Accessibility

Target: WCAG 2.2 AA.

## Automated (CI, every PR)

`web/e2e/accessibility.spec.ts` runs axe-core with the WCAG 2.0/2.1/2.2 A and AA rule sets
on every main screen in a realistic state: welcome (empty and with a report), login, Today
(onboarding and with a plan), document + tutor, quiz, interview prep (skill matrix), library,
prep, new goal, progress and settings. Any violation fails the run.

First run (P1 Wave 5) found one serious issue: loading placeholders used `aria-label` on a
plain `<div>`, where screen readers ignore it. They now have `role="status"` (8 places), so
"Loading…" is announced politely.

## Keyboard, reflow and motion (CI, every PR)

`web/e2e/keyboard.spec.ts` automates the keyboard and layout items of the manual list:

- Tab through every main screen: each stop must show a focus indicator (2px+ outline, a ring,
  or the ink border on fields) and focus must keep moving (no traps).
- Key flows with the keyboard only: the gap report (focus moves to the new report heading),
  asking the tutor, making a quiz; menus close with Escape and return focus to their button.
- Reflow at 320px wide: no sideways scrolling on any main screen, signed out or in.
- `prefers-reduced-motion: reduce` leaves no infinite animation running.

First run (P1 Wave 7) found one issue: date fields (New goal, Add session) showed no focus
indicator in Chromium, because focus sits on an inner segment that `input:focus` didn't
style. Fixed with `:focus-within`.

## Manual (before each beta release)

Automated rules catch roughly a third of real problems. Check these by hand:

- **Keyboard only** (partly automated above; still try a full session by hand): every flow (gap report, sign-up, upload, ask, cite, quiz, report a
  question, plan, settings) works with Tab / Shift+Tab / Enter / Space; focus is always
  visible; nothing traps focus; after an action, focus lands somewhere sensible (quiz
  feedback, new report heading).
- **Screen reader** (VoiceOver on macOS and iOS, TalkBack on Android): citations announce
  their page ("Source: p. 1. Show in reader"); the reader announces "Showing the source on page N";
  status changes (saved, reported, loading) are announced.
- **Zoom 200% and 400% / 320px wide:** no horizontal scrolling of page content, no clipped text.
- **Reduced motion:** the citation pulse and other animations stop with `prefers-reduced-motion`.
- **Reduce transparency:** Settings > Display, and the OS setting, switch glass to solid.
- **Colour:** contrast rules are at the top of `web/src/app/globals.css` (orange always carries
  charcoal text); state is never shown by colour alone.
