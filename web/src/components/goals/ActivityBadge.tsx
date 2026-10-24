import type { ActivityType, PlanItem } from "@/lib/api-goals";

// Colour is always paired with a text label (PRD 10.3).
const ACTIVITY: Record<ActivityType, [string, string]> = {
  learn: ["Learn", "info"],
  practice: ["Practice", "ready"],
  review: ["Review", ""],
  mock_interview: ["Mock interview", "warn"],
  drill: ["Drill", "warn"],
};

export function ActivityBadge({ activity }: { activity: ActivityType }) {
  const [label, cls] = ACTIVITY[activity] ?? [activity, ""];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function activityLabel(activity: ActivityType): string {
  return (ACTIVITY[activity] ?? [activity])[0];
}

const STATUS: Record<PlanItem["status"], [string, string]> = {
  pending: ["To do", ""],
  done: ["Done", "ready"],
  skipped: ["Skipped", ""],
};

export function ItemStatusBadge({ status, leftOut = false }: { status: PlanItem["status"]; leftOut?: boolean }) {
  if (leftOut) return <span className="badge">Left out</span>;
  const [label, cls] = STATUS[status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function OnTrackBadge({ onTrack }: { onTrack: boolean }) {
  return onTrack ? <span className="badge ready">On track</span> : <span className="badge warn">Behind plan</span>;
}

/** Items the planner couldn't fit are stored as skipped rows with this reason prefix. */
export function isLeftOut(item: PlanItem): boolean {
  return item.status === "skipped" && item.reason.startsWith("Left out:");
}
