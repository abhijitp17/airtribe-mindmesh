"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useId, useRef, useState, type Ref } from "react";
import Icon from "@/components/Icon";
import Shell, { BackLink } from "@/components/Shell";
import { SectionPath } from "@/components/SourceViewer";
import LibStyles from "@/components/library/styles";
import { pages } from "@/components/ui";
import { api, FLAG_REASON_LABEL, type Attempt, type FlagReason, type QuestionT, type Quiz } from "@/lib/api";

export default function QuizPage() {
  return (
    <Shell>
      <LibStyles />
      <Suspense fallback={<QuizSkeleton />}>
        <QuizView />
      </Suspense>
    </Shell>
  );
}

const TYPE_LABEL = { mcq: "Multiple choice", short: "Explain", applied: "Apply it" } as const;

// "How sure are you?" scale. Optional; helps separate lucky guesses from real knowledge.
const CONFIDENCE = [
  [1, "Guessing"],
  [2, "Unsure"],
  [3, "Fairly sure"],
  [4, "Confident"],
  [5, "Certain"],
] as const;

type SessionCtx = { sid: string; step: string } | null;

function QuizSkeleton() {
  return (
    <div role="status" className="stack narrow" aria-busy="true" aria-label="Loading quiz">
      <div className="skeleton" style={{ height: 64 }} />
      <div className="skeleton" style={{ height: 360, borderRadius: "var(--r-xl)" }} />
    </div>
  );
}

