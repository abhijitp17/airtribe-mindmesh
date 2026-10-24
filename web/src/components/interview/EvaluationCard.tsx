import type { CriterionStatus, Evaluation, StarCheck } from "@/lib/api-interview";
import Pill from "./Pill";
import { CRITERION_MARK, VERDICT } from "./labels";

const STAR_LABEL: Record<keyof StarCheck, string> = {
  situation: "Situation",
  task: "Task",
  action: "Action",
  result: "Result",
  reflection: "Reflection",
};

const MARK_BG: Record<CriterionStatus, string> = {
  met: "var(--sage)",
  partial: "var(--sky)",
  missing: "var(--peach)",
};

function Sub({ children }: { children: React.ReactNode }) {
  return <h3 className="prep-sec-h" style={{ fontSize: ".95rem" }}>{children}</h3>;
}

export default function EvaluationCard({ ev }: { ev: Evaluation }) {
  const starKeys = Object.keys(STAR_LABEL) as (keyof StarCheck)[];
  return (
    <div className="stack" style={{ marginTop: ".25rem", padding: "1rem 1.05rem", borderRadius: "var(--r-md)", background: "rgba(255,255,255,0.7)", border: "1px solid var(--glass-edge)" }}>
      <div className="row">
        <Pill pair={VERDICT[ev.verdict]} prefix="Verdict:" />
        {ev.verdict !== "unassessed" && <span className="muted small">Covered {Math.round(ev.score * 100)}% of what a good answer covers</span>}
      </div>
      {ev.feedback && <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ev.feedback}</p>}

      {ev.criteria.length > 0 && (
        <div>
          <Sub>What a good answer covers</Sub>
          <ul className="criteria" style={{ marginTop: 0 }}>
            {ev.criteria.map((c, i) => {
              const [mark, text] = CRITERION_MARK[c.status];
              return (
                <li key={`${c.criterion}-${i}`} style={{ display: "flex", gap: ".6rem", alignItems: "flex-start", padding: ".4rem 0" }}>
                  <span
                    aria-hidden
                    style={{ flex: "none", width: 26, height: 26, borderRadius: 8, display: "inline-grid", placeItems: "center", background: MARK_BG[c.status], fontWeight: 600 }}
                  >
                    {mark}
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ fontWeight: 500 }}>{c.criterion}</span>{" "}
                    <span className="muted small">({text}, {c.points} pt)</span>
                    {c.evidence && <span className="muted small" style={{ display: "block" }}>From your answer: &ldquo;{c.evidence}&rdquo;</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {ev.star && (
        <div>
          <Sub>Story structure</Sub>
          <ul className="row" style={{ listStyle: "none", padding: 0, margin: 0, gap: ".4rem" }} aria-label="STAR checklist">
            {starKeys.map((k) => {
              const ok = ev.star ? ev.star[k] : false;
              return (
                <li key={k}>
                  <span className={`badge ${ok ? "ready" : ""}`} style={ok ? undefined : { opacity: 0.85 }}>
                    <span aria-hidden>{ok ? "✓" : "✗"}</span> {STAR_LABEL[k]}
                    <span className="sr-only">{ok ? " covered" : " not covered"}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {(ev.strengths.length > 0 || ev.improvements.length > 0) && (
        <div className="grid2" style={{ alignItems: "start" }}>
          {ev.strengths.length > 0 && (
            <div>
              <Sub>What worked</Sub>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {ev.strengths.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}
          {ev.improvements.length > 0 && (
            <div>
              <Sub>To improve</Sub>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {ev.improvements.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {ev.missing_details.length > 0 && (
        <div className="notice warn">
          <span style={{ fontWeight: 500 }}>Add these real details, don&apos;t make them up</span>
          <ul className="small" style={{ margin: ".25rem 0 0", paddingLeft: "1.1rem" }}>
            {ev.missing_details.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
