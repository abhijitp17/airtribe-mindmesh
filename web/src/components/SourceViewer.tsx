"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, type ChunkT, type Doc } from "@/lib/api";
import { pages } from "./ui";

export type Focus = { page: number; chunkId?: string; quote?: string; nonce: number };

/** Reader pane: extracted text with page anchors, plus the original PDF. */
export default function SourceViewer({ doc, focus, className = "" }: { doc: Doc; focus: Focus | null; className?: string }) {
  const [tab, setTab] = useState<"text" | "pdf">("text");
  const isPdf = doc.filename.toLowerCase().endsWith(".pdf");  // other formats are downloaded, not embedded
  const [chunks, setChunks] = useState<ChunkT[] | null>(null);
  const [chunkErr, setChunkErr] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfErr, setPdfErr] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setChunkErr(null);
    api.chunks(doc.id)
      .then((c) => { if (!cancelled) setChunks(c); })
      .catch((e: unknown) => { if (!cancelled) setChunkErr(e instanceof Error ? e.message : "unknown error"); });
    return () => { cancelled = true; };
  }, [doc.id, attempt]);

  // Fetch the PDF lazily the first time the tab opens.
  useEffect(() => {
    if (tab !== "pdf" || pdfUrl) return;
    let cancelled = false;
    setPdfErr(false);
    api.fileBlob(doc.id)
      .then((b) => { if (!cancelled) setPdfUrl(URL.createObjectURL(b)); })
      .catch(() => { if (!cancelled) setPdfErr(true); });
    return () => { cancelled = true; };
  }, [tab, doc.id, pdfUrl, attempt]);

  // Revoke the object URL only when it is replaced or the viewer unmounts.
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  // Scroll to the cited sentence (or, if the quote can't be matched, the cited passage) on each click.
  useEffect(() => {
    if (!focus || tab !== "text") return;
    const sel = focus.chunkId ? `[data-chunk="${focus.chunkId}"]` : `[data-page="${focus.page}"]`;
    const el = body.current?.querySelector(`${sel} mark`) ?? body.current?.querySelector(sel);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: el.tagName === "MARK" ? "center" : "start" });
  }, [focus, tab, chunks]);

  const lowPages = doc.low_text_pages;

  return (
    <section className={`pane ${className}`} aria-label="Source document">
      <div className="pane-head">
        <strong style={{ fontWeight: 500, minWidth: 0, flex: "1 1 10rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={doc.title || doc.filename}>
          {doc.title || doc.filename}
        </strong>
        <div className="tabs" role="tablist" aria-label="Reader view">
          <button role="tab" type="button" aria-selected={tab === "text"} onClick={() => setTab("text")} style={{ minHeight: 40 }}>Text</button>
          <button role="tab" type="button" aria-selected={tab === "pdf"} onClick={() => setTab("pdf")} style={{ minHeight: 40 }}>{isPdf ? "Original PDF" : "Original file"}</button>
        </div>
      </div>
      {lowPages.length > 0 && (
        <div className="notice warn small" style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)" }}>
          We couldn&apos;t read {lowPages.length === 1 ? "1 page" : `${lowPages.length} pages`}
          {lowPages.length <= 8 && ` (${lowPages.map((p) => `p. ${p}`).join(", ")})`}. They look scanned or image-only, so answers can&apos;t use them yet.
        </div>
      )}
      <p className="sr-only" aria-live="polite">{focus ? `Showing the source on page ${focus.page}.` : ""}</p>
      {tab === "text" ? (
        <div className="pane-body" ref={body} tabIndex={0} aria-label="Document text">
          {chunks === null && !chunkErr && (
            <div role="status" className="stack-sm" aria-busy="true" aria-label="Loading text">
              <div className="skeleton" style={{ height: 14, width: "40%" }} />
              <div className="skeleton" style={{ height: 90 }} />
              <div className="skeleton" style={{ height: 90 }} />
            </div>
          )}
          {chunkErr && (
            <div className="notice bad row spread" role="alert">
              <span>We couldn&apos;t load the text ({chunkErr}).</span>
              <button type="button" className="small" onClick={() => setAttempt((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
            </div>
          )}
          {chunks?.length === 0 && (
            <div className="empty">
              <h3>No readable text yet</h3>
              <p className="small">This file may be scanned. Open the Original PDF tab to read it.</p>
              <button type="button" onClick={() => setTab("pdf")} style={{ minHeight: 44 }}>Open the original PDF</button>
            </div>
          )}
          {chunks && chunks.length > 0 && <ChunkList chunks={chunks} focus={focus} />}
        </div>
      ) : (
        <div className="pane-body" style={{ padding: 0 }}>
          {pdfUrl && !isPdf ? (
            <div className="stack-sm" style={{ padding: "1rem" }}>
              <p className="small" style={{ margin: 0 }}>This is a {doc.filename.split(".").pop()?.toUpperCase()} file. The Text tab shows its content with the same page numbers your citations use.</p>
              <a className="btn" href={pdfUrl} download={doc.filename} style={{ alignSelf: "flex-start", minHeight: 44 }}>Download {doc.filename}</a>
            </div>
          ) : pdfUrl ? (
            <iframe
              key={focus?.nonce}
              title="Original PDF"
              src={`${pdfUrl}#page=${focus?.page ?? 1}`}
              style={{ width: "100%", height: "100%", border: 0, minHeight: 500 }}
            />
          ) : pdfErr ? (
            <div className="notice bad row spread" role="alert" style={{ margin: "1rem" }}>
              <span>We couldn&apos;t load the PDF. Check your connection and try again.</span>
              <button type="button" className="small" onClick={() => setAttempt((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
            </div>
          ) : (
            <div role="status" className="skeleton" style={{ margin: "1rem", height: 420 }} aria-busy="true" aria-label="Loading PDF" />
          )}
        </div>
      )}
    </section>
  );
}

function ChunkList({ chunks, focus }: { chunks: ChunkT[]; focus: Focus | null }) {
  let lastSection = "";
  const seenPages = new Set<number>();
  return (
    <>
      {chunks.map((c) => {
        const showSection = c.section && c.section !== lastSection;
        lastSection = c.section;
        const firstOnPage = !seenPages.has(c.page_start);
        seenPages.add(c.page_start);
        const active = focus?.chunkId === c.id;
        return (
          <div key={c.id} data-chunk={c.id} data-page={firstOnPage ? c.page_start : undefined} style={{ scrollMarginTop: 8 }}>
            {showSection && <SectionPath section={c.section} variant="heading" />}
            <div className="tiny muted" style={{ margin: ".6rem 0 .2rem", display: "flex", alignItems: "center", gap: ".5rem" }}>
              <span className="badge" style={{ fontWeight: 500, fontSize: ".74rem" }}>{pages(c.page_start, c.page_end)}</span>
              {active && <span>Cited passage</span>}
            </div>
            <div
              className="page-text"
              style={active ? { background: "rgba(255,255,255,0.9)", boxShadow: "inset 3px 0 0 var(--peach)", borderRadius: 10, padding: ".5rem .7rem" } : undefined}
            >
              <Highlighted text={c.text} quote={active ? focus?.quote : undefined} flashKey={active ? focus?.nonce : undefined} />
            </div>
          </div>
        );
      })}
    </>
  );
}

/** Split a stored section label ("Chapter 7 > 7.3 Little's Law") into parent path and deepest title. */
export function splitSection(section: string): { title: string; parents: string[] } {
  const parts = section.split(">").map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return { title: "", parents: [] };
  return { title: parts[parts.length - 1], parents: parts.slice(0, -1) };
}

const ELLIPSIS: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 };

/**
 * Show only the deepest section title, with the parent path as a small muted breadcrumb
 * (truncated with an ellipsis). The full path is always available in the title attribute.
 * - "heading": reader section heading
 * - "inline": compact one-line form for citation lists and quiz source links
 */
export function SectionPath({ section, variant = "inline" }: { section: string; variant?: "heading" | "inline" }) {
  const { title, parents } = splitSection(section);
  if (!title) return null;
  const full = [...parents, title].join(" › ");
  const crumb = parents.join(" › ");
  if (variant === "heading") {
    return (
      <div title={full} style={{ margin: "1.4rem 0 .2rem", paddingTop: ".9rem", borderTop: "1px solid var(--line)" }}>
        {crumb && <div className="muted" style={{ ...ELLIPSIS, fontSize: ".76rem" }}>{crumb}</div>}
        <h3 style={{ ...ELLIPSIS, margin: ".1rem 0 0", fontSize: "1.05rem", fontWeight: 500 }}>{title}</h3>
      </div>
    );
  }
  return (
    <span title={full} style={{ display: "inline-flex", alignItems: "baseline", gap: ".3rem", maxWidth: "100%", minWidth: 0, verticalAlign: "bottom" }}>
      {crumb && <span className="muted" style={{ ...ELLIPSIS, fontSize: ".75rem", maxWidth: "12rem" }}>{crumb} ›</span>}
      <span style={ELLIPSIS}>{title}</span>
    </span>
  );
}

/** Highlight the cited quote inside the chunk. Matches on words only, so whitespace, punctuation,
 * curly vs straight quotes and hyphenation differences between the model's quote and the PDF text
 * don't stop the highlight. If nothing matches, the passage itself stays outlined as "Cited passage". */
export function findQuote(text: string, quote?: string): [string, string, string] | null {
  if (!quote) return null;
  const words = quote.normalize("NFKC").split(/[^\p{L}\p{M}\p{N}]+/u).filter(Boolean);
  if (words.length === 0 || (words.length === 1 && words[0].length < 4)) return null;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[^\\p{L}\\p{M}\\p{N}]+");
  const m = new RegExp(`(?<![\\p{L}\\p{M}\\p{N}])${pattern}(?![\\p{L}\\p{M}\\p{N}])`, "iu").exec(text);  // the original text: normalising it could shift indices (e.g. the "ﬁ" ligature)
  return m ? [text.slice(0, m.index), text.slice(m.index, m.index + m[0].length), text.slice(m.index + m[0].length)] : null;
}

function Highlighted({ text, quote, flashKey }: { text: string; quote?: string; flashKey?: number }) {
  const parts = useMemo(() => findQuote(text, quote), [text, quote]);
  if (!parts) return <>{text}</>;
  return <>{parts[0]}<mark key={flashKey} className="cite-flash">{parts[1]}</mark>{parts[2]}</>;
}
