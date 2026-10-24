"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import Icon from "@/components/Icon";
import {
  interviewApi,
  type DeepDiveItem,
  type PrepPlanItem,
  type SessionFocus,
  type SessionListItem,
  type SkillMatch,
} from "@/lib/api-interview";
import { ACTIVITY, FOCUS, errMsg, focusLabel } from "./labels";

function Skeletons({ n = 3, h = 56 }: { n?: number; h?: number }) {
  return (
    <div className="stack-sm" role="status" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" style={{ height: h }} />)}
    </div>
  );
}

export function PrepPlan({ plan, skills }: { plan: PrepPlanItem[]; skills: SkillMatch[] }) {
  const byComp = new Map(skills.map((s) => [s.competency_id, s.name]));
  const total = plan.reduce((a, p) => a + p.estimated_minutes, 0);
  return (
    <section className="glass card stack" aria-labelledby="plan-h">
      <div className="prep-section-h" style={{ marginBottom: 0 }}>
        <h2 id="plan-h">Your prep plan</h2>
        {plan.length > 0 && <span className="muted small">{plan.length} step{plan.length === 1 ? "" : "s"} · about {total} min</span>}
      </div>
      {plan.length === 0 ? (
        <div className="empty" style={{ padding: "1rem" }}>
          <p style={{ margin: 0 }}>No plan steps yet. Edit your resume or job description, then press Update.</p>
        </div>
      ) : (
        <ol className="prep-items">
          {plan.map((p, i) => (
            <li key={p.id} className="prep-item">
              <div style={{ minWidth: 0, flex: "1 1 220px" }}>
                <span className="muted tiny">Step {i + 1}</span>
                <span className="prep-name" style={{ fontSize: "1rem" }}>{p.title}</span>
                {p.competency_id && byComp.get(p.competency_id) && <span className="muted small">For {byComp.get(p.competency_id)}</span>}
                {p.reason && <div className="muted small">Why: {p.reason}</div>}
              </div>
              <div className="row" style={{ gap: ".35rem", flexShrink: 0 }}>
                <span className="badge info">{ACTIVITY[p.activity]}</span>
                <span className="badge">{p.estimated_minutes} min</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function DeepDive({ prepId, version }: { prepId: string; version: string }) {
  const [items, setItems] = useState<DeepDiveItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setItems(null);
    setErr(null);
    interviewApi.deepDive(prepId).then(setItems).catch((e: unknown) => setErr(errMsg(e, "We couldn't load the deep-dive questions.")));
  }, [prepId, version, tick]);

  return (
    <section className="glass card stack" aria-labelledby="dd-h">
      <h2 id="dd-h" style={{ margin: 0 }}>Questions about your resume</h2>
      <p className="muted small" style={{ margin: 0 }}>Interviewers probe what you wrote. Prepare real answers for each line: your role, the numbers, the trade-offs.</p>
      {err && (
        <div className="notice bad row spread" role="alert">
          <span>{err}</span>
          <button type="button" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}
      {!items && !err && <Skeletons n={2} h={48} />}
      {items && items.length === 0 && <p className="muted" style={{ margin: 0 }}>No resume lines to ask about yet.</p>}
      {items && items.length > 0 && (
        <ul className="prep-items">
          {items.map((it) => (
            <li key={it.bullet_id} className="prep-item" style={{ display: "block" }}>
              <details>
                <summary style={{ cursor: "pointer", minHeight: 44, display: "flex", alignItems: "center", gap: ".5rem", flexWrap: "wrap" }}>
                  <mark>&ldquo;{it.bullet}&rdquo;</mark>
                  <span className="muted small">{it.questions.length} question{it.questions.length === 1 ? "" : "s"}</span>
                </summary>
                <ul className="small" style={{ margin: ".35rem 0 0", paddingLeft: "1.2rem" }}>
                  {it.questions.map((q, i) => <li key={i} style={{ marginBottom: ".25rem" }}>{q}</li>)}
                </ul>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const FOCI: SessionFocus[] = ["mixed", "technical", "behavioral", "resume", "case"];

/** Mock interviews: the start form (the screen's one orange action) and past sessions. */
export function Sessions({ prepId }: { prepId: string }) {
  const router = useRouter();
  const fid = useId();
  const [list, setList] = useState<SessionListItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [focus, setFocus] = useState<SessionFocus>("mixed");
  const [n, setN] = useState(5);
  const [busy, setBusy] = useState(false);
  const [startErr, setStartErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    interviewApi.sessions(prepId).then(setList).catch((e: unknown) => setErr(errMsg(e, "We couldn't load your past mock interviews.")));
  }, [prepId, tick]);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStartErr(null);
    try {
      const s = await interviewApi.startSession(prepId, { focus, target_questions: n });
      router.push(`/interview/${prepId}/session/${s.id}`);
    } catch (e2) {
      setStartErr(errMsg(e2, "We couldn't start the mock interview. Try again in a moment."));
      setBusy(false);
    }
  }

  return (
    <section className="glass card stack" aria-labelledby="sess-h">
      <h2 id="sess-h" style={{ margin: 0 }}>Mock interviews</h2>
      <form onSubmit={start} className="stack-sm">
        <div>
          <span className="small muted" id={`${fid}-f`} style={{ display: "block", marginBottom: ".3rem" }}>Focus</span>
          <div className="prep-chips" role="group" aria-labelledby={`${fid}-f`}>
            {FOCI.map((f) => (
              <button key={f} type="button" aria-pressed={focus === f} onClick={() => setFocus(f)}>{FOCUS[f]}</button>
            ))}
          </div>
        </div>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: "0 1 140px" }}>
            <label htmlFor="mi-n">Questions</label>
            <select id="mi-n" value={n} onChange={(e) => setN(Number(e.target.value))}>
              {[3, 4, 5, 6, 7, 8, 9, 10].map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <button type="submit" className="primary lg" disabled={busy} style={{ flex: "1 1 220px" }}>
            {busy && <span className="spinner" />} {busy ? "Starting…" : "Start mock interview"}
          </button>
        </div>
      </form>
      {startErr && <div className="notice bad" role="alert">{startErr}</div>}

      {err && (
        <div className="notice bad row spread" role="alert">
          <span>{err}</span>
          <button type="button" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}
      {!list && !err && <Skeletons n={2} />}
      {list && list.length === 0 && <p className="muted small" style={{ margin: 0 }}>No mock interviews yet. Your first one shows where to focus.</p>}
      {list && list.length > 0 && (
        <ul className="prep-items" aria-label="Past mock interviews">
          {list.map((s) => (
            <li key={s.id}>
              <Link
                href={`/interview/${prepId}/session/${s.id}`}
                className="prep-item"
                style={{ textDecoration: "none", color: "var(--ink)", alignItems: "center", flexWrap: "nowrap" }}
              >
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span className="prep-name" style={{ fontSize: "1rem" }}>{focusLabel(s.focus)} interview</span>
                  <span className="muted small">
                    {new Date(s.started_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })} · {s.questions} question{s.questions === 1 ? "" : "s"}
                    {s.avg_score !== null && ` · ${Math.round(s.avg_score * 100)}% of what a good answer covers`}
                  </span>
                </span>
                <span className={`badge ${s.status === "completed" ? "ready" : "info"}`}>
                  {s.status === "completed" ? "Finished" : s.status === "active" ? "In progress" : s.status}
                </span>
                <span className="arrow-tile" aria-hidden="true"><Icon name="arrow" size={18} /></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
