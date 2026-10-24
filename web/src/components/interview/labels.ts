// Enum → human label + badge class. Colour is always paired with text (PRD 10.3).
import type {
  AssessedLevel,
  CompetencyCat,
  Confidence,
  CriterionStatus,
  EvidenceStrength,
  GapType,
  Importance,
  PlanActivity,
  Priority,
  QuestionCat,
  ReadinessDimension,
  SessionFocus,
  Verdict,
} from "@/lib/api-interview";

/** [label, badge class] */
export type LabelCls = readonly [string, string];

export const IMPORTANCE: Record<Importance, LabelCls> = {
  critical: ["Critical", "gap"],
  high: ["High", "warn"],
  medium: ["Medium", "info"],
  low: ["Low", ""],
};

export const PRIORITY: Record<Priority, LabelCls> = {
  critical: ["Critical priority", "gap"],
  high: ["High priority", "warn"],
  medium: ["Medium priority", "info"],
  low: ["Low priority", ""],
};

export const PRIORITY_SHORT: Record<Priority, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

export const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, medium: 2, low: 3 };
export const IMPORTANCE_RANK: Record<Importance, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export const STRENGTH: Record<EvidenceStrength, LabelCls> = {
  strong: ["Strong evidence", "good"],
  partial: ["Partial evidence", "warn"],
  none: ["Not on your resume", "warn"],
};

export const LEVEL: Record<AssessedLevel, LabelCls> = {
  strong: ["Strong", "good"],
  developing: ["Developing", "info"],
  weak: ["Needs work", "warn"],
  unverified: ["Not enough answers yet", ""],
};

export const CONFIDENCE: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

/** [label, badge class, explanation] */
export const GAP: Record<GapType, readonly [string, string, string]> = {
  strong: ["Ready", "good", "Your resume and practice both show this."],
  knowledge_gap: ["Need to learn it", "gap", "Practice results suggest you don't know this well yet."],
  application_gap: ["Know it, need to apply it", "warn", "You know the concept but haven't shown you can apply it to problems."],
  evidence_gap: ["Resume doesn't show it", "warn", "You may have this skill, but your resume doesn't show concrete evidence of it."],
  communication_gap: ["Explain it better", "warn", "You know this, but your answers don't yet explain it clearly."],
  unverified: ["Not enough answers yet", "info", "We don't have enough answers or resume evidence to judge this yet."],
  stretch: ["Stretch skill", "", "Nice to have for this role; lower return on prep time."],
};

export const CATEGORY: Record<CompetencyCat, string> = {
  technical: "Technical",
  domain: "Domain",
  tool: "Tool",
  behavioral: "Behavioral",
  leadership: "Leadership",
  communication: "Communication",
};

export const QUESTION_CAT: Record<QuestionCat, LabelCls> = {
  technical: ["Technical", "info"],
  behavioral: ["Behavioral", "ready"],
  case: ["Case", "warn"],
  resume_deep_dive: ["Resume deep-dive", ""],
  role_specific: ["Role-specific", "info"],
};

export const VERDICT: Record<Verdict, LabelCls> = {
  strong: ["Strong answer", "good"],
  adequate: ["Adequate", "info"],
  needs_work: ["Needs work", "warn"],
  unassessed: ["Not assessed", ""],
};

export const CRITERION_MARK: Record<CriterionStatus, [string, string]> = {
  met: ["✓", "Met"],
  partial: ["◐", "Partly met"],
  missing: ["✗", "Missing"],
};

export const READINESS: Record<ReadinessDimension, [string, string]> = {
  role_knowledge: ["Role knowledge", "Do you know the concepts this role needs?"],
  applied_problem_solving: ["Applied problem solving", "Can you use them on realistic problems?"],
  resume_evidence: ["Resume evidence", "Does your resume prove the skills the role asks for?"],
  behavioral_examples: ["Behavioral examples", "Do you have real stories with situation, action and result?"],
  communication: ["Communication", "Are your answers clear and well structured?"],
};

export const ACTIVITY: Record<PlanActivity, string> = {
  learn: "Learn",
  practice: "Practice",
  story: "Prepare a story",
  mock_interview: "Mock interview",
  drill: "Drill",
};

export const FOCUS: Record<SessionFocus, string> = {
  mixed: "Mixed",
  technical: "Technical",
  behavioral: "Behavioral",
  resume: "Resume deep-dive",
  case: "Case",
};

export const FACTOR_LABEL: Record<"importance" | "gap_severity" | "evidence_confidence" | "urgency" | "feasibility", string> = {
  importance: "How important to the role",
  gap_severity: "How big the gap is",
  evidence_confidence: "How sure we are",
  urgency: "Time until interview",
  feasibility: "How quickly you can close it",
};

export function focusLabel(f: string): string {
  return f in FOCUS ? FOCUS[f as SessionFocus] : f;
}

/** Days from today (local) until a YYYY-MM-DD date. Negative if past. */
export function daysUntil(date: string): number {
  const [y, m, d] = date.split("-").map(Number);
  const target = new Date(y, (m || 1) - 1, d || 1);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function countdown(date: string | null): string {
  if (!date) return "No interview date set";
  const n = daysUntil(date);
  if (n === 0) return "Interview today";
  if (n === 1) return "Interview tomorrow";
  if (n > 1) return `Interview in ${n} days`;
  return `Interview was ${-n} day${n === -1 ? "" : "s"} ago`;
}

/** "23 October" (adds the year when it isn't this year). */
export function longDate(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const dt = new Date(y, (m || 1) - 1, d || 1);
  const sameYear = dt.getFullYear() === new Date().getFullYear();
  return dt.toLocaleDateString(undefined, sameYear ? { day: "numeric", month: "long" } : { day: "numeric", month: "long", year: "numeric" });
}

/** Gap types that mean "there is something to close". */
export const GAP_TYPES_REAL: GapType[] = ["knowledge_gap", "application_gap", "evidence_gap", "communication_gap"];

export type SkillState = "gap" | "unknown" | "ready" | "stretch";

export function skillState(g: GapType): SkillState {
  if (g === "strong") return "ready";
  if (g === "unverified") return "unknown";
  if (g === "stretch") return "stretch";
  return "gap";
}

/** Tint class for a skill card. Always paired with a text badge. */
export function skillTint(g: GapType): string {
  const st = skillState(g);
  return st === "gap" ? "tint-gap" : st === "unknown" ? "tint-unknown" : st === "ready" ? "tint-ready" : "plain";
}

/** Status badge shown above the skill name, e.g. "Critical gap", "Gap", "Interview ready". */
export function skillStatus(g: GapType, p: Priority): LabelCls {
  const st = skillState(g);
  if (st === "ready") return ["Interview ready", "ready"];
  if (st === "unknown") return ["Not enough answers yet", "info"];
  if (st === "stretch") return ["Nice to have", ""];
  if (p === "critical") return ["Critical gap", "gap"];
  if (p === "high") return ["Gap, high priority", "gap"];
  return ["Gap", "warn"];
}

/** Filled segments (0..4) for a readiness level, used with .steps4. */
export const LEVEL_STEPS: Record<AssessedLevel, number> = { strong: 4, developing: 3, weak: 1, unverified: 0 };

export function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
