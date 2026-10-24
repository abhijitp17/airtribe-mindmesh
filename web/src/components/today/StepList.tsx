"use client";

import Icon from "@/components/Icon";
import type { SessionStep } from "@/lib/api-engagement";
import { KIND_ICON, KIND_LABEL } from "./labels";

/** Compact list of session steps (title + minutes). Used on Today and in the session overview. */
export default function StepList({ steps, currentId }: { steps: SessionStep[]; currentId?: string | null }) {
  if (!steps.length) return null;
  return (
    <ol className="list" style={{ margin: 0 }}>
      {steps.map((s) => {
        const current = s.id === currentId;
        const status = s.status === "done" ? "Done" : s.status === "skipped" ? "Skipped" : current ? "Now" : null;
        return (
          <li key={s.id} aria-current={current ? "step" : undefined} style={{ padding: ".65rem 0" }}>
            <span className="row" style={{ gap: ".65rem", minWidth: 0, flexWrap: "nowrap" }}>
              <span className="icon-well sm" aria-hidden style={{ width: 36, height: 36 }}>
                <Icon name={s.status === "done" ? "check" : KIND_ICON[s.kind]} size={18} />
              </span>
              <span style={{ minWidth: 0 }}>
                <span className="sr-only">{KIND_LABEL[s.kind]}: </span>
                <span style={{ display: "block", textDecoration: s.status === "skipped" ? "line-through" : undefined, fontWeight: current ? 500 : 400 }}>
                  {s.title}
                </span>
              </span>
            </span>
            <span className="row" style={{ gap: ".4rem", flexShrink: 0 }}>
              {status && <span className={`badge ${s.status === "done" ? "ready" : current ? "dark" : ""}`}>{status}</span>}
              <span className="muted small">{s.minutes} min</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
