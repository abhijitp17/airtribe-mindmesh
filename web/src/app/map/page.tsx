"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import Icon from "@/components/Icon";
import { useAsk } from "@/components/AskDock";
import Shell from "@/components/Shell";
import { errorText, plural } from "@/components/today/labels";
import { graphApi, type KnowledgeMap, type Level, type MapNode } from "@/lib/api-graph";
import { layout } from "@/lib/graph-layout";

const W = 1000, H = 640, LABELS = 36;
// Colour is never the only signal: the legend, the detail panel and the list all say the level in words.
const LEVEL: Record<Level, { fill: string; label: string }> = {
  strong: { fill: "#1C6C5B", label: "Strong" },
  developing: { fill: "#6B9A7C", label: "Developing" },
  weak: { fill: "#E78363", label: "Needs work" },
  unverified: { fill: "#C9D7B5", label: "Not practised yet" },
};
const BADGE: Record<Level, string> = { strong: "good", developing: "info", weak: "gap", unverified: "" };

const MAP_CSS = `
  .map-grid { display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr); }
  @media (min-width: 1000px) { .map-grid { grid-template-columns: minmax(0, 1fr) 330px; align-items: start; } }
  .map-frame { position: relative; padding: 0; overflow: hidden; background: #F8F6EE; }
  .map-scroll { overflow-x: auto; }
  .map-frame svg { display: block; width: 100%; min-width: 760px; height: auto; }
  .map-node { cursor: pointer; }
  .map-node:focus-visible circle.map-dot { stroke: var(--green); stroke-width: 3; }
  .map-label { font: 500 11px var(--font); fill: var(--ink-2); pointer-events: none; paint-order: stroke; stroke: #F8F6EE; stroke-width: 3px; }
  .map-label.on { fill: var(--ink); font-weight: 600; }
  .map-legend { display: flex; flex-wrap: wrap; gap: .4rem 1rem; padding: .7rem 1rem; border-top: 1px solid var(--line); font-size: .8rem; color: var(--ink-2); background: var(--solid); }
  .map-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: .35rem; vertical-align: -1px; }
  .map-legend .dash { width: 18px; height: 0; border-radius: 0; border-top: 2px dashed #A9B9A8; }
  .map-quote { margin: .35rem 0 0; padding-left: .7rem; border-left: 2px solid var(--gold); color: var(--ink-2); font-size: .88rem; }
  .map-list { columns: 2 240px; column-gap: 1.5rem; list-style: none; padding: 0; margin: 0; }
  .map-list li { break-inside: avoid; padding: .3rem 0; }
  .map-list button { background: none; border: 0; padding: .2rem 0; font-weight: 500; text-align: left; min-height: 32px; }
    border-radius: var(--r-lg); box-shadow: 0 20px 50px rgba(40,55,50,.18); overflow: hidden; }
`;

export default function MapPage() {
  return (
    <Shell wide>
      <style>{MAP_CSS}</style>
      <KnowledgeMapView />
    </Shell>
  );
}

