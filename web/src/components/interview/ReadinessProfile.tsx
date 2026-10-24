import type { ReadinessDim } from "@/lib/api-interview";
import Pill from "./Pill";
import { LEVEL, LEVEL_STEPS, READINESS } from "./labels";

/** One small glass card per readiness dimension. Deliberately no single overall percentage (PRD 7.5). */
export default function ReadinessProfile({ dims }: { dims: ReadinessDim[] }) {
  return (
    <section className="stack-sm" aria-labelledby="readiness-h">
      <div className="prep-section-h">
        <h2 id="readiness-h">How ready you are</h2>
        <span className="muted small">Practice readiness estimate, not a hiring prediction</span>
      </div>
      {dims.length === 0 ? (
        <div className="glass empty">
          <p style={{ margin: 0 }}>Not enough answers yet. Practise with a quiz or a mock interview to build this.</p>
        </div>
      ) : (
        <div className="prep-dims">
          {dims.map((d) => {
            const [name, question] = READINESS[d.dimension];
            const filled = LEVEL_STEPS[d.level];
            return (
              <div key={d.dimension} className="glass prep-dim">
                <span className="prep-name" style={{ fontSize: ".98rem" }}>{name}</span>
                <span className="muted tiny">{question}</span>
                <div className="steps4" aria-hidden="true">
                  {[0, 1, 2, 3].map((i) => <span key={i} className={i < filled ? "f" : undefined} />)}
                </div>
                <div className="row" style={{ gap: ".35rem" }}>
                  <Pill pair={LEVEL[d.level]} prefix={`${name}:`} />
                  <span className="muted tiny">{d.evidence_count} piece{d.evidence_count === 1 ? "" : "s"} of evidence</span>
                </div>
                {d.explanation && <p className="small" style={{ margin: 0 }}>{d.explanation}</p>}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
