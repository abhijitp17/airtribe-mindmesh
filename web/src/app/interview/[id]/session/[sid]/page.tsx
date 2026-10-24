"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import Shell, { BackLink } from "@/components/Shell";
import EvaluationCard from "@/components/interview/EvaluationCard";
import Pill from "@/components/interview/Pill";
import PrepStyles from "@/components/interview/PrepStyles";
import SessionSummaryCard from "@/components/interview/SessionSummaryCard";
import { QUESTION_CAT, errMsg, focusLabel } from "@/components/interview/labels";
import { interviewApi, type InterviewSession, type InterviewTurn } from "@/lib/api-interview";
import VoiceControls from "@/components/interview/VoiceControls";

export default function MockInterviewPage() {
  return (
    <Shell>
      <MockInterview />
    </Shell>
  );
}

/** Main-question number for each turn, and the parent main question for follow-ups. */
function threadTurns(turns: InterviewTurn[]) {
  const sorted = [...turns].sort((a, b) => a.position - b.position);
  let qNum = 0;
  let parent: InterviewTurn | null = null;
  return sorted.map((t) => {
    if (t.kind === "question" || !parent) {
      qNum += 1;
      parent = t;
      return { turn: t, qNum, parent: null as InterviewTurn | null };
    }
    return { turn: t, qNum, parent };
  });
}

function MockInterview() {
  const { id, sid } = useParams<{ id: string; sid: string }>();
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<"answer" | "end" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const currentRef = useRef<HTMLHeadingElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const shouldFocus = useRef(false);

  useEffect(() => {
    interviewApi.session(sid).then(setSession).catch((e: unknown) => setError(errMsg(e, "We couldn't load this interview.")));
  }, [sid]);

  const threaded = useMemo(() => (session ? threadTurns(session.turns) : []), [session]);
  const current = session?.status === "active" ? threaded.filter((x) => x.turn.answer === null).at(-1) ?? null : null;
  const answered = threaded.filter((x) => x.turn.answer !== null);
  const mainCount = threaded.filter((x) => x.parent === null).length;

  // After a submit, move focus to the next question (or the summary) so keyboard users continue in place.
  useEffect(() => {
    if (!shouldFocus.current || !session) return;
    shouldFocus.current = false;
    if (session.status === "completed") summaryRef.current?.focus();
    else currentRef.current?.focus();
  }, [session]);

  async function submit() {
    const text = answer.trim();
    if (!text || busy || !session) return;
    setBusy("answer");
    setErr(null);
    try {
      const next = await interviewApi.answer(session.id, text);
      setAnswer("");
      shouldFocus.current = true;
      const last = [...next.turns].sort((a, b) => a.position - b.position).at(-1);
      setAnnounce(
        next.status === "completed"
          ? "Answer evaluated. Interview complete, summary below."
          : last && last.answer === null
            ? `Answer evaluated. ${last.kind === "follow_up" ? "Follow-up question" : "Next question"}: ${last.question}`
            : "Answer evaluated.",
      );
      setSession(next);
    } catch (e) {
      setErr(errMsg(e, "We couldn't score your answer. Your text is still here; try again."));
    } finally {
      setBusy(null);
    }
  }

  async function end() {
    if (!session || busy) return;
    if (!confirm("End this interview now? Unanswered questions won't be scored.")) return;
    setBusy("end");
    setErr(null);
    try {
      shouldFocus.current = true;
      setSession(await interviewApi.endSession(session.id));
      setAnnounce("Interview ended. Summary below.");
    } catch (e) {
      setErr(errMsg(e, "We couldn't end the interview. Try again."));
    } finally {
      setBusy(null);
    }
  }

  if (error) {
    return (
      <div className="prep-root stack" style={{ maxWidth: 760, margin: "0 auto" }}>
        <BackLink href={`/interview/${id}`}>Back to prep</BackLink>
        <div className="notice bad row spread" role="alert">
          <span>{error} Check your connection and try again.</span>
          <button type="button" onClick={() => { setError(null); interviewApi.session(sid).then(setSession).catch((e: unknown) => setError(errMsg(e, "We couldn't load this interview."))); }}>Try again</button>
        </div>
      </div>
    );
  }
  if (!session) {
    return (
      <div className="prep-root stack" style={{ maxWidth: 760, margin: "0 auto" }} role="status" aria-label="Loading the interview">
        <div className="skeleton" style={{ height: 70 }} />
        <div className="skeleton" style={{ height: 260, borderRadius: "var(--r-xl)" }} />
      </div>
    );
  }

  const progressN = Math.min(current ? current.qNum : mainCount, session.target_questions);

  return (
    <div className="prep-root stack" style={{ maxWidth: 760, margin: "0 auto" }}>
      <PrepStyles />
      <BackLink href={`/interview/${id}`}>Back to prep</BackLink>
      <div className="row spread" style={{ alignItems: "flex-end" }}>
        <div>
          <span className="prep-kicker">Mock interview</span>
          <h1 style={{ margin: ".1rem 0 0" }}>{focusLabel(session.focus)} questions</h1>
          <span className="muted small">
            {session.status === "completed"
              ? `Finished · ${answered.length} answer${answered.length === 1 ? "" : "s"}`
              : `Question ${progressN} of ${session.target_questions}`}
          </span>
        </div>
        {session.status === "active" && (
          <button type="button" className="ghost" onClick={end} disabled={busy !== null}>
            {busy === "end" && <span className="spinner" />} End interview
          </button>
        )}
      </div>
      {session.status === "active" && (
        <div className="meter" role="progressbar" aria-label="Interview progress" aria-valuemin={0} aria-valuemax={session.target_questions} aria-valuenow={progressN}>
          <div style={{ width: `${Math.round((progressN / Math.max(1, session.target_questions)) * 100)}%` }} />
        </div>
      )}

      <div className="sr-only" aria-live="polite" role="status">{announce}</div>

      {answered.length > 0 && (
        <ol aria-label="Answered questions" className="prep-list">
          {answered.map(({ turn, qNum, parent }) => (
            <li key={turn.id} className={parent ? "prep-followup" : undefined}>
              <TurnCard turn={turn} qNum={qNum} parent={parent} />
            </li>
          ))}
        </ol>
      )}

      {current && (
        <div className={current.parent ? "prep-followup" : undefined}>
          <form
            className="glass hero-card stack"
            onSubmit={(e) => { e.preventDefault(); submit(); }}
            aria-labelledby="current-q"
          >
            <TurnHeader turn={current.turn} qNum={current.qNum} parent={current.parent} />
            <h2 id="current-q" ref={currentRef} tabIndex={-1} className="prep-q" style={{ outline: "none" }}>
              {current.turn.question}
            </h2>
            <VoiceControls question={current.turn.question} disabled={busy !== null}
                           onText={(t) => setAnswer((a) => (a.trim() ? `${a.trim()} ${t}` : t))} />
            <div>
              <label htmlFor="answer">Your answer</label>
              <textarea
                id="answer"
                rows={7}
                value={answer}
                disabled={busy !== null}
                aria-describedby="answer-hint"
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    submit();
                  }
                }}
                placeholder={current.turn.category === "behavioral" ? "Use a real example: situation, task, what you did, the result, and what you learned." : "Answer as you would in the interview."}
              />
              <div id="answer-hint" className="muted small">Press Ctrl+Enter (⌘+Enter on Mac) to submit. Only use real details from your experience.</div>
            </div>
            {err && <div className="notice bad" role="alert">{err}</div>}
            <div className="row spread">
              {busy === "answer" ? (
                <span className="muted small" role="status"><span className="spinner" /> Reading your answer…</span>
              ) : <span />}
              <button type="submit" className="primary lg" disabled={busy !== null || !answer.trim()}>Submit answer</button>
            </div>
          </form>
        </div>
      )}

      {!current && session.status === "active" && (
        <div className="notice info row spread">
          <span>Waiting for the next question.</span>
          <button type="button" className="small" onClick={() => interviewApi.session(sid).then(setSession).catch((e: unknown) => setErr(errMsg(e, "We couldn't reload. Try again.")))}>Reload</button>
        </div>
      )}
      {!current && err && <div className="notice bad" role="alert">{err}</div>}

      {session.status === "completed" && (
        <div ref={summaryRef} tabIndex={-1} style={{ outline: "none" }} className="stack">
          {session.summary ? (
            <SessionSummaryCard summary={session.summary} />
          ) : (
            <div className="notice info">This interview has ended. There&apos;s no summary because no answers were scored.</div>
          )}
          <div className="row">
            <Link className="btn primary lg" href={`/interview/${id}`}>Back to my prep</Link>
            <Link className="btn lg" href="/prep">All of Prep</Link>
          </div>
        </div>
      )}
    </div>
  );
}