function KnowledgeMapView() {
  const [data, setData] = useState<KnowledgeMap | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [view, setView] = useState<"map" | "list">("map");
  const ask = useAsk();
  const fid = useId();

  useEffect(() => {
    graphApi.map().then((m) => {
      setData(m);
      const c = new URLSearchParams(window.location.search).get("c");  // from ⌘K: open on that concept
      if (c && m.nodes.some((n) => n.id === c)) setSelected(c);
    }).catch((e) => setErr(errorText(e, "Couldn't load your map. Try again.")));
  }, []);

  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const docTitle = useMemo(() => new Map((data?.documents ?? []).map((d) => [d.id, d.title])), [data]);
  const pos = useMemo(() => {
    if (!data?.nodes.length) return new Map<string, { x: number; y: number }>();
    const groups = new Map(data.nodes.filter((n) => n.sources[0]).map((n) => [n.id, n.sources[0].document_id]));
    return layout(data.nodes.map((n) => n.id), data.edges.map((e) => [e.source, e.target]), groups, W, H);
  }, [data]);

  if (err) return <div className="notice bad" role="alert">{err}</div>;
  if (!data) return <div className="muted" role="status"><span className="spinner" aria-hidden /> Drawing your map…</div>;

  const q = filter.trim().toLowerCase();
  const matches = (n: MapNode) => !q || n.name.toLowerCase().includes(q) || (n.skill ?? "").toLowerCase().includes(q);
  const sel = selected ? byId.get(selected) ?? null : null;
  const near = new Set<string>();
  const focus = hover ?? selected;
  if (focus) for (const e of data.edges) { if (e.source === focus) near.add(e.target); if (e.target === focus) near.add(e.source); }
  const labelled = new Set(data.nodes.slice(0, LABELS).map((n) => n.id));
  const radius = (n: MapNode) => 6 + Math.min(10, Math.sqrt(n.degree * 2 + n.source_count) * 2.2);

  return (
    <div className="stack">
      <header className="page-head">
        <div>
          <p className="eyebrow">Your knowledge</p>
          <h1 className="display">Your knowledge map</h1>
          <p>
            {data.total_concepts === 0 ? "Concepts from your library appear here, linked by what builds on what."
              : `${plural(data.total_concepts, "concept")} from ${plural(data.documents.length, "document")}, ${plural(data.edges.length, "link")}.`}
            {data.nodes.length < data.total_concepts && ` Showing the ${data.nodes.length} best connected.`}
          </p>
        </div>
        {data.nodes.length > 0 && (
          <div className="segmented" role="tablist" aria-label="View">
            <button role="tab" aria-selected={view === "map"} onClick={() => setView("map")}>Map</button>
            <button role="tab" aria-selected={view === "list"} onClick={() => setView("list")}>List</button>
          </div>
        )}
      </header>

      {data.nodes.length === 0 ? (
        <div className="card empty">
          <span className="icon-well" aria-hidden style={{ margin: "0 auto 1rem" }}><Icon name="mesh" size={26} /></span>
          <h3>Your map starts with your first document</h3>
          <p>Add a PDF, Word file or notes. Mindmesh finds the concepts in it and how they connect, each traced to its page.</p>
          <Link href="/library" className="btn primary">Add to your library</Link>
        </div>
      ) : (
        <div className="map-grid">
          <div className="stack-sm">
            <div className="row">
              <label htmlFor={fid} className="sr-only">Find a concept</label>
              <input id={fid} type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a concept or skill" style={{ maxWidth: 340 }} />
              {q && <span className="small muted" role="status">{plural(data.nodes.filter(matches).length, "match", "matches")}</span>}
            </div>
            {view === "map" ? (
              <figure className="card map-frame" style={{ margin: 0 }}>
                <div className="map-scroll" tabIndex={-1}>
                <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Knowledge map. Each concept is a button; the List view shows the same concepts as text.">
                  <defs>
                    <marker id="map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                      <path d="M0 0 10 5 0 10z" fill="#9DB09C" />
                    </marker>
                  </defs>
                  <g aria-hidden>
                    {data.edges.map((e) => {
                      const a = pos.get(e.source), b = pos.get(e.target), tn = byId.get(e.target);
                      if (!a || !b || !tn) return null;
                      const on = focus && (e.source === focus || e.target === focus);
                      const len = Math.hypot(b.x - a.x, b.y - a.y) || 1, r = radius(tn) + 3;
                      return <line key={`${e.source}-${e.target}`} x1={a.x} y1={a.y} x2={b.x - ((b.x - a.x) / len) * r} y2={b.y - ((b.y - a.y) / len) * r}
                        stroke={on ? "#1C6C5B" : "#B8C9B7"} strokeWidth={on ? 2 : 1.3} strokeDasharray={e.verified ? undefined : "5 4"}
                        opacity={focus && !on ? 0.35 : 1} markerEnd="url(#map-arrow)" />;
                    })}
                  </g>
                  {data.nodes.map((n) => {
                    const p = pos.get(n.id);
                    if (!p) return null;
                    const dim = (q && !matches(n)) || (focus && focus !== n.id && !near.has(n.id));
                    const show = labelled.has(n.id) || n.id === focus || near.has(n.id) || (q && matches(n));
                    return (
                      <g key={n.id} className="map-node" role="button" tabIndex={0} opacity={dim ? 0.3 : 1}
                         aria-label={`${n.name}: ${LEVEL[n.level].label}${n.source_count ? `, in ${plural(n.source_count, "source")}` : ""}`}
                         aria-pressed={selected === n.id}
                         onClick={() => setSelected(n.id === selected ? null : n.id)}
                         onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setSelected(n.id === selected ? null : n.id); } }}
                         onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}>
                        {selected === n.id && <circle cx={p.x} cy={p.y} r={radius(n) + 7} fill="none" stroke="#E78363" strokeWidth={2} />}
                        <circle className="map-dot" cx={p.x} cy={p.y} r={radius(n)} fill={LEVEL[n.level].fill}
                                stroke={n.level === "unverified" ? "#93A893" : "#FFFDF7"} strokeWidth={1.5} />
                        {show && <text className={`map-label ${n.id === focus ? "on" : ""}`} x={p.x} y={p.y - radius(n) - 6} textAnchor="middle">{n.name}</text>}
                      </g>
                    );
                  })}
                </svg>
                </div>
                <figcaption className="map-legend">
                  {(Object.keys(LEVEL) as Level[]).map((l) => <span key={l}><i style={{ background: LEVEL[l].fill }} />{LEVEL[l].label}</span>)}
                  <span><i className="dash" />Link not yet confirmed by a quote</span>
                  <span>Arrows point from a concept to what builds on it</span>
                </figcaption>
              </figure>
            ) : (
              <div className="card">
                {(["weak", "developing", "unverified", "strong"] as Level[]).map((l) => {
                  const items = data.nodes.filter((n) => n.level === l && matches(n)).sort((a, b) => a.name.localeCompare(b.name));
                  if (!items.length) return null;
                  return (
                    <section key={l} className="stack-sm" style={{ marginBottom: "1rem" }}>
                      <h2 className="small" style={{ fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: ".1em" }}>{LEVEL[l].label} · {items.length}</h2>
                      <ul className="map-list">
                        {items.map((n) => <li key={n.id}><button aria-pressed={selected === n.id} onClick={() => setSelected(n.id)}>{n.name}</button></li>)}
                      </ul>
                    </section>
                  );
                })}
              </div>
            )}
          </div>

          <aside className="card stack-sm" aria-live="polite" aria-label="Concept details">
            {sel ? (
              <Detail node={sel} map={data} byId={byId} docTitle={docTitle} onPick={setSelected} onAsk={ask} />
            ) : (
              <>
                <p className="eyebrow">How to read it</p>
                <p className="small" style={{ margin: 0 }}>Each dot is a concept from your library. Bigger dots are better connected. Pick one to see where it comes from, what it builds on, and how well you know it.</p>
                {data.nodes.some((n) => n.level === "weak") && (
                  <p className="notice bad small" style={{ margin: 0 }}>
                    {plural(data.nodes.filter((n) => n.level === "weak").length, "concept")} need work. They&apos;re the coral dots.
                  </p>
                )}
              </>
            )}
          </aside>
        </div>
      )}

    </div>
  );
}

