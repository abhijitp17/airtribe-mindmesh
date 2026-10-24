"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { DocStatusBadge, formatBytes } from "@/components/ui";
import { api, type Doc } from "@/lib/api";

export const isOpenable = (d: Doc) => d.status === "ready" || d.status === "needs_attention";
export const isBusy = (d: Doc) => d.status === "uploaded" || d.status === "processing";

/** A glass document card. Ready docs are a real link ending in an arrow tile; delete sits in a small overflow. */
export default function DocCard({ doc, onChange }: { doc: Doc; onChange: () => void }) {
  const name = doc.title || doc.filename;
  const openable = isOpenable(doc);
  const linkable = openable || isBusy(doc);  // a document being read opens on its progress page
  const [menu, setMenu] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const menuId = useId();
  const moreBtn = useRef<HTMLButtonElement>(null);
  const firstAction = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (menu) firstAction.current?.focus();
  }, [menu, confirming]);

  function close() {
    setMenu(false);
    setConfirming(false);
    moreBtn.current?.focus();
  }

  async function remove() {
    setBusy(true);
    setErr(null);
    try {
      await api.deleteDocument(doc.id);
      onChange();
    } catch (e) {
      setErr(`Couldn't delete: ${e instanceof Error ? e.message : "unknown error"}. Try again.`);
      setBusy(false);
    }
  }

  async function retry() {
    setBusy(true);
    setErr(null);
    try {
      await api.retryDocument(doc.id);
      onChange();
    } catch (e) {
      setErr(`Retry didn't start: ${e instanceof Error ? e.message : "unknown error"}.`);
    } finally {
      setBusy(false);
    }
  }

  const meta = [doc.page_count ? `${doc.page_count} page${doc.page_count === 1 ? "" : "s"}` : null, formatBytes(doc.size_bytes)]
    .filter(Boolean)
    .join(" · ");

  const body = (
    <>
      <div className="tile-top">
        <span className="icon-well sm" aria-hidden><Icon name="book" size={20} /></span>
        {openable && <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>}
      </div>
      <strong className="lib-title">{name}</strong>
      <span className="muted small">{meta}</span>
    </>
  );

  return (
    <li className={`glass lib-card ${doc.status === "failed" ? "tint-gap" : ""}`}>
      {linkable ? (
        <Link href={`/documents/${doc.id}`} className="tile-link" aria-label={`Open ${name}`}>{body}</Link>
      ) : (
        <div className="tile-link">{body}</div>
      )}

      {doc.status_detail && (doc.status === "needs_attention" || doc.status === "failed") && (
        <p className="small" style={{ margin: "0 1rem .5rem" }}>{doc.status_detail}</p>
      )}
      {isBusy(doc) && (
        <p className="small muted" style={{ margin: "0 1rem .5rem" }}>
          {doc.pages_done && doc.page_count
            ? `Read ${doc.pages_done} of ${doc.page_count} pages. You can start on the first pages now.`
            : "Reading your pages. Open it to follow along."}
        </p>
      )}

      <div className="lib-foot">
        <DocStatusBadge status={doc.status} />
        <div className="row" style={{ gap: ".35rem" }}>
          {doc.status === "failed" && (
            <button type="button" className="small" onClick={retry} disabled={busy} style={{ minHeight: 44 }}>
              {busy && <span className="spinner" aria-hidden />} Retry
            </button>
          )}
          <button
            ref={moreBtn}
            type="button"
            className="ghost icon-btn lib-more"
            aria-label={`More actions for ${name}`}
            aria-expanded={menu}
            aria-controls={menuId}
            onClick={() => (menu ? close() : setMenu(true))}
          >
            <span aria-hidden style={{ fontSize: "1.25rem", lineHeight: 1 }}>⋯</span>
          </button>
        </div>
      </div>

      {menu && (
        <div
          id={menuId}
          className="lib-menu"
          onKeyDown={(e) => { if (e.key === "Escape") close(); }}
        >
          {confirming ? (
            <div className="stack-sm">
              <p className="small" style={{ margin: 0 }}>
                Delete &ldquo;{name}&rdquo;? This removes the file, its text and the page links in its quizzes. You can&apos;t undo this.
              </p>
              <div className="row" style={{ gap: ".4rem" }}>
                <button type="button" className="danger small" onClick={remove} disabled={busy} style={{ minHeight: 44 }}>
                  {busy && <span className="spinner" aria-hidden />} Yes, delete
                </button>
                <button ref={firstAction} type="button" className="small" onClick={close} style={{ minHeight: 44 }}>Keep it</button>
              </div>
            </div>
          ) : (
            <button ref={firstAction} type="button" className="ghost danger small block" style={{ justifyContent: "flex-start", minHeight: 44 }} onClick={() => setConfirming(true)}>
              Delete document
            </button>
          )}
        </div>
      )}
      {err && <div className="notice bad small" role="alert" style={{ margin: "0 1rem 1rem" }}>{err}</div>}
    </li>
  );
}
