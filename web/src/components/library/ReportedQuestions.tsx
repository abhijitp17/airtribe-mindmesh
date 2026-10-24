"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, FLAG_REASON_LABEL, type FlaggedQuestion } from "@/lib/api";

/** The learner's own reported questions: what they reported and why, with Undo. Hidden when empty. */
export default function ReportedQuestions() {
  const [items, setItems] = useState<FlaggedQuestion[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.flaggedQuestions().then(setItems).catch(() => setItems([]));
  }, []);

  async function undo(id: string) {
    setErr(null);
    try {
      await api.unflag(id);
      setItems((xs) => (xs ?? []).filter((x) => x.id !== id));
    } catch (e) {
      setErr(`We couldn't undo that report (${e instanceof Error ? e.message : "unknown error"}).`);
    }
  }

  if (!items || items.length === 0) return null;
  return (
    <section aria-labelledby="lib-reported-h" className="stack-sm">
      <h2 id="lib-reported-h" style={{ margin: "1rem 0 0" }}>Reported questions</h2>
      <p className="muted small" style={{ margin: 0 }}>
        These don&apos;t count towards what you know. Undo a report if the question was fine after all.
      </p>
      {err && <div className="notice bad small" role="alert">{err}</div>}
      <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {items.map((q) => (
          <li key={q.id} className="glass row" style={{ padding: ".75rem 1rem", gap: ".75rem", alignItems: "flex-start", borderRadius: "var(--r-md)" }}>
            <div style={{ flex: 1, minWidth: 0 }} className="stack-sm">
              <span style={{ fontWeight: 500 }}>{q.prompt}</span>
              <span className="small muted">
                <span className="badge gap">{FLAG_REASON_LABEL[q.reason] ?? "Reported"}</span>
                {q.note && <> · &ldquo;{q.note}&rdquo;</>}
                {" · "}<Link href={`/quiz/${q.quiz_id}`}>{q.quiz_title}</Link>
              </span>
            </div>
            <button type="button" className="ghost small" onClick={() => void undo(q.id)} style={{ minHeight: 44, flex: "none" }}
                    aria-label={`Undo report: ${q.prompt.slice(0, 80)}`}>
              Undo
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
