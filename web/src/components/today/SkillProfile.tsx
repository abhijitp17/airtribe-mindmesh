"use client";

import { useEffect, useState } from "react";
import { LEVEL } from "@/components/interview/labels";
import { request } from "@/lib/api";
import type { AssessedLevel } from "@/lib/api-interview";

type Skill = { slug: string; name: string; category: string; level: AssessedLevel; concepts: string[]; job_skills: string[]; roles: string[] };

/** Your skills on the shared taxonomy (P3): concepts from your material and job skills, grouped. Hidden when empty. */
export default function SkillProfile() {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  useEffect(() => {
    request<Skill[]>("/me/skill-profile").then(setSkills).catch(() => setSkills([]));
  }, []);
  if (!skills || skills.length === 0) return null;
  return (
    <section className="glass card stack-sm" aria-labelledby="skills-h">
      <h2 id="skills-h" style={{ fontSize: "1.2rem", margin: 0 }}>Your skills</h2>
      <p className="muted small" style={{ margin: 0 }}>Your concepts and job skills, grouped by a common skill list. Ratings come from your answers.</p>
      <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {skills.map((s) => {
          const [label, cls] = LEVEL[s.level];
          const from = [...s.concepts, ...s.job_skills.filter((j) => !s.concepts.includes(j))];
          return (
            <li key={s.slug} className="row spread" style={{ gap: ".5rem", alignItems: "flex-start", borderTop: "1px solid var(--line)", paddingTop: ".5rem" }}>
              <div style={{ minWidth: 0, flex: "1 1 220px" }}>
                <strong style={{ fontWeight: 500 }}>{s.name}</strong>
                {from.length > 0 && <div className="muted small">From: {from.slice(0, 4).join(", ")}{from.length > 4 ? ` +${from.length - 4}` : ""}</div>}
                {s.roles.length > 0 && <div className="small">Needed for: {s.roles.join(", ")}</div>}
              </div>
              <span className={`badge ${cls}`}>{label}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
