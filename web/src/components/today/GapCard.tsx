"use client";

import Icon from "@/components/Icon";
import type { PublicSkill } from "@/lib/api-engagement";

type State = "gap" | "unknown" | "ready";

/** Map the interview gap type to one of three plain states. */
export function skillState(s: PublicSkill): State {
  if (s.gap_type === "strong") return "ready";
  if (s.gap_type === "unverified" || s.gap_type === "evidence_gap" || s.gap_type === "stretch") return "unknown";
  return "gap";
}

const STATE_LABEL: Record<State, string> = {
  gap: "Gap",
  unknown: "Not shown yet",
  ready: "Your resume proves this",
};

const IMPORTANCE_LABEL: Record<PublicSkill["importance"], string> = {
  critical: "Critical for this role",
  high: "High importance",
  medium: "Medium importance",
  low: "Nice to have",
};

/** One skill from the public gap report: state tint + text label, JD quote, resume quote in a <mark>. */
export default function GapCard({ skill }: { skill: PublicSkill }) {
  const state = skillState(skill);
  const critical = state === "gap" && skill.importance === "critical";
  return (
    <article className={`glass card tint-${state} stack-sm`} aria-label={`${skill.name}: ${STATE_LABEL[state]}`}>
      <div className="row spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
        <h3 style={{ margin: 0, minWidth: 0 }}>{skill.name}</h3>
        <span className={`badge ${state === "gap" ? "gap" : state === "ready" ? "ready" : "info"}`}>
          {critical ? "Critical gap" : STATE_LABEL[state]}
        </span>
      </div>
      <p className="muted small" style={{ margin: 0 }}>{IMPORTANCE_LABEL[skill.importance]}. {skill.why}</p>
      <figure style={{ margin: 0 }}>
        <figcaption className="tiny muted" style={{ marginBottom: ".15rem" }}>The job asks for</figcaption>
        <blockquote style={{ margin: 0, fontSize: ".92rem" }}>&ldquo;{skill.jd_quote}&rdquo;</blockquote>
      </figure>
      {skill.evidence_quote ? (
        <figure style={{ margin: 0 }}>
          <figcaption className="tiny muted" style={{ marginBottom: ".15rem" }}>Your resume says</figcaption>
          <blockquote style={{ margin: 0, fontSize: ".92rem" }}><mark>{skill.evidence_quote}</mark></blockquote>
        </figure>
      ) : (
        <p className="small" style={{ margin: 0 }}>Not on your resume yet.</p>
      )}
      {skill.next_step && (
        <p className="small row" style={{ margin: 0, gap: ".4rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
          <span aria-hidden style={{ marginTop: 2 }}><Icon name="flag" size={16} /></span>
          <span><span className="sr-only">Next step: </span>{skill.next_step}</span>
        </p>
      )}
    </article>
  );
}
