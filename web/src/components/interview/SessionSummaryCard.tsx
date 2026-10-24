import type { SessionSummary } from "@/lib/api-interview";

export default function SessionSummaryCard({ summary }: { summary: SessionSummary }) {
  return (
    <section className="glass hero-card stack" aria-labelledby="summary-h">
      <div>
        <span className="prep-kicker">Interview finished</span>
        <h2 id="summary-h" style={{ margin: ".15rem 0 0" }}>How it went</h2>
      </div>
      {summary.overall && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{summary.overall}</p>}
      <p className="muted small" style={{ margin: 0 }}>Practice readiness estimate, not a hiring prediction.</p>

      {summary.by_competency.length > 0 && (
        <div>
          <h3 className="prep-sec-h">By skill</h3>
          {summary.by_competency.map((c) => {
            const pct = Math.round(Math.max(0, Math.min(1, c.score)) * 100);
            return (
              <div key={c.competency_id} className="concept-row">
                <span style={{ fontWeight: 500 }}>{c.name}</span>
                <div className="meter" role="img" aria-label={`${c.name}: ${pct}% of what a good answer covers`}>
                  <div style={{ width: `${pct}%` }} />
                </div>
                <span className="muted small">{pct}% · {c.attempts} answer{c.attempts === 1 ? "" : "s"}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid2" style={{ alignItems: "start" }}>
        <div className="glass" style={{ padding: "1rem" }}>
          <h3 className="prep-sec-h">Work on these first</h3>
          {summary.top_improvements.length ? (
            <ol className="small" style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {summary.top_improvements.map((t, i) => <li key={i}>{t}</li>)}
            </ol>
          ) : <p className="muted small" style={{ margin: 0 }}>Nothing specific. Nice work.</p>}
        </div>
        <div className="glass" style={{ padding: "1rem" }}>
          <h3 className="prep-sec-h">Practice next</h3>
          {summary.suggested_drills.length ? (
            <ul className="small" style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {summary.suggested_drills.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          ) : <p className="muted small" style={{ margin: 0 }}>No drills suggested.</p>}
        </div>
      </div>
    </section>
  );
}
