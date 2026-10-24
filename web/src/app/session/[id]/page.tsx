"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import Shell, { BackLink } from "@/components/Shell";
import StepList from "@/components/today/StepList";
import { WeekDots, weekHeadline } from "@/components/today/WeekCard";
import { KIND_ICON, KIND_LABEL, WIN_ICON, errorText, plural } from "@/components/today/labels";
import { api } from "@/lib/api";
import { engagementApi, type SessionStep, type StudySessionOut, type WeekOut } from "@/lib/api-engagement";

export default function SessionPage() {
  return (
    <Shell>
      <Suspense fallback={<SessionSkeleton />}>
        <SessionView />
      </Suspense>
    </Shell>
  );
}

const SESSION_CSS = `
  .today-session { max-width: 640px; margin: 0 auto; }
  .today-step-card { padding: 1.5rem 1.35rem; }
  .today-step-card h1 { font-size: clamp(1.45rem, 1.1rem + 1.6vw, 1.9rem); }
  .today-actions { display: grid; gap: .6rem; grid-template-columns: 1fr 1fr; }
  .today-actions > :first-child { grid-column: 1 / -1; }
  .today-wins li { opacity: 1; transform: none; }
  @media (prefers-reduced-motion: no-preference) {
    .today-wins li { animation: today-pop .5s cubic-bezier(.2,.8,.3,1.2) both; }
    .today-wins li:nth-child(2) { animation-delay: .08s; }
    .today-wins li:nth-child(3) { animation-delay: .16s; }
    .today-wins li:nth-child(n+4) { animation-delay: .24s; }
  }
  @keyframes today-pop { from { opacity: 0; transform: scale(.94) translateY(6px); } to { opacity: 1; transform: none; } }
`;

// Per-session browser memory: which steps were opened, and which quiz each quiz step created.
// The PATCH endpoint only accepts quiz_id together with a status, so we hold it until the step is marked done.
type LocalState = { opened: string[]; quizzes: Record<string, string> };
const storeKey = (sid: string) => `today-session-${sid}`;

function readLocal(sid: string): LocalState {
  try {
    const raw = window.sessionStorage.getItem(storeKey(sid));
    if (raw) {
      const v = JSON.parse(raw) as Partial<LocalState>;
      return { opened: Array.isArray(v.opened) ? v.opened : [], quizzes: v.quizzes && typeof v.quizzes === "object" ? v.quizzes : {} };
    }
  } catch {
    /* storage blocked or bad JSON */
  }
  return { opened: [], quizzes: {} };
}

function writeLocal(sid: string, s: LocalState) {
  try {
    window.sessionStorage.setItem(storeKey(sid), JSON.stringify(s));
  } catch {
    /* storage blocked: we still work, the step just shows "Start step" again */
  }
}

