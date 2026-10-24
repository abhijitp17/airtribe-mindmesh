"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import Shell, { BackLink, useUser } from "@/components/Shell";
import PrepStyles from "@/components/interview/PrepStyles";
import { fieldStyle } from "@/components/goals/styles";
import { api, type Doc } from "@/lib/api";
import {
  GOAL_TYPE_LABEL,
  WEEKDAYS,
  addDays,
  goalsApi,
  todayIso,
  type GoalType,
  type PrepOption,
} from "@/lib/api-goals";

export default function NewGoalPage() {
  return (
    <Shell>
      <NewGoal />
    </Shell>
  );
}

const TYPES: GoalType[] = ["learn", "revise", "exam", "interview"];
const LEVELS = [
  ["beginner", "Beginner: new to this"],
  ["standard", "Standard: some background"],
  ["advanced", "Advanced: I know the basics well"],
] as const;
type Level = (typeof LEVELS)[number][0];

function isLevel(v: string): v is Level {
  return LEVELS.some(([k]) => k === v);
}

function NewGoal() {
  const router = useRouter();
  const user = useUser();
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [preps, setPreps] = useState<PrepOption[] | null>(null);
  const [prepError, setPrepError] = useState(false);

  const [goalType, setGoalType] = useState<GoalType>("learn");
  const [title, setTitle] = useState("");
  const [outcome, setOutcome] = useState("");
  const [deadline, setDeadline] = useState(addDays(todayIso(), 21));
  const [minutes, setMinutes] = useState(45);
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [level, setLevel] = useState<Level>(user && isLevel(user.level) ? user.level : "standard");
  const [docIds, setDocIds] = useState<string[]>([]);
  const [prepId, setPrepId] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.documents()
      .then((d) => setDocs(d.filter((x) => x.status === "ready")))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load documents"));
  }, []);

  useEffect(() => {
    if (goalType !== "interview" || preps !== null || prepError) return;
    goalsApi.preps().then(setPreps).catch(() => setPrepError(true));
  }, [goalType, preps, prepError]);

  function toggleDay(d: number) {
    setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort((a, b) => a - b)));
  }

  function toggleDoc(id: string) {
    setDocIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  const usePrep = goalType === "interview" && prepId !== "";
  const canSubmit =
    title.trim().length > 0 && deadline >= todayIso() && minutes >= 10 && minutes <= 480 &&
    days.length > 0 && (docIds.length > 0 || usePrep);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const g = await goalsApi.create({
        goal_type: goalType, title: title.trim(), target_outcome: outcome.trim(), deadline,
        minutes_per_day: minutes, study_days: days, current_level: level, document_ids: docIds,
        prep_id: usePrep ? prepId : null,
      });
      router.push(`/goals/${g.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the goal");
      setBusy(false);
    }
  }

  return (
    <form className="prep-root stack" style={{ maxWidth: 720, margin: "0 auto" }} onSubmit={submit} aria-labelledby="new-goal-h">
      <PrepStyles />
      <BackLink href="/prep">Prep</BackLink>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1 id="new-goal-h">New study goal</h1>
          <p>
            Tell us what you want to achieve and how much time you have. We&apos;ll suggest topics from your documents and
            schedule them so no day goes over your time. You can edit everything afterwards.
          </p>
        </div>
      </div>

      <section className="glass card stack" aria-label="Your goal">
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="small muted" style={{ marginBottom: ".35rem" }}>What kind of goal is it?</legend>
          <div className="prep-chips">
            {TYPES.map((t) => (
              <button key={t} type="button" aria-pressed={goalType === t} onClick={() => setGoalType(t)}>
                {goalType === t && <span aria-hidden>✓ </span>}{GOAL_TYPE_LABEL[t]}
              </button>
            ))}
          </div>
        </fieldset>

        <div>
          <label htmlFor="g-title">Title</label>
          <input id="g-title" type="text" required maxLength={255} value={title} onChange={(e) => setTitle(e.target.value)}
                 placeholder={goalType === "interview" ? "e.g. Data analyst interview at Acme" : "e.g. Understand factory physics"} />
        </div>
        <div>
          <label htmlFor="g-outcome">What does success look like? (optional)</label>
          <textarea id="g-outcome" maxLength={2000} value={outcome} onChange={(e) => setOutcome(e.target.value)}
                    placeholder="e.g. Explain Little's Law and apply it to a real production line" style={{ minHeight: 70 }} />
        </div>
      </section>

      <section className="glass card stack" aria-labelledby="time-h">
        <h2 id="time-h">Your time</h2>
        <div className="grid2">
          <div>
            <label htmlFor="g-deadline">Deadline</label>
            <input id="g-deadline" type="date" required min={todayIso()} value={deadline}
                   onChange={(e) => setDeadline(e.target.value)} style={fieldStyle} />
          </div>
          <div>
            <label htmlFor="g-minutes">Minutes per study day (10–480)</label>
            <input id="g-minutes" type="number" required min={10} max={480} step={5} value={minutes}
                   onChange={(e) => setMinutes(Number(e.target.value))} style={fieldStyle} />
          </div>
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="small muted" style={{ marginBottom: ".35rem" }}>Study days</legend>
          <div className="prep-chips">
            {WEEKDAYS.map((name, i) => {
              const on = days.includes(i);
              return (
                <button key={name} type="button" aria-pressed={on} onClick={() => toggleDay(i)} style={{ minWidth: 60 }}>
                  {on && <span aria-hidden>✓ </span>}{name}
                </button>
              );
            })}
          </div>
          {days.length === 0 && <div className="notice warn small" style={{ marginTop: ".5rem" }}>Pick at least one study day.</div>}
        </fieldset>
        <div>
          <label htmlFor="g-level">Your current level</label>
          <select id="g-level" value={level} onChange={(e) => { if (isLevel(e.target.value)) setLevel(e.target.value); }}>
            {LEVELS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
      </section>

      {goalType === "interview" && (
        <section className="glass card stack" aria-labelledby="prep-h">
          <h2 id="prep-h">Interview prep (optional)</h2>
          <p className="muted small" style={{ margin: 0 }}>
            Link an interview prep and we&apos;ll plan around its skill gaps (critical and high priority first) and add mock
            interviews near your deadline.
          </p>
          {prepError ? (
            <div className="notice info small">Interview preps couldn&apos;t be loaded right now. You can still plan from your documents.</div>
          ) : preps === null ? (
            <div className="skeleton" style={{ height: 44 }} role="status" aria-label="Loading your role preps" />
          ) : preps.length === 0 ? (
            <p className="muted small" style={{ margin: 0 }}>No interview preps yet. <Link href="/interview/new">Create one</Link> to plan from your skill gaps.</p>
          ) : (
            <div>
              <label htmlFor="g-prep">Prep</label>
              <select id="g-prep" value={prepId} onChange={(e) => setPrepId(e.target.value)}>
                <option value="">None: plan from documents only</option>
                {preps.map((p) => <option key={p.id} value={p.id}>{p.role_title}{p.company ? ` at ${p.company}` : ""}</option>)}
              </select>
            </div>
          )}
        </section>
      )}

      <section className="glass card stack" aria-labelledby="docs-h">
        <h2 id="docs-h">Documents to plan from{usePrep ? " (optional)" : ""}</h2>
        {!docs && !error && (
          <div className="stack-sm" role="status" aria-label="Loading documents">
            <div className="skeleton" style={{ height: 44 }} />
            <div className="skeleton" style={{ height: 44 }} />
          </div>
        )}
        {docs && docs.length === 0 && (
          <p className="muted small" style={{ margin: 0 }}>No ready documents yet. <Link href="/library">Upload a PDF in your Library</Link> first.</p>
        )}
        {docs && docs.length > 0 && (
          <ul className="doc-list">
            {docs.map((d) => (
              <li key={d.id}>
                <label className="row" style={{ gap: ".5rem", color: "var(--ink)", margin: 0, fontSize: "1rem", minHeight: 44 }}>
                  <input type="checkbox" checked={docIds.includes(d.id)} onChange={() => toggleDoc(d.id)} />
                  {d.title || d.filename}
                </label>
                <span className="muted small">{d.page_count ? `${d.page_count} pages` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {error && <div className="notice bad" role="alert">{error}</div>}
      <div className="row">
        <button type="submit" className="primary lg" disabled={!canSubmit || busy}>
          {busy && <span className="spinner" />} {busy ? "Building your plan…" : "Create plan"}
        </button>
        <Link href="/prep" className="btn ghost">Cancel</Link>
        {!canSubmit && !busy && (
          <span className="muted small" aria-live="polite">
            {title.trim() === "" ? "Add a title." : days.length === 0 ? "Pick study days." : docIds.length === 0 && !usePrep ? "Choose at least one document." : deadline < todayIso() ? "The deadline is in the past." : "Check minutes per day (10–480)."}
          </span>
        )}
      </div>
    </form>
  );
}
