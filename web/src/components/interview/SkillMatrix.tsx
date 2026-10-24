"use client";

import Link from "next/link";
import { useId, useMemo, useState } from "react";
import Icon from "@/components/Icon";
import { pages } from "@/components/ui";
import { interviewApi, type GapType, type Priority, type PriorityFactors, type SkillMatch, type StudyLink } from "@/lib/api-interview";
import Pill from "./Pill";
import {
  CATEGORY,
  CONFIDENCE,
  FACTOR_LABEL,
  GAP,
  IMPORTANCE,
  IMPORTANCE_RANK,
  LEVEL,
  PRIORITY,
  PRIORITY_RANK,
  PRIORITY_SHORT,
  STRENGTH,
  errMsg,
  skillStatus,
  skillTint,
} from "./labels";

const PRIORITIES: Priority[] = ["critical", "high", "medium", "low"];
const GAP_TYPES: GapType[] = ["knowledge_gap", "application_gap", "evidence_gap", "communication_gap", "unverified", "stretch", "strong"];

/** Priority shown to the user: their override wins over the computed value. */
export function effectivePriority(s: SkillMatch): Priority {
  return s.user_override?.priority ?? s.priority;
}

const IMPORTANCE_LINE: Record<SkillMatch["jd_importance"], string> = {
  critical: "Critical for this role.",
  high: "High importance for this role.",
  medium: "Medium importance for this role.",
  low: "Low importance for this role.",
};

/**
 * The gap report: a grid of skill cards (2 columns on desktop, 1 on phones), tinted by state and always labelled.
 * Each card leads with status, skill, why it matters and the next step; opening it reveals the detail
 * (UX research: "the skill table is dense").
 */
