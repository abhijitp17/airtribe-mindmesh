"use client";

import { Fragment, useEffect, useId, useRef, useState } from "react";
import { api, type AnswerStatus, type Citation } from "@/lib/api";
import Icon from "./Icon";
import { SectionPath, type Focus } from "./SourceViewer";
import { AnswerStatusBadge, pages } from "./ui";

const STARTERS = ["Summarise the key ideas", "Explain the hardest concept simply", "Give me a real-world example"] as const;

type Turn = { role: "user" | "assistant"; content: string; status?: AnswerStatus | null; citations?: Citation[]; question?: string };

export default function Tutor({ documentIds, onCite }: { documentIds: string[]; onCite: (f: Omit<Focus, "nonce">) => void }) {
  const [turns, setTurns] = useState<Turn[] | null>(null);
  const [histErr, setHistErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [level, setLevel] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const lastAnswer = useRef<HTMLDivElement>(null);
  const focusAnswer = useRef(false);
  const startersLabel = useId();
  const inputId = useId();
  const levelId = useId();

  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setHistErr(null);
    api.history(documentIds)
      .then((h) => {
        if (!cancelled) setTurns(h.map((m) => ({ role: m.role, content: m.content, status: m.status, citations: m.citations })));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setHistErr(e instanceof Error ? e.message : "unknown error");
        setTurns((t) => t ?? []);
      });
    return () => { cancelled = true; };
  }, [documentIds, reload]);

  const count = turns?.length ?? 0;
  useEffect(() => {
    if (focusAnswer.current) {
      focusAnswer.current = false;
      lastAnswer.current?.focus({ preventScroll: true });
      lastAnswer.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      end.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [count]);

  async function ask(question: string, allowGeneral = false) {
    setBusy(true);
    setErr(null);
    if (!allowGeneral) setTurns((t) => [...(t ?? []), { role: "user", content: question }]);
    try {
      const r = await api.ask(question, documentIds, level, allowGeneral);
      focusAnswer.current = true;
      setTurns((t) => [...(t ?? []), { role: "assistant", content: r.answer, status: r.status, citations: r.citations, question }]);
    } catch (e) {
      setErr(`The tutor couldn't answer: ${e instanceof Error ? e.message : "unknown error"}. Try asking again.`);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: { preventDefault(): void }) {
    e.preventDefault();
    const text = q.trim();
    if (!text || busy) return;
    setQ("");
    void ask(text);
  }

  const lastAssistant = turns ? turns.map((t) => t.role).lastIndexOf("assistant") : -1;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "1rem" }} role="log" aria-live="polite" aria-label="Conversation with the tutor">
        {turns === null && (
          <div role="status" className="stack-sm" aria-busy="true" aria-label="Loading conversation">
            <div className="skeleton" style={{ height: 48, width: "60%", marginLeft: "auto" }} />
            <div className="skeleton" style={{ height: 96 }} />
          </div>
        )}
        {histErr && (
          <div className="notice bad row spread" role="alert" style={{ marginBottom: "1rem" }}>
            <span>We couldn&apos;t load earlier messages ({histErr}).</span>
            <button type="button" className="small" onClick={() => setReload((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
          </div>
        )}
        {turns?.length === 0 && (
          <div className="empty" style={{ padding: "1.5rem .5rem" }}>
            <span className="icon-well" aria-hidden style={{ margin: "0 auto .75rem" }}><Icon name="sparkle" size={24} /></span>
            <h3>Ask anything about this document</h3>
            <p className="small" style={{ maxWidth: 380, margin: "0 auto 1rem" }}>
              Every answer points to the exact page it comes from. Tap a page to see it in the reader.
            </p>
            <p className="small" id={startersLabel} style={{ marginBottom: ".5rem" }}>Not sure where to start? Try one of these:</p>
            <div className="row" style={{ gap: ".45rem", justifyContent: "center" }} role="group" aria-labelledby={startersLabel}>
              {STARTERS.map((s) => (
                <button key={s} type="button" className="small lib-chip" disabled={busy} onClick={() => void ask(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns?.map((t, i) => (
          <div key={i} className={`msg ${t.role}`}>
            {t.role === "user" ? (
              <>
                <span className="sr-only">You asked: </span>
                <div className="bubble">{t.content}</div>
              </>
            ) : (
              <div
                ref={i === lastAssistant ? lastAnswer : undefined}
                tabIndex={i === lastAssistant ? -1 : undefined}
                style={{ scrollMarginTop: 8 }}
              >
                <div className="row" style={{ marginBottom: ".35rem", gap: ".4rem" }}>
                  <span className="sr-only">Tutor answer.</span>
                  {t.status && <AnswerStatusBadge status={t.status} />}
                </div>
                <div className="bubble answer-page">
                  <AnswerText text={t.content} citations={t.citations ?? []} onCite={onCite} />
                </div>
                {!!t.citations?.length && (
                  <div className="cite-list" aria-label="Where this comes from">
                    {t.citations.map((c) => (
                      <button
                        key={c.label}
                        type="button"
                        className="cite-item margin-note"
                        style={{ minHeight: 44 }}
                        onClick={() => onCite({ page: c.page_start, chunkId: c.chunk_id, quote: c.quote })}
                        aria-label={`Show ${pages(c.page_start, c.page_end)} of ${c.document_title} in the reader`}
                      >
                        <span className="row" style={{ gap: ".4rem", flexWrap: "nowrap", minWidth: 0 }}>
                          <span className="cite" style={{ cursor: "inherit", margin: 0, flex: "none" }}>{pages(c.page_start, c.page_end)}</span>
                          <span className="small" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {c.section ? <SectionPath section={c.section} /> : c.document_title}
                          </span>
                        </span>
                        <span style={{ display: "block", marginTop: ".35rem" }}><mark>{c.quote}</mark></span>
                      </button>
                    ))}
                  </div>
                )}
                {t.status === "not_found" && t.question && (
                  <button type="button" className="small" style={{ marginTop: ".6rem", minHeight: 44 }} disabled={busy} onClick={() => void ask(t.question ?? "", true)}>
                    Explain from general knowledge (clearly labelled)
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="muted small row" role="status" style={{ gap: ".45rem" }}>
            <span className="spinner" aria-hidden /> Reading your pages…
          </div>
        )}
        {err && <div className="notice bad" role="alert">{err}</div>}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="glass lib-composer" aria-label="Ask the tutor">
        <label htmlFor={inputId} className="sr-only">Your question</label>
        <textarea
          id={inputId}
          rows={2}
          placeholder="Ask about this document…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }}
        />
        <div className="row spread" style={{ gap: ".5rem" }}>
          <div className="row small" style={{ gap: ".4rem", flexWrap: "nowrap" }}>
            <label htmlFor={levelId} style={{ margin: 0, whiteSpace: "nowrap" }}>Explain as</label>
            <select id={levelId} value={level} onChange={(e) => setLevel(e.target.value)} style={{ width: "auto", minHeight: 44, padding: ".4rem .6rem" }}>
              <option value="beginner">Beginner</option>
              <option value="standard">Standard</option>
              <option value="advanced">Advanced</option>
            </select>
          </div>
          <button className="primary" type="submit" disabled={busy || !q.trim()} style={{ minHeight: 44, minWidth: 88 }}>
            {busy && <span className="spinner" aria-hidden />} Ask
          </button>
        </div>
      </form>
    </div>
  );
}

/** Render [S#] markers as small peach page pills. */
function AnswerText({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (f: Omit<Focus, "nonce">) => void }) {
  const byLabel = Object.fromEntries(citations.map((c) => [c.label, c]));
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = /^\[(S\d+)\]$/.exec(p);
        const c = m ? byLabel[m[1]] : undefined;
        if (c) {
          return (
            <button
              key={i}
              type="button"
              className="cite"
              title={`${c.document_title}, ${pages(c.page_start, c.page_end)}`}
              aria-label={`Source: ${pages(c.page_start, c.page_end)}. Show in reader`}
              onClick={() => onCite({ page: c.page_start, chunkId: c.chunk_id, quote: c.quote })}
            >
              {pages(c.page_start, c.page_end)}
            </button>
          );
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}
