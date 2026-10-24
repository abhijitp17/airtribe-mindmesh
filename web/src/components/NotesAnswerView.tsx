"use client";

import Link from "next/link";
import type { NotesAnswer } from "@/lib/api-notes";

export const LOCAL = new Set(["graph", "reused", "notes"]);
const BADGE: Record<string, string> = {
  graph: "From your progress · no AI used",
  reused: "Your earlier verified answer · no AI used",
  notes: "Quoted from your notes · no AI used",
  ai: "AI answer, cited from your notes",
  general: "General AI answer · not from your notes",
};
export const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/** One notes-first answer with its sources, and the AI offered only as a choice (Ask page, map chat). */
export default function NotesAnswerView({ res, asked, busy, run, tokensPerAi = 0 }: {
  res: NotesAnswer; asked: string; busy: null | "ask" | "ai";
  run: (question: string, useAi: "explain" | "general" | null) => void; tokensPerAi?: number;
}) {
  return (
    <div className="glass card stack-sm">
      {BADGE[res.mode] && <span className={`badge ${LOCAL.has(res.mode) ? "good" : "info"}`} style={{ alignSelf: "flex-start" }}>{BADGE[res.mode]}</span>}
      {res.answer && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{res.answer}</p>}
      {res.citations.length > 0 && (
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }} aria-label="Sources">
          {res.citations.filter((c, i, all) => all.findIndex((x) => x.chunk_id === c.chunk_id) === i).map((c, i) => (
            <li key={`${c.chunk_id}-${i}`}>
              {c.label && <b>[{c.label}] </b>}
              <Link href={`/documents/${c.document_id}?page=${c.page_start}`}>p. {c.page_start}{c.page_end !== c.page_start ? `–${c.page_end}` : ""}</Link>
              {c.section && <span className="muted"> · {c.section.split(" > ").slice(-1)[0]}</span>}
            </li>
          ))}
        </ul>
      )}

      {res.mode === "needs_ai" && (
        <>
          <p className="muted small" style={{ margin: 0 }}>{res.reason} Here&apos;s what your notes say, free:</p>
          <ul className="stack-sm" style={{ margin: 0, paddingLeft: "1.1rem" }} aria-label="Passages from your notes">
            {res.passages.map((p) => (
              <li key={p.chunk_id} className="small">
                <Link href={`/documents/${p.document_id}?page=${p.page_start}`}>p. {p.page_start}</Link>: {p.text}{p.text.length >= 600 ? "…" : ""}
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => void run(asked, "explain")} disabled={busy !== null} style={{ alignSelf: "flex-start", minHeight: 44 }}>
            {busy === "ai" && <span className="spinner" aria-hidden />} Explain with AI (about {fmt(res.ai_tokens_estimate)} tokens)
          </button>
        </>
      )}

      {res.mode === "not_found" && (
        <>
          <p style={{ margin: 0 }}>Your notes don&apos;t cover this yet.</p>
          <div className="row" style={{ gap: ".5rem" }}>
            <button type="button" onClick={() => void run(asked, "general")} disabled={busy !== null} style={{ minHeight: 44 }}>
              {busy === "ai" && <span className="spinner" aria-hidden />} Ask the AI: general knowledge (about {fmt(res.ai_tokens_estimate)} tokens)
            </button>
            <Link href="/library" className="btn ghost" style={{ minHeight: 44 }}>Add material</Link>
          </div>
        </>
      )}

      {LOCAL.has(res.mode) && (
        <button type="button" className="ghost small" onClick={() => void run(asked, "explain")} disabled={busy !== null} style={{ alignSelf: "flex-start", minHeight: 44 }}>
          Want it explained? Use AI (about {fmt(res.ai_tokens_estimate || tokensPerAi)} tokens)
        </button>
      )}
    </div>
  );
}
