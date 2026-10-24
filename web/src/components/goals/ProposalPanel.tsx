"use client";

import { formatDay, formatMinutes, type PlanItem, type PlanProposal, type ProposalChange } from "@/lib/api-goals";

const OP_LABEL: Record<ProposalChange["op"], [string, string]> = {
  add: ["Add", "ready"],
  move: ["Move", "info"],
  remove: ["Remove", "warn"],
  resize: ["Change length", ""],
};

function describe(c: ProposalChange, items: Map<string, PlanItem>): string {
  const item = c.item_id ? items.get(c.item_id) : undefined;
  const topic = c.topic ?? item?.topic ?? "a session";
  const mins = c.minutes !== undefined ? ` (${formatMinutes(c.minutes)})` : "";
  switch (c.op) {
    case "add":
      return `${c.activity_type ?? "session"} on ${topic}${c.to_date ? ` on ${formatDay(c.to_date)}` : ""}${mins}`;
    case "move":
      return `${topic}${item ? ` from ${formatDay(item.scheduled_date)}` : ""}${c.to_date ? ` to ${formatDay(c.to_date)}` : ""}${mins}`;
    case "remove":
      return topic;
    case "resize":
      return `${topic}${mins}`;
  }
}

type Props = {
  proposal: PlanProposal;
  items: PlanItem[];
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
};

/** A suggested plan change. Accept is the screen's one orange action while a proposal is showing. */
export default function ProposalPanel({ proposal, items, busy, onAccept, onReject }: Props) {
  const byId = new Map(items.map((i) => [i.id, i]));
  return (
    <section className="glass card tint-unknown stack" aria-labelledby="proposal-h">
      <div>
        <span className="badge info">Suggested update</span>
        <h2 id="proposal-h" style={{ margin: ".5rem 0 .15rem" }}>We&apos;d change your plan</h2>
        <p className="small" style={{ margin: 0 }}>{proposal.reason}</p>
      </div>
      <ul className="prep-items">
        {proposal.changes.map((c, i) => {
          const [label, cls] = OP_LABEL[c.op];
          return (
            <li key={`${c.op}-${c.item_id ?? "new"}-${i}`} className="prep-item" style={{ display: "block" }}>
              <div className="row" style={{ gap: ".4rem" }}>
                <span className={`badge ${cls}`}>{label}</span>
                <span style={{ fontWeight: 500 }}>{describe(c, byId)}</span>
              </div>
              <div className="muted small" style={{ marginTop: ".2rem" }}>Why: {c.why}</div>
            </li>
          );
        })}
      </ul>
      <div className="row">
        <button className="primary lg" onClick={onAccept} disabled={busy}>{busy && <span className="spinner" />} Accept changes</button>
        <button className="lg" onClick={onReject} disabled={busy}>Reject, keep my plan</button>
      </div>
    </section>
  );
}