function SessionView() {
  const params = useParams<{ id: string }>();
  const sid = params?.id ?? "";
  const search = useSearchParams();
  const doneParam = search.get("done");
  const router = useRouter();

  const [session, setSession] = useState<StudySessionOut | null>(null);
  const [local, setLocal] = useState<LocalState>({ opened: [], quizzes: {} });
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"start" | "done" | "skip" | "complete" | null>(null);
  const [week, setWeek] = useState<WeekOut | null>(null);
  const handledDone = useRef(false);
  const completing = useRef(false);
  const stepHead = useRef<HTMLHeadingElement>(null);
  const prevStepId = useRef<string | null>(null);

  const updateLocal = useCallback((fn: (s: LocalState) => LocalState) => {
    setLocal((prev) => {
      const next = fn(prev);
      writeLocal(sid, next);
      return next;
    });
  }, [sid]);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      setSession(await engagementApi.session(sid));
    } catch (e) {
      setLoadErr(errorText(e, "Could not load this session."));
    }
  }, [sid]);

  useEffect(() => {
    if (!sid) return;
    setLocal(readLocal(sid));
    load();
  }, [sid, load]);

  // Returning from a quiz: /session/<sid>?done=<stepId> marks that step done once, then clears the param.
  useEffect(() => {
    if (!session || !doneParam || handledDone.current) return;
    handledDone.current = true;
    const step = session.steps.find((s) => s.id === doneParam);
    const finish = () => router.replace(`/session/${sid}`);
    if (!step || step.status !== "pending" || session.status !== "active") {
      finish();
      return;
    }
    const quizId = readLocal(sid).quizzes[step.id] ?? (step.target.type === "quiz" ? step.target.quiz_id ?? undefined : undefined);
    engagementApi.updateStep(sid, step.id, "done", quizId)
      .then(setSession)
      .catch((e) => setActionErr(errorText(e, "Could not mark that step done. Use Mark done below.")))
      .finally(finish);
  }, [session, doneParam, sid, router]);

  const current = session?.steps.find((s) => s.status === "pending") ?? null;
  const allSettled = !!session && session.steps.length > 0 && !current;

  // When every step is done or skipped, complete the session (once).
  useEffect(() => {
    if (!session || session.status !== "active" || !allSettled || completing.current) return;
    completing.current = true;
    setBusy("complete");
    engagementApi.completeSession(sid)
      .then((s) => setSession(s))
      .catch((e) => {
        completing.current = false;
        setActionErr(errorText(e, "Could not finish the session. Try again."));
      })
      .finally(() => setBusy(null));
  }, [session, allSettled, sid]);

  useEffect(() => {
    if (session?.status === "completed") engagementApi.week().then(setWeek).catch(() => setWeek(null));
  }, [session?.status]);

  // Move focus to the new step heading after a step changes (not on first load).
  useEffect(() => {
    const id = current?.id ?? null;
    if (prevStepId.current !== null && id && id !== prevStepId.current) stepHead.current?.focus();
    prevStepId.current = id;
  }, [current?.id]);

  async function openStep(step: SessionStep) {
    setActionErr(null);
    updateLocal((s) => (s.opened.includes(step.id) ? s : { ...s, opened: [...s.opened, step.id] }));
    const t = step.target;
    if (t.type === "quiz") {
      const existing = local.quizzes[step.id] ?? t.quiz_id;
      const back = `session=${encodeURIComponent(sid)}&step=${encodeURIComponent(step.id)}`;
      if (existing) {
        router.push(`/quiz/${existing}?${back}`);
        return;
      }
      if (!t.document_ids.length) {
        setActionErr("This step has no documents to quiz on. Skip it or add a document in Library.");
        return;
      }
      setBusy("start");
      try {
        const q = await api.createQuiz(t.document_ids, step.kind === "review" ? 3 : 5, "medium", t.focus ?? undefined);
        updateLocal((s) => ({ ...s, quizzes: { ...s.quizzes, [step.id]: q.id } }));
        router.push(`/quiz/${q.id}?${back}`);
      } catch (e) {
        setActionErr(errorText(e, "Could not create the quiz. Try again, or skip this step."));
        setBusy(null);
      }
      return;
    }
    if (t.type === "interview") router.push(t.session_id ? `/interview/${t.prep_id}/session/${t.session_id}` : `/interview/${t.prep_id}`);
    else if (t.type === "plan_item") router.push(`/goals/${t.goal_id}`);
    else router.push(t.href);
  }

  async function settle(step: SessionStep, status: "done" | "skipped") {
    setBusy(status === "done" ? "done" : "skip");
    setActionErr(null);
    try {
      const quizId = status === "done" ? local.quizzes[step.id] : undefined;
      setSession(await engagementApi.updateStep(sid, step.id, status, quizId));
    } catch (e) {
      setActionErr(errorText(e, "Could not save that. Try again."));
    } finally {
      setBusy(null);
    }
  }

  if (loadErr) {
    return (
      <div className="today-session stack">
        <style>{SESSION_CSS}</style>
        <BackLink href="/">Today</BackLink>
        <div className="notice bad row spread" role="alert">
          <span>{loadErr} Check your connection and try again.</span>
          <button type="button" onClick={load} style={{ minHeight: 44 }}>Try again</button>
        </div>
      </div>
    );
  }

  if (!session) return <SessionSkeleton />;

  if (session.status === "completed") {
    return <Celebration session={session} week={week} />;
  }

  if (session.status === "abandoned") {
    return (
      <div className="today-session stack">
        <style>{SESSION_CSS}</style>
        <BackLink href="/">Today</BackLink>
        <div className="glass card empty">
          <h3>This session was closed</h3>
          <p>Start a fresh one from Today. It only takes a minute to pick up again.</p>
          <Link href="/" className="btn dark" style={{ minHeight: 44 }}>Back to Today</Link>
        </div>
      </div>
    );
  }

  const total = session.steps.length;
  const settledCount = session.steps.filter((s) => s.status !== "pending").length;
  const index = current ? session.steps.findIndex((s) => s.id === current.id) : total - 1;
  const minutesLeft = session.steps.filter((s) => s.status === "pending").reduce((n, s) => n + s.minutes, 0);
  const opened = current ? local.opened.includes(current.id) : false;

  return (
    <div className="today-session stack">
      <style>{SESSION_CSS}</style>
      <div>
        <BackLink href="/">Today</BackLink>
        <div className="row spread small" style={{ marginBottom: ".4rem" }}>
          <span>{total ? `Step ${Math.min(index + 1, total)} of ${total}` : "No steps"}</span>
          <span className="muted">{minutesLeft > 0 ? `About ${minutesLeft} min left` : "Finishing up"}</span>
        </div>
        <div
          className="meter"
          role="progressbar"
          aria-label="Session progress"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={settledCount}
          aria-valuetext={`${settledCount} of ${total} steps finished`}
        >
          <div style={{ width: `${total ? (settledCount / total) * 100 : 0}%`, transition: "width .3s ease" }} />
        </div>
      </div>

      {total === 0 && (
        <div className="glass card empty">
          <h3>Nothing to do in this session</h3>
          <p>Add a document or a job so we can plan your next one.</p>
          <Link href="/" className="btn dark" style={{ minHeight: 44 }}>Back to Today</Link>
        </div>
      )}

      {busy === "complete" && (
        <div className="glass card row" role="status"><span className="spinner" aria-hidden /> Wrapping up your session…</div>
      )}

      {current && (
        <section className="glass hero-card today-step-card stack" aria-labelledby="today-step-h">
          <div className="row" style={{ gap: ".75rem" }}>
            <span className="icon-well" aria-hidden><Icon name={KIND_ICON[current.kind]} size={24} /></span>
            <span className="badge">{KIND_LABEL[current.kind]}</span>
            <span className="badge"><Icon name="clock" size={14} /> {current.minutes} min</span>
          </div>
          <div>
            <h1 id="today-step-h" ref={stepHead} tabIndex={-1}>{current.title}</h1>
            <p className="muted" style={{ margin: 0 }}>{current.detail}</p>
          </div>
          {actionErr && <div className="notice bad" role="alert">{actionErr}</div>}
          <div className="today-actions">
            {opened ? (
              <button type="button" className="dark lg" onClick={() => settle(current, "done")} disabled={busy !== null} style={{ minHeight: 52 }}>
                {busy === "done" && <span className="spinner" aria-hidden />} <Icon name="check" size={18} /> Mark done
              </button>
            ) : (
              <button type="button" className="primary lg" onClick={() => openStep(current)} disabled={busy !== null} style={{ minHeight: 52 }}>
                {busy === "start" && <span className="spinner" aria-hidden />} Start step
              </button>
            )}
            {opened ? (
              <button type="button" onClick={() => openStep(current)} disabled={busy !== null} style={{ minHeight: 48 }}>
                {busy === "start" && <span className="spinner" aria-hidden />} Open again
              </button>
            ) : (
              <button type="button" onClick={() => settle(current, "done")} disabled={busy !== null} style={{ minHeight: 48 }}>
                {busy === "done" && <span className="spinner" aria-hidden />} Mark done
              </button>
            )}
            <button type="button" className="ghost" onClick={() => settle(current, "skipped")} disabled={busy !== null} style={{ minHeight: 48 }}>
              {busy === "skip" && <span className="spinner" aria-hidden />} Skip
            </button>
          </div>
        </section>
      )}

      {!current && actionErr && (
        <div className="notice bad row spread" role="alert">
          <span>{actionErr}</span>
          <button type="button" onClick={() => { setActionErr(null); load(); }} style={{ minHeight: 44 }}>Try again</button>
        </div>
      )}

      {total > 1 && (
        <section className="glass card" aria-labelledby="today-all-h" style={{ padding: ".9rem 1.1rem" }}>
          <h2 id="today-all-h" className="small muted" style={{ fontWeight: 500, margin: "0 0 .25rem" }}>This session</h2>
          <StepList steps={session.steps} currentId={current?.id ?? null} />
        </section>
      )}
    </div>
  );
}

