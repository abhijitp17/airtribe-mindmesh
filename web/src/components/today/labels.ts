// Plain-language labels and small pure helpers for Today, sessions, progress and the gap report (W4).
import type { IconName } from "@/components/Icon";
import type { Mastery } from "@/lib/api";
import type { DebriefNext, DebriefOutcome, Minutes, PreparingFor, SessionStep, StepKind, WeekDay, Win } from "@/lib/api-engagement";

export const MINUTE_CHOICES: readonly Minutes[] = [5, 15, 30];

export function isMinutes(n: number): n is Minutes {
  return n === 5 || n === 15 || n === 30;
}

export const KIND_LABEL: Record<StepKind, string> = {
  review: "Review",
  quiz: "Quiz",
  learn: "Learn",
  story: "Story",
  mock_question: "Mock question",
  plan_item: "From your plan",
};

export const KIND_ICON: Record<StepKind, IconName> = {
  review: "clock",
  quiz: "target",
  learn: "book",
  story: "quote",
  mock_question: "mic",
  plan_item: "flag",
};

export const WIN_ICON: Record<Win["kind"], IconName> = {
  level_up: "chart",
  gap_closed: "check",
  first_answer: "sparkle",
  target_met: "flag",
};

export const PREPARING_CHOICES: { value: PreparingFor; label: string; hint: string; icon: IconName }[] = [
  { value: "interview", label: "An interview", hint: "Match your resume to a job and practise answers", icon: "mic" },
  { value: "exam", label: "An exam", hint: "Turn your notes into a study plan", icon: "flag" },
  { value: "learn", label: "Learning a subject", hint: "Learn from your own documents", icon: "book" },
];

export const OUTCOMES: { value: DebriefOutcome; label: string }[] = [
  { value: "offer", label: "I got an offer" },
  { value: "next_round", label: "Moving to the next round" },
  { value: "rejected", label: "Not this time" },
  { value: "not_happened", label: "It didn't happen" },
  { value: "prefer_not", label: "Prefer not to say" },
];

export const NEXT_STEPS: { value: DebriefNext; label: string; hint: string }[] = [
  { value: "next_round", label: "Prepare for the next round", hint: "Keep the same skills and practise again" },
  { value: "new_role", label: "Start prep for another role", hint: "What you've proven carries over" },
  { value: "learning_goal", label: "Turn my gaps into a learning goal", hint: "A longer plan for the skills still open" },
  { value: "none", label: "Nothing for now", hint: "You can start something new any time" },
];

/** Next-step choices that make sense for an outcome ("prepare again" only when there is another interview to come). */
export function nextStepsFor(outcome: DebriefOutcome): typeof NEXT_STEPS {
  if (outcome === "next_round") return NEXT_STEPS;
  if (outcome === "not_happened") {
    return NEXT_STEPS.map((n) => (n.value === "next_round" ? { ...n, label: "Keep preparing for this interview", hint: "Same skills, a new date when you have one" } : n));
  }
  return NEXT_STEPS.filter((n) => n.value !== "next_round");
}

/** Progress groups, in the order shown on "What you know". */
export const LEVEL_GROUPS: { level: Mastery["level"]; title: string; filled: number; tint: string }[] = [
  { level: "strong", title: "Ready", filled: 4, tint: "tint-ready" },
  { level: "developing", title: "Getting there", filled: 3, tint: "" },
  { level: "weak", title: "Needs work", filled: 1, tint: "tint-gap" },
  { level: "unverified", title: "Not enough answers yet", filled: 0, tint: "tint-unknown" },
];

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "a", "a and b", "a, b and c". */
export function listPhrase(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

// Leading verbs we can safely lower-case when joining step titles into one sentence.
const VERBS = new Set(["Review", "Take", "Write", "Answer", "Learn", "Practise", "Practice", "Rehearse", "Read", "Revise", "Try", "Do", "Finish", "Start", "Prepare", "Explain"]);

function softenFirstWord(title: string): string {
  const [first, ...rest] = title.split(" ");
  return VERBS.has(first) ? [first.toLowerCase(), ...rest].join(" ") : title;
}

/** One-line summary of a set of steps, e.g. "Review Little's Law, write a stakeholder story and answer one mock question". */
export function summarizeSteps(steps: SessionStep[]): string {
  if (!steps.length) return "";
  const titles = steps.map((s, i) => (i === 0 ? s.title : softenFirstWord(s.title)));
  return listPhrase(titles);
}

export function totalMinutes(steps: SessionStep[]): number {
  return steps.reduce((sum, s) => sum + s.minutes, 0);
}

export function daysLeftPhrase(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

function parseIso(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function weekdayName(iso: string, style: "long" | "short" | "narrow" = "long"): string {
  return parseIso(iso).toLocaleDateString(undefined, { weekday: style });
}

/** Screen-reader sentence for the week dots. */
export function weekSentence(days: WeekDay[]): string {
  const practised = days.filter((d) => d.practised).map((d) => weekdayName(d.date));
  const today = days.find((d) => d.is_today);
  const first = practised.length ? `Practised ${listPhrase(practised)}.` : "No practice yet this week.";
  return today ? `${first} Today is ${weekdayName(today.date)}.` : first;
}

export function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