function TurnHeader({ turn, qNum, parent }: { turn: InterviewTurn; qNum: number; parent: InterviewTurn | null }) {
  return (
    <div className="row small" style={{ gap: ".35rem" }}>
      <Pill pair={QUESTION_CAT[turn.category]} prefix="Category:" />
      {turn.competency_name && <span className="badge">{turn.competency_name}</span>}
      <span className="muted">{parent ? `Follow-up to question ${qNum}` : `Question ${qNum}`}</span>
    </div>
  );
}

function TurnCard({ turn, qNum, parent }: { turn: InterviewTurn; qNum: number; parent: InterviewTurn | null }) {
  return (
    <article className="glass card stack" aria-label={parent ? `Follow-up to question ${qNum}` : `Question ${qNum}`}>
      <TurnHeader turn={turn} qNum={qNum} parent={parent} />
      {parent && (
        <div className="muted small">
          Following up on: <q>{parent.question.length > 120 ? `${parent.question.slice(0, 120)}…` : parent.question}</q>
        </div>
      )}
      <p className="prep-q" style={{ fontSize: "1.02rem" }}>{turn.question}</p>
      <div className="msg user" style={{ marginBottom: 0 }}>
        <span className="sr-only">Your answer: </span>
        <div className="bubble">{turn.answer}</div>
      </div>
      {turn.evaluation ? (
        <EvaluationCard ev={turn.evaluation} />
      ) : (
        <p className="muted small" style={{ margin: 0 }}>Not scored.</p>
      )}
    </article>
  );
}
