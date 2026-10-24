"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { goalsApi, formatDay, formatMinutes, type TodayItem, type TodayOut } from "@/lib/api-goals";
import { ActivityBadge } from "./ActivityBadge";
import { isQuizActivity, startQuizSession } from "./session";

/** "Today's sessions" across all active goals. Self-contained so it can sit on any page. */
export default function TodayCard({ showEmptyLink = true }: { showEmptyLink?: boolean }) {
  const router = useRouter();
  const [today, setToday] = useState<TodayOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setToday(await goalsApi.today());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "We couldn't load today's sessions.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function setStatus(item: TodayItem, status: "done" | "skipped") {
    setBusy(item.id);
    try {
      await goalsApi.updateItem(item.id, { status });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "We couldn't update the session.");
    } finally {
      setBusy(null);
    }
  }

  async function start(item: TodayItem) {
    setBusy(item.id);
    setError(null);
    try {
      const goal = await goalsApi.get(item.goal_id);
      const quizId = await startQuizSession(goal.document_ids, item);
      router.push(`/quiz/${quizId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "We couldn't start the session.");
      setBusy(null);
    }
  }

  return (
    <section className="glass card stack" aria-labelledby="today-h">
      <div className="row spread">
        <div>
          <span className="muted small">{today ? formatDay(today.date) : "Today"}</span>
          <h2 id="today-h" style={{ margin: ".15rem 0" }}>Today&apos;s study sessions</h2>
        </div>
        {today && today.items.length > 0 && (
          <span className="muted small">{today.items.length} session{today.items.length === 1 ? "" : "s"} · {formatMinutes(today.total_minutes)}</span>
        )}
      </div>
      {error && (
        <div className="notice bad row spread" role="alert">
          <span>{error}</span>
          <button type="button" className="small" onClick={() => { setError(null); load(); }}>Try again</button>
        </div>
      )}
      {!today && !error && (
        <div className="stack-sm" role="status" aria-label="Loading">
          <div className="skeleton" style={{ height: 56 }} />
          <div className="skeleton" style={{ height: 56 }} />
        </div>
      )}
      {today && today.items.length === 0 && (
        <p className="muted" style={{ margin: 0 }}>
          Nothing scheduled for today.{" "}
          {showEmptyLink && <Link href="/goals/new">Set a study goal</Link>}
        </p>
      )}
      {today && today.items.length > 0 && (
        <ul className="prep-items" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: ".55rem" }}>
          {today.items.map((it) => (
            <li
              key={it.id}
              style={{ background: "rgba(255,255,255,0.62)", border: "1px solid var(--glass-edge)", borderRadius: "var(--r-md)", padding: ".8rem .95rem", display: "flex", gap: ".75rem", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}
            >
              <div style={{ minWidth: 0, flex: "1 1 220px" }}>
                <div className="row" style={{ gap: ".4rem" }}>
                  <ActivityBadge activity={it.activity_type} />
                  <span style={{ fontWeight: 500 }}>{it.topic}</span>
                  <span className="muted small">{formatMinutes(it.estimated_minutes)}</span>
                </div>
                <div className="muted small">
                  <Link href={`/goals/${it.goal_id}`}>{it.goal_title}</Link>
                  {it.objective && ` · ${it.objective}`}
                </div>
              </div>
              <div className="row" style={{ gap: ".35rem" }}>
                {isQuizActivity(it) && (
                  <button className="dark small" onClick={() => start(it)} disabled={busy !== null} style={{ minHeight: 44 }}
                          aria-label={`Start ${it.topic} quiz`}>
                    {busy === it.id && <span className="spinner" />} Start
                  </button>
                )}
                <button className="small" onClick={() => setStatus(it, "done")} disabled={busy !== null} style={{ minHeight: 44 }}
                        aria-label={`Mark ${it.topic} done`}>Done</button>
                <button className="ghost small" onClick={() => setStatus(it, "skipped")} disabled={busy !== null} style={{ minHeight: 44 }}
                        aria-label={`Skip ${it.topic}`}>Skip</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
