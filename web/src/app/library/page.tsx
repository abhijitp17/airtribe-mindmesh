"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Icon from "@/components/Icon";
import Shell from "@/components/Shell";
import DocCard, { isBusy } from "@/components/library/DocCard";
import LibStyles from "@/components/library/styles";
import Uploader from "@/components/library/Uploader";
import ReportedQuestions from "@/components/library/ReportedQuestions";
import { api, type Doc, type QuizSummary } from "@/lib/api";

export default function LibraryPage() {
  return (
    <Shell>
      <LibStyles />
      <Library />
    </Shell>
  );
}

function Library() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quizErr, setQuizErr] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    try {
      setDocs(await api.documents());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unknown error");
    }
  }, []);

  const loadQuizzes = useCallback(async () => {
    try {
      setQuizzes(await api.quizzes());
      setQuizErr(null);
    } catch (e) {
      setQuizErr(e instanceof Error ? e.message : "unknown error");
    }
  }, []);

  useEffect(() => {
    void loadDocs();
    void loadQuizzes();
  }, [loadDocs, loadQuizzes]);

  // Poll while any document is still processing.
  const processing = docs?.some(isBusy) ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => void loadDocs(), 2000);
    return () => clearInterval(t);
  }, [processing, loadDocs]);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p>Your documents. Private to you.</p>
        </div>
      </div>

      <Uploader onUploaded={() => void loadDocs()} />

      {processing && (
        <div className="notice info row" role="status" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <span className="spinner" aria-hidden style={{ marginTop: 4 }} />
          <span>We&apos;ll have it ready in a minute. Meanwhile, you can ask a question as soon as the first pages are in.</span>
        </div>
      )}

      <section aria-labelledby="lib-docs-h" className="stack-sm">
        <div className="row spread">
          <h2 id="lib-docs-h" style={{ margin: 0 }}>Documents</h2>
          {docs && docs.length > 0 && <span className="muted small">{docs.length} document{docs.length === 1 ? "" : "s"}</span>}
        </div>

        {error && (
          <div className="notice bad row spread" role="alert">
            <span>We couldn&apos;t load your documents ({error}). Check your connection and try again.</span>
            <button type="button" className="small" onClick={() => void loadDocs()} style={{ minHeight: 44 }}>Try again</button>
          </div>
        )}

        {docs === null && !error && (
          <ul className="lib-grid" aria-busy="true" aria-label="Loading documents">
            {[0, 1, 2].map((i) => <li key={i} className="skeleton" style={{ height: 190 }} />)}
          </ul>
        )}

        {docs && docs.length === 0 && (
          <div className="glass hero-card empty">
            <span className="icon-well" aria-hidden style={{ margin: "0 auto .75rem" }}><Icon name="book" size={24} /></span>
            <h3>Start your library</h3>
            <p style={{ maxWidth: 420, margin: "0 auto .25rem" }}>
              Upload a textbook, notes or a case study. Answers will point to the exact page.
            </p>
            <button
              type="button"
              className="dark"
              style={{ minHeight: 44, marginTop: ".5rem" }}
              onClick={() => {
                const b = document.getElementById("lib-upload-btn");
                b?.scrollIntoView({ behavior: "smooth", block: "center" });
                b?.click();
              }}
            >
              Add your first PDF
            </button>
          </div>
        )}

        {docs && docs.length > 0 && (
          <ul className="lib-grid">
            {docs.map((d) => <DocCard key={d.id} doc={d} onChange={() => void loadDocs()} />)}
          </ul>
        )}
      </section>

      <section aria-labelledby="lib-quiz-h" className="stack-sm">
        <h2 id="lib-quiz-h" style={{ margin: "1rem 0 0" }}>Recent quizzes</h2>
        {quizErr && (
          <div className="notice bad row spread" role="alert">
            <span>We couldn&apos;t load your quizzes ({quizErr}).</span>
            <button type="button" className="small" onClick={() => void loadQuizzes()} style={{ minHeight: 44 }}>Try again</button>
          </div>
        )}
        {quizzes === null && !quizErr && (
          <div role="status" aria-busy="true" aria-label="Loading quizzes" className="stack-sm">
            <div className="skeleton" style={{ height: 64 }} />
            <div className="skeleton" style={{ height: 64 }} />
          </div>
        )}
        {quizzes && quizzes.length === 0 && (
          <div className="glass empty" style={{ padding: "1.25rem" }}>
            <p style={{ margin: 0 }}>
              No quizzes yet. Open a document and choose <strong style={{ fontWeight: 500 }}>Practise</strong> for a 5-question quiz, and we&apos;ll start showing what you know.
            </p>
          </div>
        )}
        {quizzes && quizzes.length > 0 && (
          <div>
            {quizzes.slice(0, 8).map((q) => {
              const done = q.answered >= q.question_count && q.question_count > 0;
              return (
                <Link key={q.id} href={`/quiz/${q.id}`} className="glass lib-quiz">
                  <span className="icon-well sm" aria-hidden><Icon name="target" size={20} /></span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: "block", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.title}</span>
                    <span className="muted small">
                      {q.answered} of {q.question_count} answered
                      {q.avg_score !== null && ` · ${Math.round(q.avg_score * 100)}% so far`}
                    </span>
                  </span>
                  <span className={`badge ${done ? "good" : ""}`}>{done ? "Finished" : q.answered ? "In progress" : "Not started"}</span>
                  <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
                </Link>
              );
            })}
          </div>
        )}
      </section>

      <ReportedQuestions />
    </div>
  );
}
