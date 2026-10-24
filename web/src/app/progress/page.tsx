"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell, { BackLink } from "@/components/Shell";
import { WeekDots, weekHeadline } from "@/components/today/WeekCard";
import { LEVEL_GROUPS, errorText, plural } from "@/components/today/labels";
import { api, type Mastery, type Progress } from "@/lib/api";
import { engagementApi, type WeekOut } from "@/lib/api-engagement";
import SkillProfile from "@/components/today/SkillProfile";

export default function ProgressPage() {
  return (
    <Shell>
      <ProgressView />
    </Shell>
  );
}

function ProgressView() {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [week, setWeek] = useState<WeekOut | null>(null);
  const [weekErr, setWeekErr] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setErr(null);
    setWeekErr(false);
    api.progress().then(setProgress).catch((e) => setErr(errorText(e, "Could not load what you know.")));
    engagementApi.week().then(setWeek).catch(() => setWeekErr(true));
  }, []);

  useEffect(() => { load(); }, [load]);

  const due = progress?.concepts.filter((c) => c.due_for_review).length ?? 0;

  return (
    <div className="narrow stack">
      <style>{`
        .today-prog-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .35rem .9rem; align-items: center; padding: .85rem 0; border-top: 1px solid var(--line); }
        .today-prog-row:first-child { border-top: 0; }
        .today-prog-row .today-prog-why { grid-column: 1 / -1; }
        @media (min-width: 640px) { .today-prog-row { grid-template-columns: minmax(0, 1fr) 140px auto; } .today-prog-row .today-prog-why { grid-column: 1; } }
      `}</style>
      <div>
        <BackLink href="/">Today</BackLink>
        <div className="page-head" style={{ marginBottom: 0 }}>
          <div>
            <h1>What you know</h1>
            <p>Based only on your answers. We wait for a few answers before rating a concept.</p>
          </div>
        </div>
      </div>

      <SkillProfile />

      <section className="glass card row spread" aria-label="This week">
        {week ? (
          <>
            <div>
              <h2 style={{ fontSize: "1.08rem", margin: 0 }}>{weekHeadline(week)}</h2>
              <p className="muted small" style={{ margin: 0 }}>
                {progress ? `${plural(progress.totals.attempts ?? 0, "answer")} so far` : "Counting your answers…"}
                {due > 0 ? ` · ${plural(due, "review")} due` : ""}
              </p>
            </div>
            <WeekDots days={week.days} />
          </>
        ) : weekErr ? (
          <p className="muted small" style={{ margin: 0 }}>Your week couldn&apos;t load right now.</p>
        ) : (
          <div className="skeleton" style={{ height: 44, width: "100%" }} role="status" aria-label="Loading your week" />
        )}
      </section>

      {err && (
        <div className="notice bad row spread" role="alert">
          <span>{err} Check your connection and try again.</span>
          <button type="button" onClick={load} style={{ minHeight: 44 }}>Try again</button>
        </div>
      )}

      {!progress && !err && (
        <div className="stack" role="status" aria-label="Loading what you know">
          {[0, 1].map((i) => <div key={i} className="skeleton" style={{ height: 180, borderRadius: "var(--r-lg)" }} />)}
        </div>
      )}

      {progress && progress.concepts.length === 0 && (
        <div className="glass card empty">
          <h3>Nothing rated yet</h3>
          <p>Take a 5-question quiz and we&apos;ll start showing what you know.</p>
          <Link href="/" className="btn primary" style={{ minHeight: 44 }}>Start today&apos;s session</Link>
        </div>
      )}

      {progress && progress.concepts.length > 0 && (
        <>
          {LEVEL_GROUPS.map((g) => {
            const items = progress.concepts.filter((c) => c.level === g.level);
            if (!items.length) return null;
            const hid = `today-prog-${g.level}`;
            return (
              <section key={g.level} className={`glass card ${g.tint}`} aria-labelledby={hid}>
                <div className="row spread" style={{ marginBottom: ".25rem" }}>
                  <h2 id={hid} style={{ fontSize: "1.08rem", margin: 0 }}>{g.title}</h2>
                  <span className="muted small">{plural(items.length, "concept")}</span>
                </div>
                <ul className="list" style={{ display: "block" }}>
                  {items.map((m) => <ConceptRow key={m.concept} m={m} filled={g.filled} label={g.title} />)}
                </ul>
              </section>
            );
          })}
          {due > 0 && (
            <p className="small muted" style={{ textAlign: "center", margin: 0 }}>
              Reviews due are added to <Link href="/">today&apos;s session</Link> first.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ConceptRow({ m, filled, label }: { m: Mastery; filled: number; label: string }) {
  return (
    <li className="today-prog-row" style={{ display: "grid" }}>
      <span style={{ fontWeight: 500, minWidth: 0 }}>{m.concept}</span>
      <span className="steps4" role="img" aria-label={`${label}: ${filled} of 4`} style={{ width: 132 }}>
        {[0, 1, 2, 3].map((i) => <span key={i} className={i < filled ? "f" : undefined} />)}
      </span>
      <span>{m.due_for_review ? <span className="badge warn">Review due</span> : null}</span>
      <span className="muted small today-prog-why">{m.explanation}</span>
    </li>
  );
}
