"use client";

import { useId, useState } from "react";
import type {
  Competency,
  CompetencyCat,
  Importance,
  JobParsed,
  ResumeBullet,
  ResumeParsed,
  ResumeRole,
} from "@/lib/api-interview";
import { CATEGORY, IMPORTANCE } from "./labels";

/** Client-side id for rows the user adds. The backend keeps or replaces it. */
export function newId(prefix: string): string {
  const rnd =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}-${rnd}`;
}

const box: React.CSSProperties = { border: "1px solid var(--glass-edge)", borderRadius: "var(--r-md)", padding: ".85rem .95rem", background: "rgba(255,255,255,0.6)" };

/** Comma-separated list input that keeps the raw text while typing. */
function ListInput({ id, value, onChange, placeholder }: { id: string; value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [raw, setRaw] = useState(value.join(", "));
  return (
    <input
      id={id}
      type="text"
      value={raw}
      placeholder={placeholder}
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean));
      }}
    />
  );
}

// ---------------- Resume ----------------

export function ResumeEditor({ value, onChange }: { value: ResumeParsed; onChange: (v: ResumeParsed) => void }) {
  const fid = useId();
  const set = <K extends keyof ResumeParsed>(k: K, v: ResumeParsed[K]) => onChange({ ...value, [k]: v });
  const setRole = (i: number, r: ResumeRole) => set("roles", value.roles.map((x, j) => (j === i ? r : x)));

  return (
    <div className="stack">
      <div className="grid2">
        <div>
          <label htmlFor={`${fid}-name`}>Name</label>
          <input id={`${fid}-name`} type="text" value={value.name ?? ""} onChange={(e) => set("name", e.target.value || null)} />
        </div>
        <div>
          <label htmlFor={`${fid}-skills`}>Skills (comma-separated)</label>
          <ListInput id={`${fid}-skills`} value={value.skills} onChange={(v) => set("skills", v)} />
        </div>
      </div>
      <div>
        <label htmlFor={`${fid}-sum`}>Summary</label>
        <textarea id={`${fid}-sum`} rows={2} style={{ minHeight: 60 }} value={value.summary ?? ""} onChange={(e) => set("summary", e.target.value || null)} />
      </div>

      <h3 style={{ marginTop: "1rem" }}>Roles</h3>
      {value.roles.length === 0 && <p className="muted small">No roles found. Add the roles you want considered.</p>}
      {value.roles.map((r, i) => (
        <RoleEditor
          key={r.id}
          role={r}
          onChange={(nr) => setRole(i, nr)}
          onRemove={() => set("roles", value.roles.filter((_, j) => j !== i))}
        />
      ))}
      <button
        type="button"
        className="small"
        onClick={() => set("roles", [...value.roles, { id: newId("role"), title: "", company: "", start: null, end: null, bullets: [] }])}
      >
        + Add role
      </button>

      <div className="grid2" style={{ marginTop: "1rem" }}>
        <div>
          <h3>Education</h3>
          {value.education.map((ed, i) => (
            <div key={ed.id} className="row" style={{ gap: ".35rem", flexWrap: "nowrap", marginBottom: ".35rem" }}>
              <label htmlFor={`${fid}-ed-${ed.id}`} className="sr-only">Education {i + 1}</label>
              <input
                id={`${fid}-ed-${ed.id}`}
                type="text"
                value={ed.text}
                onChange={(e) => set("education", value.education.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
              />
              <button type="button" className="ghost small danger" aria-label={`Remove education ${i + 1}`} onClick={() => set("education", value.education.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" className="small" onClick={() => set("education", [...value.education, { id: newId("edu"), text: "" }])}>+ Add education</button>
        </div>
        <div>
          <h3>Certifications</h3>
          <label htmlFor={`${fid}-cert`}>Comma-separated</label>
          <ListInput id={`${fid}-cert`} value={value.certifications} onChange={(v) => set("certifications", v)} />
        </div>
      </div>
    </div>
  );
}

function RoleEditor({ role, onChange, onRemove }: { role: ResumeRole; onChange: (r: ResumeRole) => void; onRemove: () => void }) {
  const fid = useId();
  const set = <K extends keyof ResumeRole>(k: K, v: ResumeRole[K]) => onChange({ ...role, [k]: v });
  const setBullet = (i: number, b: ResumeBullet) => set("bullets", role.bullets.map((x, j) => (j === i ? b : x)));
  const label = role.title || "Untitled role";

  return (
    <fieldset style={{ ...box, margin: 0 }}>
      <legend className="small" style={{ padding: "0 .3rem", fontWeight: 500 }}>{label}{role.company ? ` · ${role.company}` : ""}</legend>
      <div className="grid2">
        <div>
          <label htmlFor={`${fid}-t`}>Title</label>
          <input id={`${fid}-t`} type="text" value={role.title} onChange={(e) => set("title", e.target.value)} />
        </div>
        <div>
          <label htmlFor={`${fid}-c`}>Company</label>
          <input id={`${fid}-c`} type="text" value={role.company} onChange={(e) => set("company", e.target.value)} />
        </div>
        <div>
          <label htmlFor={`${fid}-s`}>Start</label>
          <input id={`${fid}-s`} type="text" value={role.start ?? ""} placeholder="e.g. 2021-03" onChange={(e) => set("start", e.target.value || null)} />
        </div>
        <div>
          <label htmlFor={`${fid}-e`}>End</label>
          <input id={`${fid}-e`} type="text" value={role.end ?? ""} placeholder="e.g. Present" onChange={(e) => set("end", e.target.value || null)} />
        </div>
      </div>
      <div style={{ marginTop: ".6rem" }}>
        <span className="muted small">Bullets (kept word for word; edit only to correct parsing mistakes)</span>
        {role.bullets.map((b, i) => (
          <div key={b.id} className="row" style={{ gap: ".35rem", flexWrap: "nowrap", alignItems: "flex-start", marginTop: ".35rem" }}>
            <label htmlFor={`${fid}-b-${b.id}`} className="sr-only">Bullet {i + 1} for {label}</label>
            <textarea
              id={`${fid}-b-${b.id}`}
              rows={2}
              style={{ minHeight: 48 }}
              value={b.text}
              onChange={(e) => setBullet(i, { ...b, text: e.target.value })}
            />
            <button type="button" className="ghost small danger" aria-label={`Remove bullet ${i + 1} from ${label}`} onClick={() => set("bullets", role.bullets.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: ".5rem" }}>
        <button type="button" className="small" onClick={() => set("bullets", [...role.bullets, { id: newId("b"), text: "" }])}>+ Add bullet</button>
        <button type="button" className="ghost small danger" onClick={onRemove} aria-label={`Remove role ${label}`}>Remove role</button>
      </div>
    </fieldset>
  );
}

// ---------------- Job description ----------------

const IMPORTANCES: Importance[] = ["critical", "high", "medium", "low"];
const CATEGORIES: CompetencyCat[] = ["technical", "domain", "tool", "behavioral", "leadership", "communication"];

export function JobEditor({ value, onChange }: { value: JobParsed; onChange: (v: JobParsed) => void }) {
  const fid = useId();
  const set = <K extends keyof JobParsed>(k: K, v: JobParsed[K]) => onChange({ ...value, [k]: v });
  const setComp = (i: number, c: Competency) => set("competencies", value.competencies.map((x, j) => (j === i ? c : x)));

  return (
    <div className="stack">
      <div className="grid2">
        <div>
          <label htmlFor={`${fid}-rt`}>Role title</label>
          <input id={`${fid}-rt`} type="text" value={value.role_title} onChange={(e) => set("role_title", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={`${fid}-co`}>Company</label>
          <input id={`${fid}-co`} type="text" value={value.company ?? ""} onChange={(e) => set("company", e.target.value || null)} />
        </div>
        <div>
          <label htmlFor={`${fid}-se`}>Seniority</label>
          <input id={`${fid}-se`} type="text" value={value.seniority ?? ""} onChange={(e) => set("seniority", e.target.value || null)} />
        </div>
      </div>

      <h3 style={{ marginTop: "1rem" }}>Competencies</h3>
      <p className="muted small" style={{ margin: 0 }}>Set how much each one matters for this role. Remove anything that was misread.</p>
      {value.competencies.length === 0 && <p className="muted small">No competencies found. Add the skills the role asks for.</p>}
      {value.competencies.map((c, i) => (
        <fieldset key={c.id} style={{ ...box, margin: 0 }}>
          <legend className="sr-only">Competency {i + 1}: {c.name || "unnamed"}</legend>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: "2 1 200px" }}>
              <label htmlFor={`${fid}-n-${c.id}`}>Name</label>
              <input id={`${fid}-n-${c.id}`} type="text" value={c.name} onChange={(e) => setComp(i, { ...c, name: e.target.value })} />
            </div>
            <div style={{ flex: "1 1 130px" }}>
              <label htmlFor={`${fid}-c-${c.id}`}>Category</label>
              <select id={`${fid}-c-${c.id}`} value={c.category} onChange={(e) => setComp(i, { ...c, category: e.target.value as CompetencyCat })}>
                {CATEGORIES.map((k) => <option key={k} value={k}>{CATEGORY[k]}</option>)}
              </select>
            </div>
            <div style={{ flex: "1 1 120px" }}>
              <label htmlFor={`${fid}-i-${c.id}`}>Importance</label>
              <select id={`${fid}-i-${c.id}`} value={c.importance} onChange={(e) => setComp(i, { ...c, importance: e.target.value as Importance })}>
                {IMPORTANCES.map((k) => <option key={k} value={k}>{IMPORTANCE[k][0]}</option>)}
              </select>
            </div>
            <label className="row small" style={{ color: "var(--ink)", gap: ".35rem", margin: 0, paddingBottom: ".55rem" }}>
              <input type="checkbox" checked={c.required} onChange={(e) => setComp(i, { ...c, required: e.target.checked })} />
              Required
            </label>
            <button
              type="button"
              className="ghost small danger"
              style={{ marginBottom: ".3rem" }}
              aria-label={`Remove competency ${c.name || i + 1}`}
              onClick={() => set("competencies", value.competencies.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
          {c.evidence_quote ? (
            <div className="muted small" style={{ marginTop: ".35rem" }}>From the JD: <mark>{c.evidence_quote}</mark></div>
          ) : (
            <div className="muted small" style={{ marginTop: ".35rem" }}>Added by you</div>
          )}
        </fieldset>
      ))}
      <button
        type="button"
        className="small"
        onClick={() =>
          set("competencies", [
            ...value.competencies,
            { id: newId("comp"), name: "", category: "technical", importance: "medium", required: false, evidence_quote: "" },
          ])
        }
      >
        + Add competency
      </button>

      {value.responsibilities.length > 0 && (
        <details>
          <summary className="small">Responsibilities found ({value.responsibilities.length})</summary>
          <ul className="small" style={{ margin: ".3rem 0 0", paddingLeft: "1.1rem" }}>
            {value.responsibilities.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
