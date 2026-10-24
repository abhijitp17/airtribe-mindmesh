"use client";

import { useEffect, useId, useState } from "react";
import NotesAnswerView, { fmt } from "@/components/NotesAnswerView";
import Shell from "@/components/Shell";
import { notesApi, type NotesAnswer, type NotesStats } from "@/lib/api-notes";

export default function AskPage() {
  return (
    <Shell>
      <Ask />
    </Shell>
  );
}

/** Ask my notes (P3): answers come from the knowledge base first; the AI is used only when you choose it. */
function Ask() {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState("");
  const [res, setRes] = useState<NotesAnswer | null>(null);
  const [stats, setStats] = useState<NotesStats | null>(null);
  const [busy, setBusy] = useState<null | "ask" | "ai">(null);
  const [err, setErr] = useState<string | null>(null);
  const qid = useId();

  const loadStats = () => notesApi.stats().then(setStats).catch(() => setStats(null));
  useEffect(() => { void loadStats(); }, []);

  async function run(question: string, useAi: "explain" | "general" | null) {
    setBusy(useAi ? "ai" : "ask");
    setErr(null);
    try {
      setRes(await notesApi.ask(question, useAi));
      setAsked(question);
      void loadStats();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong. Try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack narrow">
      <header className="stack-sm">
        <h1 style={{ margin: 0 }}>Ask my notes</h1>
        <p className="muted" style={{ margin: 0 }}>
          Answers come from your own material first, at no AI cost. When your notes aren&apos;t enough, you choose whether to use the AI.
        </p>
        {stats && (stats.from_notes > 0 || stats.with_ai > 0) && (
          <p className="notice info small" style={{ margin: 0 }} aria-label="Savings this month">
            Last {stats.days} days: <b>{stats.from_notes}</b> answered from your notes, <b>{stats.with_ai}</b> with the AI ·
            about <b>{fmt(stats.tokens_saved_estimate)}</b> tokens saved.
          </p>
        )}
      </header>

      <form className="glass card stack-sm" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void run(q.trim(), null); }}>
        <label htmlFor={qid}>Your question</label>
        <input id={qid} type="text" value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000}
               placeholder="For example: What is Little's Law? · Which notes cover forecasting? · How well do I know NPV?" />
        <button type="submit" className="primary" disabled={busy !== null || q.trim().length < 2} style={{ alignSelf: "flex-start", minHeight: 44 }}>
          {busy === "ask" && <span className="spinner" aria-hidden />} Ask my notes
        </button>
      </form>

      {err && <div className="notice bad" role="alert">{err}</div>}

      <section aria-live="polite" aria-busy={busy !== null} className="stack-sm">
        {res && <NotesAnswerView res={res} asked={asked} busy={busy} run={(q2, ai) => void run(q2, ai)} tokensPerAi={stats?.tokens_per_ai_answer} />}
      </section>
    </div>
  );
}