export default function SkillMatrix({
  prepId,
  skills,
  onSkillUpdated,
  studyLinks = {},
}: {
  prepId: string;
  skills: SkillMatch[];
  onSkillUpdated: (s: SkillMatch) => void;
  studyLinks?: Record<string, StudyLink[]>;
}) {
  const [prio, setPrio] = useState<Priority | "all">("all");
  const [gap, setGap] = useState<GapType | "all">("all");
  const [sort, setSort] = useState<"priority" | "importance">("priority");
  const [openId, setOpenId] = useState<string | null>(null);
  const fid = useId();

  const shown = useMemo(() => {
    const list = skills.filter((s) => (prio === "all" || effectivePriority(s) === prio) && (gap === "all" || s.gap_type === gap));
    return [...list].sort((a, b) => {
      const pa = PRIORITY_RANK[effectivePriority(a)] - PRIORITY_RANK[effectivePriority(b)];
      const ia = IMPORTANCE_RANK[a.jd_importance] - IMPORTANCE_RANK[b.jd_importance];
      return sort === "priority" ? pa || ia : ia || pa;
    });
  }, [skills, prio, gap, sort]);

  return (
    <section className="stack" aria-labelledby="matrix-h">
      <div className="prep-section-h">
        <h2 id="matrix-h">What to work on</h2>
        <span className="muted small" aria-live="polite">Showing {shown.length} of {skills.length} skill{skills.length === 1 ? "" : "s"}</span>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        What the job asks for, what your resume proves, and what your practice shows. A keyword in your skills list is never treated as proof. Open a skill to see why.
      </p>

      <div className="stack-sm" role="group" aria-label="Filter and sort skills">
        <div>
          <span className="small muted" id={`${fid}-pl`} style={{ display: "block", marginBottom: ".3rem" }}>Priority</span>
          <div className="prep-chips" role="group" aria-labelledby={`${fid}-pl`}>
            {(["all", ...PRIORITIES] as const).map((p) => (
              <button key={p} type="button" aria-pressed={prio === p} onClick={() => setPrio(p)}>
                {p === "all" ? "All" : PRIORITY_SHORT[p]}
              </button>
            ))}
          </div>
        </div>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 180px" }}>
            <label htmlFor={`${fid}-g`}>Kind of gap</label>
            <select id={`${fid}-g`} value={gap} onChange={(e) => setGap(e.target.value as GapType | "all")}>
              <option value="all">All kinds</option>
              {GAP_TYPES.map((g) => <option key={g} value={g}>{GAP[g][0]}</option>)}
            </select>
          </div>
          <div style={{ flex: "1 1 160px" }}>
            <label htmlFor={`${fid}-s`}>Sort by</label>
            <select id={`${fid}-s`} value={sort} onChange={(e) => setSort(e.target.value as "priority" | "importance")}>
              <option value="priority">What to do first</option>
              <option value="importance">How much it matters</option>
            </select>
          </div>
        </div>
      </div>

      {skills.length === 0 ? (
        <div className="glass empty">
          <h3>No skills found in the job description</h3>
          <p style={{ margin: 0 }}>Edit the job description, then press Update.</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="glass empty">
          <p style={{ marginBottom: ".75rem" }}>No skills match these filters.</p>
          <button type="button" onClick={() => { setPrio("all"); setGap("all"); }}>Show all skills</button>
        </div>
      ) : (
        <ul className="prep-grid" aria-label="Skills">
          {shown.map((s) => (
            <SkillCard
              key={s.id}
              prepId={prepId}
              s={s}
              links={studyLinks[s.id] ?? []}
              open={openId === s.id}
              onToggle={() => setOpenId((cur) => (cur === s.id ? null : s.id))}
              onUpdated={onSkillUpdated}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SkillCard({
  prepId,
  s,
  links,
  open,
  onToggle,
  onUpdated,
}: {
  prepId: string;
  s: SkillMatch;
  links: StudyLink[];
  open: boolean;
  onToggle: () => void;
  onUpdated: (s: SkillMatch) => void;
}) {
  const rid = useId();
  const eff = effectivePriority(s);
  const status = skillStatus(s.gap_type, eff);
  const [, , gapWhy] = GAP[s.gap_type];
  const quote = s.resume_evidence[0]?.text;

  return (
    <li className={`prep-skill ${skillTint(s.gap_type)} ${open ? "open" : ""}`}>
      <button
        type="button"
        className="prep-skill-btn"
        aria-expanded={open}
        aria-controls={`${rid}-panel`}
        onClick={onToggle}
      >
        <span className="row" style={{ gap: ".35rem" }}>
          <Pill pair={status} prefix="Status:" />
          {s.user_override?.priority && s.user_override.priority !== s.priority && <span className="badge">Priority set by you</span>}
        </span>
        <span className="prep-name">{s.name}</span>
        <span className="prep-why">{gapWhy}</span>
        {quote ? (
          <span className="prep-quote"><span className="sr-only">From your resume: </span><mark>&ldquo;{quote}&rdquo;</mark></span>
        ) : null}
        <span className="muted tiny">{IMPORTANCE_LINE[s.jd_importance]}</span>
        <span className="prep-next">
          <span>{s.recommended_action || (open ? "Hide details" : "See details")}</span>
          <span className="arrow-tile prep-arrow" aria-hidden="true"><Icon name="arrow" size={18} /></span>
        </span>
        <span className="sr-only">{open ? "Hide details" : "Show details"}</span>
      </button>

      {open && (
        <div id={`${rid}-panel`} className="prep-panel stack" role="region" aria-label={`Details for ${s.name}`}>
          <div className="row" style={{ gap: ".35rem" }}>
            <Pill pair={IMPORTANCE[s.jd_importance]} prefix="How much it matters:" />
            <Pill pair={PRIORITY[eff]} />
            <span className="badge">{CATEGORY[s.category]}</span>
            <span className="badge">{GAP[s.gap_type][0]}</span>
          </div>

          <div className="grid2" style={{ alignItems: "start" }}>
            <div className="stack-sm">
              <h3 className="prep-sec-h">On your resume</h3>
              <Pill pair={STRENGTH[s.resume_strength]} />
              {s.resume_evidence.length > 0 ? (
                <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {s.resume_evidence.map((ev) => (
                    <li key={ev.bullet_id} style={{ marginBottom: ".3rem" }}>
                      <q>{ev.text}</q>
                      {ev.role_title && <span className="muted"> · {ev.role_title}</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small" style={{ margin: 0 }}>No resume bullet shows this yet.</p>
              )}
            </div>
            <div className="stack-sm">
              <h3 className="prep-sec-h">What you know</h3>
              <div className="row" style={{ gap: ".35rem" }}>
                <Pill pair={LEVEL[s.assessed_level]} prefix="What you know:" />
                <span className="muted small">{CONFIDENCE[s.confidence]}</span>
              </div>
              {s.assessed_explanation && <p className="small" style={{ margin: 0 }}>{s.assessed_explanation}</p>}
            </div>
          </div>

          {s.user_override?.note && <p className="small" style={{ margin: 0 }}><span className="muted">Your note:</span> {s.user_override.note}</p>}

          <div className="grid2" style={{ alignItems: "start" }}>
            <div>
              <h3 className="prep-sec-h">Why this priority?</h3>
              <FactorBars factors={s.priority_factors} />
            </div>
            <OverrideForm prepId={prepId} s={s} onUpdated={onUpdated} />
          </div>

          {links.length > 0 && (
            <div>
              <h3 className="prep-sec-h">Concepts to study in your material</h3>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {links.map((l) => (
                  <li key={`${l.document_id}-${l.concept}`} style={{ marginBottom: ".2rem" }}>
                    <Link href={`/documents/${l.document_id}?page=${l.page}`}>{l.concept}</Link>
                    <span className="muted"> · {l.document_title}, p. {l.page}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {s.linked_sources.length > 0 && (
            <div>
              <h3 className="prep-sec-h">Study from your library</h3>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {s.linked_sources.map((src) => (
                  <li key={src.chunk_id} style={{ marginBottom: ".2rem" }}>
                    <Link href={`/documents/${src.document_id}`} title={src.section}>
                      {src.document_title}, {pages(src.page_start, src.page_end)}
                    </Link>
                    {src.section && <span className="muted"> · {src.section.split(" > ").slice(-1)[0]}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function FactorBars({ factors }: { factors: PriorityFactors }) {
  const keys = Object.keys(FACTOR_LABEL) as (keyof PriorityFactors)[];
  return (
    <div>
      <p className="muted small" style={{ margin: 0 }}>A longer bar pushes this skill up your list.</p>
      {keys.map((k) => {
        const v = Math.max(0, Math.min(1, factors[k] ?? 0));
        const pct = Math.round(v * 100);
        return (
          <div key={k} className="small" style={{ marginTop: ".45rem" }}>
            <div className="row spread" style={{ gap: ".3rem" }}>
              <span>{FACTOR_LABEL[k]}</span>
              <span className="muted">{pct}%</span>
            </div>
            <div className="meter" role="img" aria-label={`${FACTOR_LABEL[k]}: ${pct}%`}>
              <div style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function OverrideForm({ prepId, s, onUpdated }: { prepId: string; s: SkillMatch; onUpdated: (s: SkillMatch) => void }) {
  const [prio, setPrio] = useState<Priority | "">(s.user_override?.priority ?? "");
  const [note, setNote] = useState(s.user_override?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const fid = useId();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      const body: { priority?: Priority; note?: string } = { note: note.trim() };
      // The contract has no "clear override" value, so "use ours" re-sends the computed priority
      // (shown as not overridden because it equals s.priority).
      if (prio) body.priority = prio;
      else if (s.user_override?.priority) body.priority = s.priority;
      onUpdated(await interviewApi.patchSkill(prepId, s.id, body));
      setSaved(true);
    } catch (e2) {
      setErr(errMsg(e2, "We couldn't save your change. Check your connection and try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="stack-sm" aria-label={`Change the priority for ${s.name}`}>
      <h3 className="prep-sec-h">Disagree? Set your own</h3>
      <div>
        <label htmlFor={`${fid}-p`}>Your priority</label>
        <select id={`${fid}-p`} value={prio} onChange={(e) => setPrio(e.target.value as Priority | "")}>
          <option value="">Use ours ({PRIORITY_SHORT[s.priority]})</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_SHORT[p]}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor={`${fid}-n`}>Note (optional)</label>
        <textarea id={`${fid}-n`} rows={2} style={{ minHeight: 56 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. I use this daily but it's not on my resume yet" />
      </div>
      <div className="row">
        <button type="submit" disabled={busy}>{busy && <span className="spinner" />} Save</button>
        <span className="muted small" aria-live="polite">{saved ? "Saved" : ""}</span>
      </div>
      {err && <div className="notice bad small" role="alert">{err}</div>}
    </form>
  );
}
