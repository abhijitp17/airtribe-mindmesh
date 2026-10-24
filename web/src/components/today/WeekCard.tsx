"use client";

import Link from "next/link";
import type { WeekDay, WeekOut } from "@/lib/api-engagement";
import { weekSentence, weekdayName } from "./labels";

/** Row of Mon–Sun dots: filled where practised, orange ring on today. Never colour alone: an sr sentence plus day letters. */
export function WeekDots({ days }: { days: WeekDay[] }) {
  return (
    <div role="img" aria-label={weekSentence(days)} style={{ display: "inline-grid", gap: 4 }}>
      <span className="week-dots" aria-hidden>
        {days.map((d) => (
          <i key={d.date} className={[d.practised ? "on" : "", d.is_today ? "today" : ""].join(" ").trim()} title={weekdayName(d.date)} />
        ))}
      </span>
      <span className="week-dots tiny muted" aria-hidden>
        {days.map((d) => (
          <span key={d.date} style={{ width: 20, textAlign: "center", fontWeight: d.is_today ? 600 : 400, color: d.is_today ? "var(--ink)" : undefined }}>
            {weekdayName(d.date, "narrow")}
          </span>
        ))}
      </span>
    </div>
  );
}

export function weekHeadline(week: WeekOut): string {
  return `${week.done} of ${week.target} this week`;
}

/** Weekly target card for Today. */
export default function WeekCard({ week, showProgressLink = true }: { week: WeekOut; showProgressLink?: boolean }) {
  const met = week.done >= week.target;
  return (
    <section className="glass card" aria-labelledby="today-week-h">
      <div className="row spread" style={{ alignItems: "flex-start" }}>
        <div>
          <h2 id="today-week-h" style={{ fontSize: "1.08rem", marginBottom: ".2rem" }}>{weekHeadline(week)}</h2>
          <p className="muted small" style={{ margin: 0 }}>
            {met ? "Weekly target met. Anything more is a bonus." : "Any session or answer counts as a practice day."}
          </p>
        </div>
        <WeekDots days={week.days} />
      </div>
      {showProgressLink && (
        <p className="small" style={{ margin: ".75rem 0 0" }}>
          <Link href="/progress" style={{ display: "inline-flex", minHeight: 44, alignItems: "center" }}>See what you know</Link>
        </p>
      )}
    </section>
  );
}
