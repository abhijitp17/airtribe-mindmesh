"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { api } from "@/lib/api";

// The rights confirmation is remembered per browser so returning users aren't asked every time.
const RIGHTS_KEY = "mindmesh_rights_ack";

function readRightsAck(): boolean {
  try {
    return window.localStorage.getItem(RIGHTS_KEY) === "1";
  } catch {
    return false;
  }
}

function writeRightsAck(v: boolean) {
  try {
    if (v) window.localStorage.setItem(RIGHTS_KEY, "1");
    else window.localStorage.removeItem(RIGHTS_KEY);
  } catch {
    // Storage blocked (private mode etc.): fall back to asking each visit.
  }
}

// PDFs, Word, text, Markdown and HTML (the server checks the content, not just the name).
const EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm"];
const ACCEPT = EXTENSIONS.join(",") + ",application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/html";

function isSupported(f: File) {
  const name = f.name.toLowerCase();
  return EXTENSIONS.some((e) => name.endsWith(e));
}

/** Glass dropzone with the screen's one orange action, "Upload a file". */
export default function Uploader({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const rightsBox = useRef<HTMLInputElement>(null);
  const focusBox = useRef(false);
  const [over, setOver] = useState(false);
  const [rights, setRights] = useState(false);
  // When true, show the compact "You confirmed…" line instead of the checkbox.
  const [collapsed, setCollapsed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Read after mount (not during render) so server and client markup match.
  useEffect(() => {
    if (readRightsAck()) {
      setRights(true);
      setCollapsed(true);
    }
  }, []);

  useEffect(() => {
    if (!collapsed && focusBox.current) {
      focusBox.current = false;
      rightsBox.current?.focus();
    }
  }, [collapsed]);

  function setAck(v: boolean) {
    setRights(v);
    writeRightsAck(v);
    if (v) setErr(null);
  }

  function changeAck() {
    focusBox.current = true;
    setCollapsed(false);
  }

  function needRights(): boolean {
    if (rights) return false;
    setErr("Please tick the box to confirm you can use these files for personal study, then try again.");
    focusBox.current = true;
    setCollapsed(false);
    rightsBox.current?.focus();
    return true;
  }

  function openPicker() {
    if (busy || needRights()) return;
    input.current?.click();
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    if (needRights()) return;
    const list = Array.from(files);
    const pdfs = list.filter(isSupported);
    if (!pdfs.length) {
      setErr("That file type isn't supported. Choose a PDF, Word (.docx), text, Markdown or HTML file.");
      return;
    }
    setErr(null);
    try {
      // api.upload sends rights_confirmed=true; it is only reachable once the user has acknowledged.
      for (const [i, f] of pdfs.entries()) {
        setBusy(pdfs.length > 1 ? `Uploading ${i + 1} of ${pdfs.length}…` : `Uploading ${f.name}…`);
        await api.upload(f);
      }
      setCollapsed(true);
      if (pdfs.length < list.length) setErr("We skipped files that weren't PDFs.");
      onUploaded();
    } catch (e) {
      setErr(`Upload didn't finish: ${e instanceof Error ? e.message : "unknown error"}. Check your connection and try again.`);
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <section className="glass stack" style={{ padding: "1rem" }} aria-labelledby="lib-upload-h">
      <h2 id="lib-upload-h" className="sr-only">Upload a document</h2>
      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void upload(e.dataTransfer.files); }}
        style={{ display: "grid", justifyItems: "center", gap: ".6rem", cursor: "default" }}
      >
        <span className="icon-well" aria-hidden><Icon name="upload" size={24} /></span>
        <div>
          <div style={{ color: "var(--ink)", fontWeight: 500 }}>Add a document to your library</div>
          <div className="small">Drop it here, or choose a file. Textbooks, notes and case studies all work.</div>
        </div>
        <button id="lib-upload-btn" type="button" className="primary lg" onClick={openPicker} disabled={!!busy} style={{ minHeight: 48 }}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="upload" size={18} />}
          {busy ? "Uploading…" : "Upload a file"}
        </button>
        <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => void upload(e.target.files)} />
        <div aria-live="polite" className="small">{busy}</div>
      </div>
      {rights && collapsed ? (
        <p className="muted small" style={{ margin: 0 }}>
          <span aria-hidden>✓ </span>You confirmed you have the right to use your files for personal study.{" "}
          <button
            type="button"
            className="ghost small"
            style={{ padding: "0 .25rem", minHeight: 44, textDecoration: "underline" }}
            onClick={changeAck}
            aria-label="Change your upload rights confirmation"
          >
            Change
          </button>
        </p>
      ) : (
        <label className="row small" style={{ color: "var(--ink)", gap: ".55rem", margin: 0, alignItems: "flex-start", flexWrap: "nowrap", minHeight: 44 }}>
          <input
            ref={rightsBox}
            type="checkbox"
            checked={rights}
            onChange={(e) => setAck(e.target.checked)}
            style={{ width: 20, height: 20, marginTop: 2, flex: "none" }}
          />
          <span>
            I have the right to use these files for my personal study.{" "}
            <span className="muted">We&apos;ll remember this on this browser.</span>
          </span>
        </label>
      )}
      {err && <div className="notice bad" role="alert">{err}</div>}
    </section>
  );
}