function QuizView() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const sid = search.get("session");
  const step = search.get("step");
  const session: SessionCtx = sid && step ? { sid, step } : null;

  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [current, setCurrent] = useState(0);
  const [showSummary, setShowSummary] = useState(false);
  const cardRef = useRef<HTMLHeadingElement>(null);
  const summaryRef = useRef<HTMLHeadingElement>(null);
  const moveFocus = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.quiz(id)
      .then((q) => {
        if (cancelled) return;
        setQuiz(q);
        // Resume at the first unanswered question.
        const first = q.questions.findIndex((x) => !x.last_attempt);
        if (first === -1 && q.questions.length) setShowSummary(true);
        else setCurrent(Math.max(0, first));
      })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : "unknown error"); });
    return () => { cancelled = true; };
  }, [id, reload]);

  // After "Next question" or a dot jump, move focus to the new card (or the summary).
  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    (showSummary ? summaryRef.current : cardRef.current)?.focus();
  }, [current, showSummary]);

  const backHref = quiz?.document_ids.length === 1 ? `/documents/${quiz.document_ids[0]}` : "/library";
  const backLabel = quiz?.document_ids.length === 1 ? "Document" : "Library";

  if (error) {
    return (
      <div className="stack narrow">
        <BackLink href="/library">Library</BackLink>
        <div className="notice bad row spread" role="alert">
          <span>We couldn&apos;t load this quiz ({error}). Check your connection and try again.</span>
          <button type="button" className="small" onClick={() => setReload((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
        </div>
      </div>
    );
  }
  if (!quiz) return <QuizSkeleton />;

  const total = quiz.questions.length;
  if (total === 0) {
    return (
      <div className="stack narrow">
        <BackLink href={backHref}>{backLabel}</BackLink>
        <div className="glass empty">
          <h3>This quiz has no questions</h3>
          <p>Open the document and make a new quiz from its Practise tab.</p>
          <Link href={backHref} className="btn dark">Open {backLabel.toLowerCase()}</Link>
        </div>
      </div>
    );
  }

  const answered = quiz.questions.filter((q) => q.last_attempt).length;
  const allDone = answered === total;
  const q = quiz.questions[Math.min(current, total - 1)];

  function go(i: number) {
    moveFocus.current = true;
    setShowSummary(false);
    setCurrent(i);
  }

  function next() {
    if (!quiz) return;
    const after = quiz.questions.findIndex((x, i) => i > current && !x.last_attempt);
    const before = quiz.questions.findIndex((x) => !x.last_attempt);
    const target = after !== -1 ? after : before;
    moveFocus.current = true;
    if (target === -1) setShowSummary(true);
    else setCurrent(target);
  }

  const position = showSummary ? `${answered} of ${total} answered` : `Question ${current + 1} of ${total}`;
  const pct = Math.round((answered / total) * 100);

  return (
    <div className="stack narrow">
      <div className="glass lib-qbar stack-sm" aria-label="Quiz progress" role="region">
        <div className="row spread" style={{ gap: ".5rem" }}>
          <BackLink href={backHref}>{backLabel}</BackLink>
          <strong style={{ fontWeight: 500 }} aria-live="polite">{position}</strong>
        </div>
        <div
          className="meter"
          role="progressbar"
          aria-label="Questions answered"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={answered}
          aria-valuetext={`${answered} of ${total} answered`}
        >
          <div style={{ width: `${pct}%`, transition: "width .25s ease" }} />
        </div>
      </div>

      {session && (
        <div className="notice info row" style={{ flexWrap: "nowrap" }}>
          <Icon name="today" size={18} />
          <span>Part of today&apos;s session</span>
        </div>
      )}

      <div>
        <h1 style={{ fontSize: "1.45rem", margin: 0 }}>{quiz.title}</h1>
        {quiz.focus && <p className="muted small" style={{ margin: ".2rem 0 0" }}>Focus: {quiz.focus}</p>}
      </div>

      <nav aria-label="Jump to a question">
        <ol className="lib-dots" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {quiz.questions.map((x, i) => {
            const done = !!x.last_attempt;
            const here = !showSummary && i === current;
            return (
              <li key={x.id}>
                <button
                  type="button"
                  className={done ? "done" : ""}
                  aria-current={here ? "step" : undefined}
                  aria-label={`Question ${i + 1}${done ? ", answered" : ", not answered yet"}`}
                  onClick={() => go(i)}
                >
                  {done && !here ? <Icon name="check" size={16} /> : i + 1}
                </button>
              </li>
            );
          })}
          {allDone && (
            <li>
              <button
                type="button"
                aria-current={showSummary ? "step" : undefined}
                aria-label="Your results"
                onClick={() => { moveFocus.current = true; setShowSummary(true); }}
                style={{ width: "auto", padding: "0 .9rem", borderRadius: "var(--r-pill)" }}
              >
                Results
              </button>
            </li>
          )}
        </ol>
      </nav>

      {showSummary ? (
        <Summary quiz={quiz} session={session} headingRef={summaryRef} onReview={go} />
      ) : (
        <QuestionCard
          key={q.id}
          q={q}
          index={current}
          total={total}
          headingRef={cardRef}
          isLastOpen={quiz.questions.filter((x) => !x.last_attempt && x.id !== q.id).length === 0}
          onNext={next}
          onAttempt={(a) => setQuiz((prev) => prev && { ...prev, questions: prev.questions.map((x) => (x.id === q.id ? { ...x, last_attempt: a } : x)) })}
        />
      )}
    </div>
  );
}

function QuestionCard({
  q, index, total, headingRef, isLastOpen, onNext, onAttempt,
}: {
  q: QuestionT;
  index: number;
  total: number;
  headingRef: Ref<HTMLHeadingElement>;
  isLastOpen: boolean;
  onNext: () => void;
  onAttempt: (a: Attempt) => void;
}) {
  const [selected, setSelected] = useState<number | null>(q.last_attempt?.selected_index ?? null);
  const [text, setText] = useState(q.last_attempt?.response_text ?? "");
  const [confidence, setConfidence] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [flagged, setFlagged] = useState(q.flagged);
  const [flagErr, setFlagErr] = useState<string | null>(null);
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState<FlagReason | null>(null);
  const [note, setNote] = useState("");
  const a = q.last_attempt;
  const locked = !!a && q.qtype === "mcq";
  const feedbackRef = useRef<HTMLDivElement>(null);
  const focusFeedback = useRef(false);
  const confLabel = useId();
  const confHint = useId();
  const promptId = useId();
  const answerId = useId();

  // After a submit, move keyboard focus to the feedback so screen-reader and keyboard users land on the result.
  useEffect(() => {
    if (focusFeedback.current && a) {
      focusFeedback.current = false;
      feedbackRef.current?.focus();
    }
  }, [a]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = q.qtype === "mcq" ? { selected_index: selected ?? undefined } : { answer_text: text };
      const attempt = await api.attempt(q.id, { ...body, confidence: confidence ?? undefined });
      focusFeedback.current = true;
      onAttempt(attempt);
    } catch (e) {
      setErr(`We couldn't check your answer: ${e instanceof Error ? e.message : "unknown error"}. Your answer is still here, so try again.`);
    } finally {
      setBusy(false);
    }
  }

  async function sendReport() {
    if (!reason) return;
    setFlagErr(null);
    try {
      await api.flag(q.id, reason, note.trim());
      setFlagged(true);
      setReporting(false);
    } catch (e) {
      setFlagErr(`We couldn't send your report (${e instanceof Error ? e.message : "unknown error"}).`);
    }
  }

  async function undoReport() {
    setFlagErr(null);
    try {
      await api.unflag(q.id);
      setFlagged(false);
      setReason(null);
      setNote("");
    } catch (e) {
      setFlagErr(`We couldn't undo the report (${e instanceof Error ? e.message : "unknown error"}).`);
    }
  }

  const canSubmit = q.qtype === "mcq" ? selected !== null : !!text.trim();

  return (
    <form className="glass lib-qcard stack" onSubmit={submit} aria-labelledby={promptId}>
      <div className="row spread" style={{ gap: ".5rem", alignItems: "flex-start" }}>
        <div className="row" style={{ gap: ".35rem" }}>
          <span className="badge info">{TYPE_LABEL[q.qtype]}</span>
          <span className="badge">{q.concept}</span>
          <span className="muted small" style={{ textTransform: "capitalize" }}>{q.difficulty}</span>
        </div>
        <span className="muted small">Question {index + 1} of {total}</span>
      </div>

      <h2
        id={promptId}
        ref={headingRef}
        tabIndex={-1}
        style={{ fontSize: "1.2rem", lineHeight: 1.4, fontWeight: 500, margin: 0, whiteSpace: "pre-wrap", outlineOffset: 6 }}
      >
        {q.prompt}
      </h2>

      {q.sources.length > 0 && (
        <div className="row small" style={{ gap: ".4rem" }}>
          <span className="muted">From</span>
          {q.sources.map((s) => (
            <Link
              key={s.chunk_id}
              href={`/documents/${s.document_id}`}
              title={s.section ? `${s.document_title}, ${pages(s.page_start, s.page_end)}: ${s.section.split(">").map((x) => x.trim()).join(" › ")}` : `${s.document_title}, ${pages(s.page_start, s.page_end)}`}
              style={{ display: "inline-flex", gap: ".35rem", alignItems: "center", maxWidth: "100%", minWidth: 0, minHeight: 32, textDecoration: "none" }}
            >
              <span className="cite" style={{ margin: 0 }}>{pages(s.page_start, s.page_end)}</span>
              {s.section && <SectionPath section={s.section} />}
            </Link>
          ))}
        </div>
      )}

      {q.qtype === "mcq" ? (
        <div role="radiogroup" aria-labelledby={promptId}>
          {q.options.map((opt, i) => {
            const cls = a ? (i === a.correct_index ? "correct" : i === a.selected_index ? "wrong" : "") : "";
            return (
              <label key={i} className={`option ${cls}`} style={{ color: "var(--ink)" }}>
                <input type="radio" name={`q-${q.id}`} checked={selected === i} disabled={locked} onChange={() => setSelected(i)} />
                <span style={{ flex: 1 }}>{opt}</span>
                {a && i === a.correct_index && <span className="badge good">Right answer</span>}
                {a && i === a.selected_index && i !== a.correct_index && <span className="badge gap">Your answer</span>}
              </label>
            );
          })}
        </div>
      ) : (
        <div>
          <label htmlFor={answerId}>Your answer</label>
          <textarea
            id={answerId}
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{ minHeight: 140 }}
            placeholder={q.qtype === "applied" ? "Work through the scenario. Show your reasoning." : "Explain in your own words."}
          />
        </div>
      )}

      {!locked && (
        <div className="stack-sm">
          <div role="group" aria-labelledby={confLabel} aria-describedby={confHint}>
            <div className="small" id={confLabel} style={{ marginBottom: ".3rem", color: "var(--ink)" }}>
              How sure are you? <span className="muted">(optional)</span>
            </div>
            <div className="row small lib-conf" style={{ gap: ".3rem" }}>
              <span className="muted" aria-hidden>Guessing</span>
              {CONFIDENCE.map(([n, label]) => {
                const on = confidence === n;
                return (
                  <button
                    type="button"
                    key={n}
                    className="small"
                    aria-pressed={on}
                    aria-label={`${n}: ${label}`}
                    title={label}
                    onClick={() => setConfidence(on ? null : n)}
                  >
                    {n}{on && <span aria-hidden> ✓</span>}
                  </button>
                );
              })}
              <span className="muted" aria-hidden>Certain</span>
            </div>
            <div className="muted small" id={confHint} style={{ marginTop: ".25rem" }}>
              Helps us tell lucky guesses from real knowledge.{confidence !== null && <> Selected: {CONFIDENCE.find(([n]) => n === confidence)?.[1]}.</>}
            </div>
          </div>
          {a ? (
            <button type="submit" className="block" disabled={busy || !canSubmit} style={{ minHeight: 48 }}>
              {busy && <span className="spinner" aria-hidden />} Check again
            </button>
          ) : (
            <button className="primary lg block" type="submit" disabled={busy || !canSubmit}>
              {busy && <span className="spinner" aria-hidden />} {busy ? "Checking…" : "Check answer"}
            </button>
          )}
        </div>
      )}
      {err && <div className="notice bad" role="alert">{err}</div>}
      {a && <Feedback a={a} qtype={q.qtype} focusRef={feedbackRef} />}
      {a && (
        <button type="button" className="dark lg block" onClick={onNext}>
          {isLastOpen ? "See your results" : "Next question"} <Icon name="arrow" size={18} />
        </button>
      )}
      {flagged ? (
        <div className="row small" style={{ justifyContent: "flex-end", gap: ".5rem" }} role="status">
          <span className="muted">Thanks, reported. This question won&apos;t count towards what you know.</span>
          <button type="button" className="ghost small" onClick={undoReport} style={{ minHeight: 44 }}>Undo</button>
        </div>
      ) : reporting ? (
        <fieldset className="glass stack-sm" style={{ border: 0, padding: ".75rem", margin: 0, borderRadius: "var(--r-md)" }}>
          <legend className="small" style={{ fontWeight: 500, padding: 0, marginBottom: ".4rem" }}>What&apos;s wrong with this question?</legend>
          <div className="prep-chips">
            {(Object.keys(FLAG_REASON_LABEL) as FlagReason[]).map((r) => (
              <button key={r} type="button" aria-pressed={reason === r} onClick={() => setReason(r)} style={{ minHeight: 44 }}>
                {reason === r && <span aria-hidden>✓ </span>}{FLAG_REASON_LABEL[r]}
              </button>
            ))}
          </div>
          <label htmlFor={`${promptId}-note`} className="small">Anything to add? <span className="muted">(optional)</span></label>
          <textarea id={`${promptId}-note`} rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="row" style={{ gap: ".5rem", justifyContent: "flex-end" }}>
            <button type="button" className="ghost small" onClick={() => setReporting(false)} style={{ minHeight: 44 }}>Cancel</button>
            <button type="button" className="small" onClick={sendReport} disabled={!reason} style={{ minHeight: 44 }}>Send report</button>
          </div>
        </fieldset>
      ) : (
        <div className="row small" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="ghost small" onClick={() => setReporting(true)} style={{ minHeight: 44 }}>
            <Icon name="flag" size={16} /> Report a problem with this question
          </button>
        </div>
      )}
      {flagErr && <div className="notice bad small" role="alert">{flagErr}</div>}
    </form>
  );
}

