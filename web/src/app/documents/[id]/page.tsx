"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useId, useMemo, useState } from "react";
import Icon from "@/components/Icon";
import Shell, { BackLink } from "@/components/Shell";
import SourceViewer, { type Focus } from "@/components/SourceViewer";
import Tutor from "@/components/Tutor";
import ProcessingWait from "@/components/library/ProcessingWait";
import LibStyles from "@/components/library/styles";
import { DocStatusBadge } from "@/components/ui";
import { api, type Doc } from "@/lib/api";

export default function DocumentPage() {
  return (
    <Shell wide>
      <LibStyles />
      <style>{`
@media (max-width: 960px) { .lib-desk-only { display: none !important; } }
`}</style>
      <Suspense fallback={null}>
        <Workspace />
      </Suspense>
    </Shell>
  );
}

type View = "read" | "ask" | "practise";
const VIEWS: { id: View; label: string }[] = [
  { id: "read", label: "Read" },
  { id: "ask", label: "Ask" },
  { id: "practise", label: "Practise" },
];

const isNarrow = () => typeof window !== "undefined" && window.matchMedia("(max-width: 960px)").matches;

function Workspace() {
  const { id } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [view, setView] = useState<View>("ask");
  const [early, setEarly] = useState(false);  // using the first pages while the rest is read
  const startPage = Number(useSearchParams().get("page")) || null;  // ?page=N: open the reader there (study links)

  useEffect(() => {
    if (!startPage) return;
    setFocus({ page: startPage, nonce: Date.now() });
    setView("read");
  }, [startPage]);
  const documentIds = useMemo(() => [id], [id]);
  const panelId = useId();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.document(id)
      .then((d) => { if (!cancelled) setDoc(d); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : "unknown error"); });
    return () => { cancelled = true; };
  }, [id, reload]);

  // Keep polling while the document is still being read, so the workspace opens as soon as it's ready.
  const busy = doc?.status === "uploaded" || doc?.status === "processing";
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => setReload((n) => n + 1), 2500);
    return () => clearInterval(t);
  }, [busy]);

  const onCite = useCallback((f: Omit<Focus, "nonce">) => {
    setFocus({ ...f, nonce: Date.now() });
    // On phones only one pane is visible, so jump to the reader to show the cited page.
    if (isNarrow()) setView("read");
  }, []);

  if (error) {
    return (
      <div className="stack narrow">
        <BackLink href="/library">Library</BackLink>
        <div className="notice bad row spread" role="alert">
          <span>We couldn&apos;t open this document ({error}). It may have been deleted, or the connection dropped.</span>
          <button type="button" className="small" onClick={() => setReload((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
        </div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div role="status" className="stack" aria-busy="true" aria-label="Loading document">
        <div className="skeleton" style={{ height: 20, width: 120 }} />
        <div className="workspace">
          <div className="skeleton" style={{ minHeight: 360 }} />
          <div className="skeleton" style={{ minHeight: 360 }} />
        </div>
      </div>
    );
  }

  if (busy && !(early && doc.pages_done)) {
    return (
      <div className="stack narrow">
        <BackLink href="/library">Library</BackLink>
        <ProcessingWait doc={doc} onStartEarly={() => setEarly(true)} />
      </div>
    );
  }

  if (doc.status === "failed") {
    return (
      <div className="stack narrow">
        <BackLink href="/library">Library</BackLink>
        <div className="glass hero-card stack-sm tint-gap" role="status">
          <div className="row spread">
            <span className="icon-well" aria-hidden><Icon name="book" size={24} /></span>
            <DocStatusBadge status={doc.status} />
          </div>
          <h1 style={{ fontSize: "1.5rem" }}>{doc.title || doc.filename}</h1>
          <p>{doc.status_detail || "We couldn't open this file. It may be damaged or password-protected."}</p>
          <div className="row">
            <button type="button" onClick={() => api.retryDocument(doc.id).then(() => setReload((n) => n + 1)).catch((e: unknown) => setError(e instanceof Error ? e.message : "unknown error"))} style={{ minHeight: 44 }}>
              Retry
            </button>
            <Link href="/library" className="btn" style={{ minHeight: 44 }}>Back to Library</Link>
          </div>
        </div>
      </div>
    );
  }

  const toolsView: "ask" | "practise" = view === "practise" ? "practise" : "ask";

  return (
    <div className="stack">
      <BackLink href="/library">Library</BackLink>
      {busy && (
        <div className="notice info small" role="status">
          Still reading the rest: {doc.pages_done} of {doc.page_count} pages so far. Answers and questions use the pages read so far.
        </div>
      )}

      <div className="segmented glass lib-ws-switch" role="tablist" aria-label="Workspace">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={view === v.id}
            aria-controls={panelId}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div className="workspace lib-ws" id={panelId}>
        <SourceViewer doc={doc} focus={focus} className={view === "read" ? "" : "lib-pane-hidden"} />
        <section className={`pane ${view === "read" ? "lib-pane-hidden" : ""}`} aria-label={toolsView === "ask" ? "Ask the tutor" : "Practise"}>
          <div className="pane-head lib-desk-only">
            <div className="tabs" role="tablist" aria-label="Learning tools">
              <button role="tab" type="button" aria-selected={toolsView === "ask"} onClick={() => setView("ask")} style={{ minHeight: 40 }}>Ask</button>
              <button role="tab" type="button" aria-selected={toolsView === "practise"} onClick={() => setView("practise")} style={{ minHeight: 40 }}>Practise</button>
            </div>
            <DocStatusBadge status={doc.status} />
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: "rgba(255,255,255,0.4)" }}>
            {toolsView === "ask" ? (
              <Tutor documentIds={documentIds} onCite={onCite} />
            ) : (
              <QuizLauncher documentIds={documentIds} />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function QuizLauncher({ documentIds }: { documentIds: string[] }) {
  const router = useRouter();
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState("medium");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [suggested, setSuggested] = useState<string[]>([]);
  const ids = { focus: useId(), count: useId(), diff: useId(), sugg: useId() };

  useEffect(() => {
    if (documentIds.length !== 1) return;
    api.concepts(documentIds[0]).then((cs) => setSuggested(cs.slice(0, 8).map((c) => c.name))).catch(() => setSuggested([]));
  }, [documentIds]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const q = await api.createQuiz(documentIds, count, difficulty, focus.trim() || undefined);
      router.push(`/quiz/${q.id}`);
    } catch (e) {
      setErr(`We couldn't make the quiz: ${e instanceof Error ? e.message : "unknown error"}. Try again in a moment.`);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={create} className="stack" style={{ padding: "1.1rem", overflow: "auto" }}>
      <div className="row" style={{ gap: ".75rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
        <span className="icon-well" aria-hidden><Icon name="target" size={24} /></span>
        <div>
          <h2 style={{ fontSize: "1.2rem" }}>Test your understanding</h2>
          <p className="muted small" style={{ margin: 0 }}>
            A mix of quick recall, explain-it-in-your-own-words and apply-it questions. Each one links to the pages it comes from.
          </p>
        </div>
      </div>
      <div>
        <label htmlFor={ids.focus}>Focus topic (optional)</label>
        <input id={ids.focus} type="text" placeholder="For example, Little's Law or working capital" value={focus} onChange={(e) => setFocus(e.target.value)} />
        {suggested.length > 0 && (
          <div className="row" role="group" aria-labelledby={ids.sugg} style={{ gap: ".4rem", marginTop: ".5rem" }}>
            <span id={ids.sugg} className="small muted">Topics in this document:</span>
            {suggested.map((name) => (
              <button key={name} type="button" className="ghost small" aria-pressed={focus === name}
                      onClick={() => setFocus(focus === name ? "" : name)} style={{ minHeight: 44 }}>
                {name}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 8rem" }}>
          <label htmlFor={ids.count}>Questions</label>
          <select id={ids.count} value={count} onChange={(e) => setCount(Number(e.target.value))} style={{ minHeight: 44 }}>
            {[3, 5, 8, 10].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div style={{ flex: "1 1 8rem" }}>
          <label htmlFor={ids.diff}>Difficulty</label>
          <select id={ids.diff} value={difficulty} onChange={(e) => setDifficulty(e.target.value)} style={{ minHeight: 44 }}>
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
        </div>
      </div>
      {err && <div className="notice bad" role="alert">{err}</div>}
      <button className="primary lg block" type="submit" disabled={busy} aria-live="polite">
        {busy && <span className="spinner" aria-hidden />} {busy ? "Writing your questions…" : "Make a quiz"}
      </button>
    </form>
  );
}
