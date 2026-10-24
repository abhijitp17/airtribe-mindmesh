"use client";

import Link from "next/link";
import { useState } from "react";
import { pages } from "@/components/ui";
import { formatMinutes, type PlanItem, type PlanItemPatch } from "@/lib/api-goals";
import { ActivityBadge, ItemStatusBadge, isLeftOut } from "./ActivityBadge";
import { isQuizActivity } from "./session";
import { compactField } from "./styles";

type Props = {
  item: PlanItem;
  deadline: string;
  minDate: string;
  busy: boolean;
  onPatch: (item: PlanItem, body: PlanItemPatch) => Promise<void>;
  onDelete: (item: PlanItem) => Promise<void>;
  onStart: (item: PlanItem) => Promise<void>;
};

export default function PlanItemRow({ item, deadline, minDate, busy, onPatch, onDelete, onStart }: Props) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(item.scheduled_date);
  const [minutes, setMinutes] = useState(item.estimated_minutes);
  const leftOut = isLeftOut(item);
  const done = item.status === "done";

  async function save() {
    const body: PlanItemPatch = {};
    if (date !== item.scheduled_date) body.scheduled_date = date;
    if (minutes !== item.estimated_minutes) body.estimated_minutes = minutes;
    if (Object.keys(body).length) await onPatch(item, body);
    setEditing(false);
  }

  function startEdit() {
    setDate(item.scheduled_date);
    setMinutes(item.estimated_minutes);
    setEditing(true);
  }

  return (
    <li className={`prep-item ${done || item.status === "skipped" ? "dim" : ""}`}>
      <div style={{ minWidth: 0, flex: "1 1 240px" }}>
        <div className="row" style={{ gap: ".4rem" }}>
          <ActivityBadge activity={item.activity_type} />
          <ItemStatusBadge status={item.status} leftOut={leftOut} />
          {item.user_edited && <span className="badge" title="You changed this session; rebuilding your plan keeps it in place.">Edited by you</span>}
        </div>
        <div className="row" style={{ gap: ".5rem", marginTop: ".3rem" }}>
          <span style={{ fontWeight: 500, textDecoration: done ? "line-through" : undefined }}>{item.topic}</span>
          <span className="muted small">{formatMinutes(item.estimated_minutes)}</span>
        </div>
        {item.objective && <div className="small" style={{ marginTop: ".2rem" }}>{item.objective}</div>}
        {item.reason && <div className="muted small">{leftOut ? item.reason : `Why: ${item.reason}`}</div>}
        {item.sources.length > 0 && (
          <div className="small" style={{ marginTop: ".2rem" }}>
            <span className="muted">Sources: </span>
            {item.sources.map((s) => (
              <Link key={s.chunk_id} href={`/documents/${s.document_id}`} title={s.section || undefined} style={{ marginRight: ".5rem" }}>
                {pages(s.page_start, s.page_end)}{s.section ? ` · ${s.section.split(" > ").slice(-1)[0]}` : ""}
              </Link>
            ))}
          </div>
        )}
        {editing && (
          <div className="row small" style={{ marginTop: ".6rem", gap: ".5rem" }}>
            <label htmlFor={`d-${item.id}`} style={{ margin: 0 }}>Date</label>
            <input id={`d-${item.id}`} type="date" value={date} min={minDate} max={deadline}
                   onChange={(e) => setDate(e.target.value)} style={compactField} />
            <label htmlFor={`m-${item.id}`} style={{ margin: 0 }}>Minutes</label>
            <input id={`m-${item.id}`} type="number" min={5} max={480} step={5} value={minutes}
                   onChange={(e) => setMinutes(Number(e.target.value))} style={{ ...compactField, width: 80 }} />
            <button className="dark small" onClick={save} disabled={busy || !date || minutes < 5 || minutes > 480}>Save</button>
            <button className="ghost small" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
          </div>
        )}
      </div>
      <div className="row" style={{ gap: ".3rem", flex: "0 1 auto", justifyContent: "flex-end" }}>
        {item.status === "pending" && isQuizActivity(item) && (
          <button className="dark small" onClick={() => onStart(item)} disabled={busy} aria-label={`Start ${item.topic} quiz`}>Start</button>
        )}
        {item.status === "pending" && (
          <>
            <button className="small" onClick={() => onPatch(item, { status: "done" })} disabled={busy} aria-label={`Mark ${item.topic} done`}>Done</button>
            <button className="ghost small" onClick={() => onPatch(item, { status: "skipped" })} disabled={busy} aria-label={`Skip ${item.topic}`}>Skip</button>
          </>
        )}
        {item.status !== "pending" && (
          <button className={leftOut ? "small" : "ghost small"} onClick={() => onPatch(item, { status: "pending" })} disabled={busy}
                  aria-label={leftOut ? `Add ${item.topic} back to the plan` : `Mark ${item.topic} as to do`}>
            {leftOut ? "Add back" : "Undo"}
          </button>
        )}
        {!editing && (
          <button className="ghost small" onClick={startEdit} disabled={busy} aria-label={`Edit date or minutes for ${item.topic}`}>Edit</button>
        )}
        <button className="ghost small danger" onClick={() => onDelete(item)} disabled={busy} aria-label={`Delete ${item.topic}`}>Delete</button>
      </div>
    </li>
  );
}
