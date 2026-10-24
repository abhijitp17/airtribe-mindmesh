// Typed client for goals & study plans (docs/CONTRACTS.md §4).
import { json, request } from "@/lib/api";

export type GoalType = "learn" | "revise" | "exam" | "interview";
export type ActivityType = "learn" | "practice" | "review" | "mock_interview" | "drill";
export type PlanItem = {
  id: string; position: number; scheduled_date: string; topic: string; concept: string | null;
  activity_type: ActivityType;
  estimated_minutes: number; objective: string;
  sources: { chunk_id: string; document_id: string; page_start: number; page_end: number; section: string }[];
  status: "pending" | "done" | "skipped"; user_edited: boolean; reason: string;
};
export type ProposalChange = {
  op: "add" | "move" | "remove" | "resize"; item_id: string | null;
  topic?: string; activity_type?: string; to_date?: string; minutes?: number; why: string;
};
export type PlanProposal = { id: string; reason: string; changes: ProposalChange[]; status: "pending" | "accepted" | "rejected"; created_at: string };
export type GoalStats = {
  total_minutes: number; done_minutes: number; items_done: number; items_total: number;
  on_track: boolean; days_left: number; capacity_minutes: number;
};
export type GoalOut = {
  id: string; goal_type: GoalType; title: string; target_outcome: string; deadline: string;
  minutes_per_day: number; study_days: number[]; current_level: string; document_ids: string[];
  prep_id: string | null; status: "active" | "paused" | "completed";
  items: PlanItem[]; pending_proposal: PlanProposal | null;
  stats: GoalStats;
  feasibility_warning: string | null; created_at: string;
};
export type GoalSummary = {
  id: string; title: string; goal_type: GoalType; deadline: string; status: string;
  items_done: number; items_total: number; on_track: boolean; today_items: number;
};
export type TodayItem = PlanItem & { goal_id: string; goal_title: string };
export type TodayOut = { date: string; items: TodayItem[]; total_minutes: number };

export type GoalCreate = {
  goal_type: GoalType; title: string; target_outcome?: string; deadline: string;
  minutes_per_day: number; study_days?: number[]; current_level?: string; document_ids: string[];
  prep_id?: string | null;
};
export type GoalPatch = Partial<GoalCreate> & { status?: GoalOut["status"] };
export type PlanItemPatch = {
  scheduled_date?: string; estimated_minutes?: number; topic?: string; status?: PlanItem["status"]; position?: number;
};
export type PlanItemCreate = { topic: string; activity_type: ActivityType; scheduled_date: string; estimated_minutes: number };

/** Minimal shape of an interview prep for the goal form (GET /api/interview/preps). */
export type PrepOption = { id: string; role_title: string; company: string | null };

export const goalsApi = {
  list: () => request<GoalSummary[]>("/goals"),
  get: (id: string) => request<GoalOut>(`/goals/${id}`),
  create: (body: GoalCreate) => request<GoalOut>("/goals", { method: "POST", body: json(body) }),
  update: (id: string, body: GoalPatch) => request<GoalOut>(`/goals/${id}`, { method: "PATCH", body: json(body) }),
  remove: (id: string) => request<void>(`/goals/${id}`, { method: "DELETE" }),
  regenerate: (id: string, keep_edited = true) =>
    request<GoalOut>(`/goals/${id}/regenerate`, { method: "POST", body: json({ keep_edited }) }),
  updateItem: (itemId: string, body: PlanItemPatch) =>
    request<PlanItem>(`/plan-items/${itemId}`, { method: "PATCH", body: json(body) }),
  addItem: (goalId: string, body: PlanItemCreate) =>
    request<PlanItem>(`/goals/${goalId}/items`, { method: "POST", body: json(body) }),
  removeItem: (itemId: string) => request<void>(`/plan-items/${itemId}`, { method: "DELETE" }),
  adapt: (goalId: string) => request<PlanProposal | null>(`/goals/${goalId}/adapt`, { method: "POST" }),
  acceptProposal: (pid: string) => request<GoalOut>(`/plan-proposals/${pid}/accept`, { method: "POST" }),
  rejectProposal: (pid: string) => request<GoalOut>(`/plan-proposals/${pid}/reject`, { method: "POST" }),
  today: () => request<TodayOut>("/today"),
  preps: () => request<PrepOption[]>("/interview/preps"),
};

// ---------- shared helpers (pure) ----------

export const GOAL_TYPE_LABEL: Record<GoalType, string> = {
  learn: "Learn something new",
  revise: "Revise what I know",
  exam: "Prepare for an exam",
  interview: "Prepare for an interview",
};

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** Local calendar date as YYYY-MM-DD (not UTC, so "today" matches the user's day). */
export function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function todayIso(): string {
  return isoDate(new Date());
}

export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDate(new Date(y, m - 1, d + n));
}

export function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function formatMinutes(n: number): string {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60);
  const m = n % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
