"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { graphApi } from "@/lib/api-graph";
import { journeyApi } from "@/lib/api-journey";
import { useAsk } from "./AskDock";
import Icon, { type IconName } from "./Icon";

/** ⌘K / Ctrl+K: jump to any screen, document, goal or concept, or ask your notes. Invisible to beginners
 *  (one "Search" button in the top bar), fast for pros. A native <dialog>: focus is trapped, Escape closes,
 *  and focus returns to whatever opened it. */
type Item = { id: string; label: string; hint: string; icon: IconName; run: () => void };

const PAGES: [string, string, IconName][] = [
  ["/", "Today", "today"], ["/map", "Knowledge map", "mesh"], ["/library", "Library", "library"], ["/prep", "Prep", "prep"],
  ["/progress", "Progress", "chart"], ["/goals/new", "New study goal", "plus"], ["/interview/new", "New interview prep", "plus"],
  ["/settings", "Settings", "settings"],
];

export default function CommandBar() {
  const router = useRouter();
  const ask = useAsk();
  const dlg = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [data, setData] = useState<{ docs: Item[]; goals: Item[]; concepts: Item[] } | null>(null);
  const listId = useId();

  const open = () => {
    setQ("");
    setActive(0);
    dlg.current?.showModal();
    if (!data) {
      Promise.all([api.documents().catch(() => []), journeyApi.get().catch(() => null), graphApi.map(400).catch(() => null)]).then(([docs, j, g]) => setData({
        docs: docs.filter((d) => d.status === "ready" || d.status === "needs_attention").map((d) => ({ id: `d${d.id}`, label: d.title || d.filename, hint: "Document", icon: "book" as IconName, run: () => router.push(`/documents/${d.id}`) })),
        goals: (j?.goals ?? []).map((b) => ({ id: `g${b.id}`, label: b.title, hint: b.kind === "interview" ? "Interview prep" : "Study goal", icon: "target" as IconName, run: () => router.push(b.href) })),
        concepts: (g?.nodes ?? []).map((n) => ({ id: `c${n.id}`, label: n.name, hint: "Concept", icon: "mesh" as IconName, run: () => router.push(`/map?c=${n.id}`) })),
      }));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!dlg.current?.open) open(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    const pages: Item[] = PAGES.map(([href, label, icon]) => ({ id: `p${href}`, label, hint: "Go to", icon, run: () => router.push(href) }));
    const all = [...pages, ...(data?.goals ?? []), ...(data?.docs ?? []), ...(data?.concepts ?? [])];
    const hits = t ? all.filter((i) => i.label.toLowerCase().includes(t)).slice(0, 8) : pages;
    return t.length >= 2 ? [{ id: "ask", label: `Ask your notes: “${q.trim()}”`, hint: "No AI unless you choose", icon: "sparkle" as IconName, run: () => ask(q.trim()) }, ...hits] : hits;
  }, [q, data, router, ask]);

  const choose = (i: Item | undefined) => { if (!i) return; dlg.current?.close(); i.run(); };

  return (
    <>
      <button type="button" className="cmd-btn" onClick={open} aria-haspopup="dialog" aria-keyshortcuts="Meta+K Control+K">
        <Icon name="search" size={16} /><span className="cmd-btn-label">Search or ask</span><kbd>⌘K</kbd>
      </button>
      <dialog ref={dlg} className="cmd" aria-label="Search or ask" onClick={(e) => { if (e.target === dlg.current) dlg.current?.close(); }}>
        <div className="cmd-in">
          <Icon name="search" size={18} />
          <input value={q} autoFocus placeholder="Search concepts, documents, goals, or ask a question" aria-label="Search or ask"
                 role="combobox" aria-expanded aria-controls={listId} aria-activedescendant={items[active] ? `${listId}-${items[active].id}` : undefined}
                 onChange={(e) => { setQ(e.target.value); setActive(0); }}
                 onKeyDown={(e) => {
                   if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
                   else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                   else if (e.key === "Enter") { e.preventDefault(); choose(items[active]); }
                 }} />
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className="cmd-list">
          {items.map((i, n) => (
            <li key={i.id} id={`${listId}-${i.id}`} role="option" aria-selected={n === active} onMouseEnter={() => setActive(n)} onClick={() => choose(i)}>
              <Icon name={i.icon} size={16} /><span className="cmd-label">{i.label}</span><span className="tiny muted">{i.hint}</span>
            </li>
          ))}
          {items.length === 0 && <li className="small muted" role="presentation" style={{ padding: ".75rem 1rem" }}>Nothing matches. Type a question to ask your notes.</li>}
        </ul>
        <p className="cmd-foot tiny muted">↑↓ to move · Enter to open · Esc to close</p>
      </dialog>
    </>
  );
}
