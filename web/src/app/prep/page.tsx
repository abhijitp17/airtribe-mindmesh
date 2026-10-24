"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Icon from "@/components/Icon";
import Shell from "@/components/Shell";
import { OnTrackBadge } from "@/components/goals/ActivityBadge";
import PrepStyles from "@/components/interview/PrepStyles";
import { countdown, daysUntil, errMsg, longDate } from "@/components/interview/labels";
import { GOAL_TYPE_LABEL, formatDay, goalsApi, type GoalSummary } from "@/lib/api-goals";
import { interviewApi, type PrepSummary } from "@/lib/api-interview";

export default function PrepHubPage() {
  return (
    <Shell>
      <PrepHub />
    </Shell>
  );
}

/** Soonest upcoming interview first; preps without a date (or past ones) fall back to the most recently updated. */
function pickHero(preps: PrepSummary[]): PrepSummary | null {
  if (preps.length === 0) return null;
  const upcoming = preps
    .filter((p) => p.interview_date !== null && daysUntil(p.interview_date) >= 0)
    .sort((a, b) => (a.interview_date ?? "").localeCompare(b.interview_date ?? ""));
  if (upcoming.length) return upcoming[0];
  return [...preps].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

function gapsLabel(n: number): string {
  if (n === 0) return "No critical gaps";
  return `${n} gap${n === 1 ? "" : "s"} to close first`;
}

function Skeletons({ n, h }: { n: number; h: number }) {
  return (
    <div className="grid2" role="status" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" style={{ height: h }} />)}
    </div>
  );
}

function PrepHub() {
  const router = useRouter();
  const [preps, setPreps] = useState<PrepSummary[] | null>(null);
  const [goals, setGoals] = useState<GoalSummary[] | null>(null);
  const [prepErr, setPrepErr] = useState<string | null>(null);
  const [goalErr, setGoalErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [starting, setStarting] = useState(false);
  const [startErr, setStartErr] = useState<string | null>(null);

  useEffect(() => {
    setPrepErr(null);
    setGoalErr(null);
    interviewApi.preps().then(setPreps).catch((e: unknown) => setPrepErr(errMsg(e, "We couldn't load your role preps.")));
    goalsApi.list().then(setGoals).catch((e: unknown) => setGoalErr(errMsg(e, "We couldn't load your study goals.")));
  }, [tick]);

  const hero = preps ? pickHero(preps) : null;
  const others = preps && hero ? preps.filter((p) => p.id !== hero.id) : [];
  const allEmpty = preps !== null && goals !== null && preps.length === 0 && goals.length === 0;

  async function practise() {
    if (!hero || starting) return;
    setStarting(true);
    setStartErr(null);
    try {
      const s = await interviewApi.startSession(hero.id, {});
      router.push(`/interview/${hero.id}/session/${s.id}`);
    } catch (e) {
      setStartErr(errMsg(e, "We couldn't start the mock interview. Try again in a moment."));
      setStarting(false);
    }
  }

  return (
    <div className="prep-root stack">
      <PrepStyles />
      <div className="page-head">
        <div>
          <h1>Prep</h1>
          <p>Everything you&apos;re preparing for</p>
        </div>
        {!allEmpty && (
          <div className="row">
            <Link className="btn" href="/interview/new"><Icon name="plus" size={18} /> New role prep</Link>
            <Link className="btn" href="/goals/new"><Icon name="plus" size={18} /> New study goal</Link>
          </div>
        )}
      </div>

      {(prepErr || goalErr) && (
        <div className="notice bad row spread" role="alert">
          <span>{[prepErr, goalErr].filter(Boolean).join(" ")} Check your connection and try again.</span>
          <button type="button" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}

      {allEmpty && (
        <section className="glass hero-card empty" aria-labelledby="empty-h">
          <span className="icon-well" aria-hidden="true" style={{ margin: "0 auto 1rem" }}><Icon name="target" size={24} /></span>
          <h2 id="empty-h">Nothing to prepare for yet</h2>
          <p>Add a job you want and your resume to see what to work on first.</p>
          <div className="stack-sm" style={{ maxWidth: 320, margin: "0 auto" }}>
            <Link className="btn primary lg block" href="/interview/new">Add a job and your resume</Link>
            <p className="small" style={{ margin: 0 }}>or <Link href="/goals/new">set a study goal</Link></p>
          </div>
        </section>
      )}

      {/* Hero: the soonest role prep */}
      {preps === null && !prepErr && <div className="skeleton" style={{ height: 210, borderRadius: "var(--r-xl)" }} role="status" aria-label="Loading" />}
      {hero && (
        <section className="glass hero-card stack" aria-labelledby="hero-h">
          <div className="row spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
            <div style={{ minWidth: 0 }}>
              <span className="prep-kicker">{hero.interview_date ? countdown(hero.interview_date) : "Your role prep"}</span>
              <h2 id="hero-h" className="prep-title-xl" style={{ marginTop: ".2rem" }}>{hero.role_title}</h2>
              <p className="muted" style={{ margin: ".25rem 0 0" }}>
                {[hero.company, hero.interview_date ? `Interview on ${longDate(hero.interview_date)}` : "No interview date set"].filter(Boolean).join(". ")}
              </p>
            </div>
            <Link href={`/interview/${hero.id}`} className="arrow-tile" aria-label={`Open ${hero.role_title}`} style={{ width: 44, height: 44 }}>
              <Icon name="arrow" size={20} />
            </Link>
          </div>
          <div className="row" style={{ gap: ".4rem" }}>
            <span className={`badge ${hero.critical_gaps > 0 ? "gap" : "ready"}`}>{gapsLabel(hero.critical_gaps)}</span>
            <span className="badge">{hero.sessions} mock interview{hero.sessions === 1 ? "" : "s"}</span>
          </div>
          <div className="row">
            <button type="button" className="primary lg" onClick={practise} disabled={starting} style={{ flex: "1 1 240px" }}>
              {starting && <span className="spinner" />} {starting ? "Starting…" : "Practise a mock interview"}
            </button>
            <Link className="btn lg" href={`/interview/${hero.id}`} style={{ flex: "0 1 auto" }}>Open</Link>
          </div>
          <div aria-live="polite">{startErr && <div className="notice bad" role="alert">{startErr}</div>}</div>
        </section>
      )}

      {/* Role preps */}
      {preps && preps.length > 0 && (
        <section aria-labelledby="roles-h">
          <div className="prep-section-h">
            <h2 id="roles-h">Role preps</h2>
            <span className="muted small">{preps.length} role{preps.length === 1 ? "" : "s"}</span>
          </div>
          {others.length === 0 ? (
            <p className="muted small" style={{ margin: 0 }}>Your only role prep is shown above. <Link href="/interview/new">Add another role</Link></p>
          ) : (
            <ul className="prep-grid">
              {others.map((p) => (
                <li key={p.id}>
                  <Link href={`/interview/${p.id}`} className="glass tile-link">
                    <span className="tile-top">
                      <span className="icon-well sm" aria-hidden="true"><Icon name="prep" /></span>
                      <span className="arrow-tile" aria-hidden="true"><Icon name="arrow" size={18} /></span>
                    </span>
                    <strong>{p.role_title}</strong>
                    <span className="prep-tile-meta">
                      {[p.company, p.interview_date ? longDate(p.interview_date) : "No date set"].filter(Boolean).join(" · ")}
                    </span>
                    <span className="row" style={{ gap: ".35rem" }}>
                      <span className={`badge ${p.critical_gaps > 0 ? "gap" : "ready"}`}>{gapsLabel(p.critical_gaps)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {preps && preps.length === 0 && goals && goals.length > 0 && (
        <Link href="/interview/new" className="glass tile-link" style={{ minHeight: 0 }}>
          <span className="tile-top">
            <span className="icon-well sm" aria-hidden="true"><Icon name="prep" /></span>
            <span className="arrow-tile" aria-hidden="true"><Icon name="arrow" size={18} /></span>
          </span>
          <strong>Preparing for a job?</strong>
          <span className="prep-tile-meta">Add a job you want and your resume to see what to work on first.</span>
        </Link>
      )}

      {/* Goals */}
      {goals === null && !goalErr && <Skeletons n={2} h={150} />}
      {goals && goals.length > 0 && (
        <section aria-labelledby="goals-h">
          <div className="prep-section-h">
            <h2 id="goals-h">Study goals</h2>
            <span className="muted small">{goals.length} goal{goals.length === 1 ? "" : "s"}</span>
          </div>
          <ul className="prep-grid">
            {goals.map((g) => {
              const pct = g.items_total ? Math.round((g.items_done / g.items_total) * 100) : 0;
              return (
                <li key={g.id}>
                  <Link href={`/goals/${g.id}`} className="glass tile-link">
                    <span className="tile-top">
                      <span className="icon-well sm" aria-hidden="true"><Icon name="flag" /></span>
                      <span className="arrow-tile" aria-hidden="true"><Icon name="arrow" size={18} /></span>
                    </span>
                    <strong>{g.title}</strong>
                    <span className="prep-tile-meta">{GOAL_TYPE_LABEL[g.goal_type]} · by {formatDay(g.deadline)}</span>
                    <span className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
                          aria-label={`${g.title}: ${pct}% of sessions done`} style={{ display: "block", marginTop: ".2rem" }}>
                      <span style={{ display: "block", height: "100%", width: `${pct}%`, background: "var(--ink)", borderRadius: 99 }} />
                    </span>
                    <span className="row" style={{ gap: ".35rem" }}>
                      <span className="muted small">{g.items_done} of {g.items_total} done</span>
                      {g.status === "active" ? <OnTrackBadge onTrack={g.on_track} /> : <span className="badge">{g.status === "paused" ? "Paused" : g.status === "completed" ? "Finished" : g.status}</span>}
                      {g.today_items > 0 && <span className="badge info">{g.today_items} today</span>}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {goals && goals.length === 0 && preps && preps.length > 0 && (
        <p className="muted small" style={{ margin: 0 }}>No study goals yet. <Link href="/goals/new">Set a study goal</Link> to get a day-by-day plan.</p>
      )}
    </div>
  );
}