const VERDICT: Record<Attempt["verdict"], [string, string]> = {
  correct: ["Correct", "good"],
  partial: ["Partly correct", "warn"],
  incorrect: ["Not quite", "gap"],
  unassessed: ["Not checked", ""],
};

const CRITERION: Record<string, [string, string]> = {
  met: ["✓", "Covered"],
  partial: ["◐", "Partly covered"],
  missing: ["✗", "Missing"],
};

function Feedback({ a, qtype, focusRef }: { a: Attempt; qtype: QuestionT["qtype"]; focusRef?: Ref<HTMLDivElement> }) {
  const [label, cls] = VERDICT[a.verdict];
  return (
    <div className="feedback" role="status" aria-live="polite" ref={focusRef} tabIndex={-1}>
      <div className="row" style={{ marginBottom: ".45rem" }}>
        <span className={`badge ${cls}`}>{label}</span>
        {qtype !== "mcq" && a.verdict !== "unassessed" && <span className="muted small">{Math.round(a.score * 100)}% of the marking guide</span>}
      </div>
      {a.feedback && <p style={{ whiteSpace: "pre-wrap" }}>{a.feedback}</p>}
      {a.criteria.length > 0 && (
        <ul className="criteria">
          {a.criteria.map((c) => {
            const [mark, words] = CRITERION[c.status] ?? ["✗", "Missing"];
            return (
              <li key={c.criterion} style={{ display: "flex", gap: ".5rem", alignItems: "flex-start" }}>
                <span aria-hidden style={{ width: "1.1rem", flex: "none", textAlign: "center" }}>{mark}</span>
                <span>
                  <span style={{ fontWeight: 500 }}>{c.criterion}</span>{" "}
                  <span className="muted small">({words}, {c.points} pt{c.points === 1 ? "" : "s"})</span>
                  {c.evidence && <span className="small" style={{ display: "block" }}>From your answer: <mark>{c.evidence}</mark></span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {qtype === "mcq" && a.explanation && <p className="small muted" style={{ margin: ".4rem 0 0" }}>{a.explanation}</p>}
      {qtype !== "mcq" && (
        <details style={{ marginTop: ".5rem" }}>
          <summary className="small" style={{ minHeight: 44, display: "flex", alignItems: "center", cursor: "pointer" }}>Show a model answer</summary>
          <p className="small" style={{ marginTop: ".2rem", whiteSpace: "pre-wrap" }}>{a.answer_key}</p>
          {a.explanation && <p className="small muted">{a.explanation}</p>}
        </details>
      )}
    </div>
  );
}

type ConceptScore = { concept: string; score: number; count: number; unchecked: number };

function conceptWords(score: number): [string, string] {
  if (score >= 0.8) return ["Solid", "good"];
  if (score >= 0.5) return ["Getting there", "warn"];
  return ["Needs another look", "gap"];
}

function Summary({
  quiz, session, headingRef, onReview,
}: {
  quiz: Quiz;
  session: SessionCtx;
  headingRef: Ref<HTMLHeadingElement>;
  onReview: (i: number) => void;
}) {
  const router = useRouter();
  const map = new Map<string, ConceptScore>();
  for (const q of quiz.questions) {
    const s = map.get(q.concept) ?? { concept: q.concept, score: 0, count: 0, unchecked: 0 };
    if (q.last_attempt && q.last_attempt.verdict !== "unassessed") {
      s.score += q.last_attempt.score;
      s.count += 1;
    } else {
      s.unchecked += 1;
    }
    map.set(q.concept, s);
  }
  const concepts = [...map.values()];
  const weak = concepts.filter((c) => c.count > 0 && c.score / c.count < 0.5);
  const firstMissIdx = quiz.questions.findIndex((q) => q.last_attempt && q.last_attempt.verdict !== "correct");
  const docHref = quiz.document_ids.length === 1 ? `/documents/${quiz.document_ids[0]}` : "/library";
  const scored = quiz.questions.filter((q) => q.last_attempt && q.last_attempt.verdict !== "unassessed");
  const correct = scored.filter((q) => q.last_attempt?.verdict === "correct").length;

  return (
    <section className="glass lib-qcard stack" aria-labelledby="lib-sum-h">
      <div className="row" style={{ gap: ".75rem", flexWrap: "nowrap" }}>
        <span className="icon-well" aria-hidden><Icon name="chart" size={24} /></span>
        <div>
          <h2 id="lib-sum-h" ref={headingRef} tabIndex={-1} style={{ margin: 0 }}>Quiz done</h2>
          <p className="muted small" style={{ margin: 0 }}>
            {scored.length ? `${correct} of ${scored.length} fully correct.` : "Your answers are saved."} Results now feed into what you know.
          </p>
        </div>
      </div>

      <div>
        <h3>By concept</h3>
        <ul className="list">
          {concepts.map((c) => {
            const [words, cls] = c.count ? conceptWords(c.score / c.count) : ["Not enough answers yet", ""];
            return (
              <li key={c.concept}>
                <span style={{ minWidth: 0 }}>
                  <span style={{ fontWeight: 500 }}>{c.concept}</span>
                  <span className="muted small" style={{ display: "block" }}>
                    {c.count ? `${Math.round((c.score / c.count) * 100)}% across ${c.count} question${c.count === 1 ? "" : "s"}` : "No checked answers"}
                  </span>
                </span>
                <span className={`badge ${cls}`}>{words}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="glass" style={{ padding: "1rem" }}>
        <h3>What to do next</h3>
        {weak.length > 0 ? (
          <p className="small" style={{ marginBottom: ".6rem" }}>
            Re-read the pages on {weak.map((w) => w.concept).join(", ")}, then ask the tutor to explain the part that tripped you up. We&apos;ll bring
            {weak.length === 1 ? " it" : " them"} back for review soon.
          </p>
        ) : (
          <p className="small" style={{ marginBottom: ".6rem" }}>
            Nice work. We&apos;ll check these again in a few days so they stick. Try a harder quiz to stretch yourself.
          </p>
        )}
        <div className="row">
          {firstMissIdx !== -1 && (
            <button type="button" onClick={() => onReview(firstMissIdx)} style={{ minHeight: 44 }}>Review what I missed</button>
          )}
          <Link href={docHref} className={`btn ${session ? "" : "dark"}`} style={{ minHeight: 44 }}>
            {quiz.document_ids.length === 1 ? "Back to the document" : "Back to Library"}
          </Link>
        </div>
      </div>

      {session && (
        <button
          type="button"
          className="primary lg block"
          onClick={() => router.push(`/session/${encodeURIComponent(session.sid)}?done=${encodeURIComponent(session.step)}`)}
        >
          Back to today&apos;s session <Icon name="arrow" size={18} />
        </button>
      )}
    </section>
  );
}
