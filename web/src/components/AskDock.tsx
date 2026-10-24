"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useId, useState } from "react";
import { notesApi, type NotesAnswer } from "@/lib/api-notes";
import Icon from "./Icon";
import NotesAnswerView from "./NotesAnswerView";
import { errorText } from "./today/labels";

/** "Ask your notes", docked bottom-right on every screen (the sketch's chat box). Notes first: opening it
 *  or asking never calls the AI; the AI is only offered, per answer, by NotesAnswerView. */
const AskCtx = createContext<(question?: string) => void>(() => {});
export const useAsk = () => useContext(AskCtx);

const DOCK_CSS = `
  .dock { position: fixed; right: 1rem; bottom: 1rem; z-index: 25; width: min(390px, calc(100vw - 2rem)); }
  @media (max-width: 720px) { .dock { bottom: calc(92px + env(safe-area-inset-bottom)); } }
  .dock-fab { margin-left: auto; display: flex; box-shadow: 0 12px 30px rgba(25,77,67,.25); }
  @media (max-width: 720px) { .dock-fab { width: 52px; height: 52px; padding: 0; } .dock-fab span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); } }
  .dock-open { max-height: min(72vh, 580px); display: flex; flex-direction: column; background: var(--solid); border: 1px solid var(--glass-edge);
    border-radius: var(--r-lg); box-shadow: 0 20px 50px rgba(40,55,50,.18); overflow: hidden; animation: dock-in .18s ease-out; }
  @keyframes dock-in { from { opacity: 0; transform: translateY(8px); } }
  @media (prefers-reduced-motion: reduce) { .dock-open { animation: none; } }
  .dock-head { display: flex; align-items: center; justify-content: space-between; padding: .55rem .55rem .55rem 1rem; border-bottom: 1px solid var(--line); }
  .dock-body { overflow: auto; padding: .9rem 1rem; display: grid; gap: .75rem; }
  .dock-form { display: flex; gap: .5rem; padding: .7rem; border-top: 1px solid var(--line); }
  .dock-form input { border-radius: var(--r-pill); }
`;

export function AskProvider({ children, dock = true }: { children: React.ReactNode; dock?: boolean }) {
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState<{ q: string; n: number } | null>(null);
  const ask = useCallback((question?: string) => {
    setOpen(true);
    if (question) setSeed({ q: question, n: Date.now() });
  }, []);
  return (
    <AskCtx.Provider value={ask}>
      {children}
      {dock && <Dock open={open} setOpen={setOpen} seed={seed} />}
    </AskCtx.Provider>
  );
}

function Dock({ open, setOpen, seed }: { open: boolean; setOpen: (v: boolean) => void; seed: { q: string; n: number } | null }) {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState("");
  const [res, setRes] = useState<NotesAnswer | null>(null);
  const [busy, setBusy] = useState<null | "ask" | "ai">(null);
  const [err, setErr] = useState<string | null>(null);
  const qid = useId();

  const run = useCallback(async (question: string, useAi: "explain" | "general" | null) => {
    setBusy(useAi ? "ai" : "ask");
    setErr(null);
    try {
      setRes(await notesApi.ask(question, useAi));
      setAsked(question);
    } catch (e) {
      setErr(errorText(e, "Something went wrong. Try again."));
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    if (!seed) return;
    setQ(seed.q);
    void run(seed.q, null);
  }, [seed, run]);

  return (
    <>
      <style>{DOCK_CSS}</style>
      {!open ? (
        <div className="dock">
          <button className="primary lg dock-fab" onClick={() => setOpen(true)} aria-label="Ask your notes" aria-expanded={false}>
            <Icon name="sparkle" size={18} /><span>Ask your notes</span>
          </button>
        </div>
      ) : (
        <section className="dock dock-open" aria-label="Ask your notes">
          <div className="dock-head">
            <b className="small row" style={{ gap: ".4rem" }}><Icon name="sparkle" size={15} /> Ask your notes</b>
            <span className="row" style={{ gap: ".25rem" }}>
              <Link href="/ask" className="tiny muted" style={{ padding: ".4rem" }}>Full page</Link>
              <button className="icon-btn ghost" aria-label="Close" aria-expanded onClick={() => setOpen(false)}><Icon name="close" size={18} /></button>
            </span>
          </div>
          <div className="dock-body" aria-live="polite" aria-busy={busy !== null}>
            {!res && !err && <p className="small muted" style={{ margin: 0 }}>Answers come from your own material first, with the page they&apos;re on. The AI is only used if you choose it.</p>}
            {err && <div className="notice bad small" role="alert">{err}</div>}
            {res && <NotesAnswerView res={res} asked={asked} busy={busy} run={(q2, ai) => void run(q2, ai)} />}
          </div>
          <form className="dock-form" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2) void run(q.trim(), null); }}>
            <label htmlFor={qid} className="sr-only">Your question</label>
            <input id={qid} type="text" value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} placeholder="Ask your knowledge…" autoFocus={!seed} />
            <button type="submit" className="primary icon-btn" aria-label="Ask" disabled={busy !== null || q.trim().length < 2}>
              {busy === "ask" ? <span className="spinner" aria-hidden /> : <Icon name="send" size={17} />}
            </button>
          </form>
        </section>
      )}
    </>
  );
}
