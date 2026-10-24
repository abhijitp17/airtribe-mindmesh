"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Icon from "@/components/Icon";
import { DocStatusBadge } from "@/components/ui";
import { api, type Doc } from "@/lib/api";

const LONG_BOOK_PAGES = 150;

/** Rough time left from the pace so far. Null until there's enough to go on. */
export function timeLeft(doc: Doc, now = Date.now()): string | null {
  const { pages_done: done, page_count: total, processing_started_at: started } = doc;
  if (!done || !total || !started || done >= total) return null;
  const elapsed = (now - new Date(started).getTime()) / 1000;
  if (!(elapsed > 2)) return null;
  const secs = (elapsed / done) * (total - done);
  if (secs < 45) return "less than a minute left";
  const mins = Math.round(secs / 60);
  return mins <= 1 ? "about a minute left" : `about ${mins} minutes left`;
}

/** Topics found in the first pages: top-level section names, in order, without repeats. */
function topicsFrom(sections: string[], max = 6): string[] {
  const out: string[] = [];
  for (const s of sections) {
    const top = s.split(" > ")[0]?.trim();
    if (top && !out.includes(top)) out.push(top);
    if (out.length >= max) break;
  }
  return out;
}

/**
 * Fills the processing wait (ux-research "Fill the processing wait"): progress with time left,
 * and once the first pages are saved, a 3-question quiz on them, what they cover, and a way in.
 */
export default function ProcessingWait({ doc, onStartEarly }: { doc: Doc; onStartEarly: () => void }) {
  const router = useRouter();
  const ready = Boolean(doc.pages_done);
  const [topics, setTopics] = useState<string[] | null>(null);
  const [quizBusy, setQuizBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || topics) return;
    api.chunks(doc.id).then((cs) => setTopics(topicsFrom(cs.map((c) => c.section)))).catch(() => setTopics([]));
  }, [ready, topics, doc.id]);

  async function quickQuiz() {
    setQuizBusy(true);
    setErr(null);
    try {
      const q = await api.createQuiz([doc.id], 3, "easy");
      router.push(`/quiz/${q.id}`);
    } catch (e) {
      setErr(`We couldn't make the quiz: ${e instanceof Error ? e.message : "unknown error"}. Try again in a moment.`);
      setQuizBusy(false);
    }
  }

  const total = doc.page_count;
  const done = doc.pages_done ?? 0;
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const left = timeLeft(doc);

  return (
    <>
      <div className="glass hero-card stack-sm">
        <div className="row spread">
          <span className="icon-well" aria-hidden><Icon name="book" size={24} /></span>
          <DocStatusBadge status={doc.status} />
        </div>
        <h1 style={{ fontSize: "1.5rem" }}>{doc.title || doc.filename}</h1>
        <div role="status" className="stack-sm">
          {total && done ? (
            <>
              <p style={{ margin: 0 }}>
                Read {done} of {total} pages{left ? `, ${left}` : ""}.
              </p>
              <div className="meter" role="progressbar" aria-label="Pages read" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
                <div style={{ width: `${pct}%` }} />
              </div>
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>Reading the first pages. They&apos;ll be ready to use in a moment.</p>
          )}
        </div>
        {total && total > LONG_BOOK_PAGES && (
          <p className="muted small" style={{ margin: 0 }}>
            This is a long one. You can leave this page; it stays in your Library and opens fully when it&apos;s done.
          </p>
        )}
      </div>

      {ready && (
        <section className="glass card stack-sm" aria-labelledby="wait-early-h">
          <h2 id="wait-early-h" style={{ fontSize: "1.2rem", margin: 0 }}>
            The first {done} pages are ready
          </h2>
          <p className="muted small" style={{ margin: 0 }}>
            Make a start while we read the rest. Answers and questions only use the pages read so far.
          </p>
          {topics && topics.length > 0 && (
            <div className="stack-sm">
              <span className="small" style={{ fontWeight: 500 }}>What it covers so far</span>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {topics.map((t) => <li key={t}>{t}</li>)}
              </ul>
            </div>
          )}
          {err && <div className="notice bad small" role="alert">{err}</div>}
          <div className="row" style={{ gap: ".5rem" }}>
            <button type="button" className="primary" onClick={() => void quickQuiz()} disabled={quizBusy} style={{ minHeight: 44 }}>
              {quizBusy && <span className="spinner" aria-hidden />} {quizBusy ? "Making questions…" : "Try 3 quick questions"}
            </button>
            <button type="button" onClick={onStartEarly} style={{ minHeight: 44 }}>Read and ask now</button>
          </div>
        </section>
      )}
    </>
  );
}