function Detail({ node, map, byId, docTitle, onPick, onAsk }: {
  node: MapNode; map: KnowledgeMap; byId: Map<string, MapNode>; docTitle: Map<string, string>;
  onPick: (id: string) => void; onAsk: (q: string) => void;
}) {
  const buildsOn = map.edges.filter((e) => e.target === node.id).map((e) => byId.get(e.source)).filter((n): n is MapNode => !!n);
  const leadsTo = map.edges.filter((e) => e.source === node.id).map((e) => byId.get(e.target)).filter((n): n is MapNode => !!n);
  const chips = (list: MapNode[]) => (
    <span className="row" style={{ gap: ".35rem" }}>{list.map((n) => <button key={n.id} className="badge" onClick={() => onPick(n.id)}>{n.name}</button>)}</span>
  );
  return (
    <>
      <p className="eyebrow">Concept</p>
      <h2 className="display" style={{ margin: 0 }}>{node.name}</h2>
      <span className="row" style={{ gap: ".4rem" }}>
        <span className={`badge ${BADGE[node.level]}`}>{LEVEL[node.level].label}</span>
        {node.due_for_review && <span className="badge warn">Due for review</span>}
        {node.skill && <span className="badge accent">Skill: {node.skill}</span>}
      </span>
      <p className="small muted" style={{ margin: 0 }}>
        {node.evidence ? `Based on ${plural(node.evidence, "answer")} in your practice.` : "You haven't practised this yet."}
      </p>
      {buildsOn.length > 0 && <div className="small"><b>Builds on</b><br />{chips(buildsOn)}</div>}
      {leadsTo.length > 0 && <div className="small"><b>Leads to</b><br />{chips(leadsTo)}</div>}
      <div className="small">
        <b>Where it comes from</b>
        {node.sources.length === 0 ? <p className="muted" style={{ margin: 0 }}>From a study plan rather than a document.</p> : (
          <ul style={{ margin: ".25rem 0 0", paddingLeft: "1.1rem" }}>
            {node.sources.map((s, i) => (
              <li key={`${s.document_id}-${i}`}>
                <Link href={`/documents/${s.document_id}${s.page ? `?page=${s.page}` : ""}`}>{docTitle.get(s.document_id) ?? "Document"}{s.page ? `, p. ${s.page}` : ""}</Link>
                {s.quote && <q className="map-quote" style={{ display: "block" }}>{s.quote}</q>}
              </li>
            ))}
          </ul>
        )}
        {node.source_count > node.sources.length && <p className="muted tiny" style={{ margin: ".25rem 0 0" }}>and {node.source_count - node.sources.length} more</p>}
      </div>
      <div className="row" style={{ gap: ".5rem" }}>
        <button className="primary" onClick={() => onAsk(`What is ${node.name}?`)}><Icon name="search" size={16} /> Ask my notes</button>
        {buildsOn.length > 0 && <button onClick={() => onAsk(`What does ${node.name} build on?`)}>What does it build on?</button>}
      </div>
    </>
  );
}
