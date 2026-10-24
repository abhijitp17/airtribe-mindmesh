// Typed client for Today, timed sessions, weekly target, onboarding, debriefs and the public gap report.
// Contract: docs/CONTRACTS.md §7. Shared, read-only for workstreams.

import { API_URL, request, json } from "./api";
import type { AssessedLevel, Importance, GapType, Priority } from "./api-interview";

export type PreparingFor = "interview" | "exam" | "learn";
export type Minutes = 5 | 15 | 30;
export type OnboardingVariant = "goal_first" | "upload_first";

export type Prefs = {
  preparing_for: PreparingFor | null;
  weekly_target: number;
  default_minutes: Minutes;
  reminders: boolean;
  quiet_start: string;
  quiet_end: string;
  reduce_transparency: boolean;
  onboarded: boolean;
};

export type StepKind = "review" | "quiz" | "learn" | "story" | "mock_question" | "plan_item";
export type SessionStep = {
  id: string;
  kind: StepKind;
  title: string;
  detail: string;
  minutes: number;
  concept: string | null;
  // Where the step happens: quiz/review open a quiz, mock_question opens an interview turn, others open a link.
  target: { type: "quiz"; quiz_id: string | null; document_ids: string[]; focus: string | null }
        | { type: "interview"; prep_id: string; session_id: string | null }
        | { type: "plan_item"; goal_id: string; item_id: string }
        | { type: "link"; href: string };
  status: "pending" | "done" | "skipped";
};

export type Win = { kind: "level_up" | "gap_closed" | "first_answer" | "target_met"; title: string; detail: string };

export type WeekDay = { date: string; practised: boolean; is_today: boolean };
export type WeekOut = { target: number; done: number; days: WeekDay[] };

export type Countdown = { prep_id: string; role_title: string; company: string | null; interview_date: string; days_left: number } | null;

export type TodayPreview = {
  greeting_name: string;
  countdown: Countdown;
  week: WeekOut;
  suggestions: Record<"5" | "15" | "30", SessionStep[]>;  // a ready-made plan for each time choice
  last_win: Win | null;
  debrief_due: { prep_id: string; role_title: string; company: string | null; interview_date: string } | null;
  empty_reason: "no_material" | "no_goal" | null;   // why suggestions may be thin, for the empty state
  library_count: number;
};

export type StudySessionOut = {
  id: string; minutes: Minutes; steps: SessionStep[]; status: "active" | "completed" | "abandoned";
  wins: Win[]; started_at: string; completed_at: string | null;
};

export type DebriefOutcome = "offer" | "next_round" | "rejected" | "not_happened" | "prefer_not";
export type DebriefNext = "next_round" | "new_role" | "learning_goal" | "none";
export type DebriefOut = { id: string; prep_id: string; outcome: DebriefOutcome; note: string; next_step: DebriefNext | null; created_at: string;
                           follow_up: { type: "goal" | "prep"; id: string } | null };

export type PublicSkill = {
  name: string; importance: Importance; gap_type: GapType; priority: Priority; assessed_level: AssessedLevel;
  evidence_quote: string | null;   // verbatim resume line, or null
  jd_quote: string;                // verbatim JD line
  why: string;                     // one plain sentence
  next_step: string;
};
export type PublicReport = {
  token: string;                   // opaque, short-lived; pass to /auth/signup to keep the report
  role_title: string; company: string | null;
  skills: PublicSkill[];           // top 5 by priority
  hidden_count: number;            // additional skills shown after sign-up
  warnings: string[];
  expires_at: string;
};

export const engagementApi = {
  prefs: () => request<Prefs>("/me/prefs"),
  experiments: () => request<{ onboarding: OnboardingVariant }>("/me/experiments"),
  /** Fire-and-forget product event (content-free; the server allowlists names and properties). */
  event: (name: "onboarding_shown" | "onboarding_choice" | "voice_answer", props: Record<string, string | number | boolean> = {}) => {
    request<void>("/events", { method: "POST", body: json({ name, props }) }).catch(() => { /* never block the UI */ });
  },
  updatePrefs: (body: Partial<Omit<Prefs, "onboarded">> & { onboarded?: true }) => request<Prefs>("/me/prefs", { method: "PATCH", body: json(body) }),
  todayPreview: () => request<TodayPreview>("/today/preview"),
  week: () => request<WeekOut>("/week"),
  startSession: (minutes: Minutes) => request<StudySessionOut>("/sessions/study", { method: "POST", body: json({ minutes }) }),
  session: (id: string) => request<StudySessionOut>(`/sessions/study/${id}`),
  updateStep: (id: string, stepId: string, status: "done" | "skipped", quizId?: string) =>
    request<StudySessionOut>(`/sessions/study/${id}/steps/${stepId}`, { method: "PATCH", body: json({ status, quiz_id: quizId ?? null }) }),
  completeSession: (id: string) => request<StudySessionOut>(`/sessions/study/${id}/complete`, { method: "POST" }),
  debrief: (prepId: string, outcome: DebriefOutcome, next_step: DebriefNext | null, note = "") =>
    request<DebriefOut>(`/interview/preps/${prepId}/debrief`, { method: "POST", body: json({ outcome, next_step, note }) }),
};

/** Signed-out endpoints: no bearer token. */
export const publicApi = {
  gapReport: async (resume_text: string, job_text: string): Promise<PublicReport> => {
    const res = await fetch(`${API_URL}/api/public/gap-report`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_text, job_text }),
    });
    if (!res.ok) {
      let msg = "Could not build the report. Check both texts and try again.";
      try { const b = await res.json(); if (typeof b.detail === "string") msg = b.detail; } catch { /* not JSON */ }
      throw new Error(msg);
    }
    return res.json() as Promise<PublicReport>;
  },
  /** Fetch a job ad from a link (server-side, SSRF-checked). Throws with a message fit to show. */
  jobFromUrl: async (url: string): Promise<JobFromUrl> => {
    const res = await fetch(`${API_URL}/api/public/job-from-url`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      let msg = "We couldn't import that link. Paste the job ad text instead.";
      try { const b = await res.json(); if (typeof b.detail === "string") msg = b.detail; } catch { /* not JSON */ }
      throw new Error(msg);
    }
    return res.json() as Promise<JobFromUrl>;
  },
};

export type JobFromUrl = { text: string; title: string | null; company: string | null };