function Celebration({ session, week }: { session: StudySessionOut; week: WeekOut | null }) {
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => { head.current?.focus(); }, []);
  const done = session.steps.filter((s) => s.status === "done").length;

  return (
    <div className="today-session stack">
      <style>{SESSION_CSS}</style>
      <BackLink href="/">Today</BackLink>
      <section className="glass hero-card stack" aria-labelledby="today-done-h" aria-live="polite">
        <span className="icon-well" aria-hidden><Icon name="sparkle" size={26} /></span>
        <div>
          <h1 id="today-done-h" ref={head} tabIndex={-1} style={{ fontSize: "1.7rem" }}>Session done</h1>
          <p className="muted" style={{ margin: 0 }}>
            You finished {plural(done, "step")} of {session.steps.length}{session.wins.length ? ". Here's what changed." : "."}
          </p>
        </div>
        {session.wins.length > 0 ? (
          <ul className="list today-wins">
            {session.wins.map((w, i) => (
              <li key={`${w.kind}-${i}`} style={{ justifyContent: "flex-start", alignItems: "flex-start" }}>
                <span className="icon-well sm" aria-hidden><Icon name={WIN_ICON[w.kind]} /></span>
                <span>
                  <span style={{ display: "block", fontWeight: 500 }}>{w.title}</span>
                  <span className="muted small">{w.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small" style={{ margin: 0 }}>No level changes this time. Every answer helps us see what you know, and changes usually show after two or three sessions.</p>
        )}
      </section>

      <section className="glass card row spread" aria-label="This week">
        {week ? (
          <>
            <span style={{ fontWeight: 500 }}>{weekHeadline(week)}</span>
            <WeekDots days={week.days} />
          </>
        ) : (
          <div className="skeleton" style={{ height: 44, width: "100%" }} role="status" aria-label="Loading your week" />
        )}
      </section>

      <Link href="/" className="btn primary lg block" style={{ minHeight: 52 }}>Back to Today</Link>
      <p className="small" style={{ textAlign: "center", margin: 0 }}><Link href="/progress">See what you know</Link></p>
    </div>
  );
}

function SessionSkeleton() {
  return (
    <div className="today-session stack" role="status" aria-label="Loading session">
      <style>{SESSION_CSS}</style>
      <div className="skeleton" style={{ height: 18, width: 80 }} />
      <div className="skeleton" style={{ height: 8 }} />
      <div className="skeleton" style={{ height: 280, borderRadius: "var(--r-xl)" }} />
      <div className="skeleton" style={{ height: 140, borderRadius: "var(--r-lg)" }} />
    </div>
  );
}
