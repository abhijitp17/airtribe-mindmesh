"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Shell, { BackLink } from "@/components/Shell";
import { DeepDive, PrepPlan, Sessions } from "@/components/interview/PrepPanels";
import PrepStyles from "@/components/interview/PrepStyles";
import ReadinessProfile from "@/components/interview/ReadinessProfile";
import SkillMatrix, { effectivePriority } from "@/components/interview/SkillMatrix";
import { GAP_TYPES_REAL, countdown, errMsg, longDate } from "@/components/interview/labels";
import { interviewApi, type PrepOut, type SkillMatch, type StudyLink } from "@/lib/api-interview";
import SharePanel from "@/components/interview/SharePanel";

export default function PrepPage() {
  return (
    <Shell wide>
      <PrepDashboard />
    </Shell>
  );
}

/** "Gaps to close first": real gaps at critical or high priority (after the user's overrides). */
function gapsFirst(skills: SkillMatch[]): number {
  return skills.filter((s) => GAP_TYPES_REAL.includes(s.gap_type) && (effectivePriority(s) === "critical" || effectivePriority(s) === "high")).length;
}

function DashboardSkeleton() {
  return (
    <div className="stack" role="status" aria-label="Loading your prep">
      <div className="skeleton" style={{ height: 120, borderRadius: "var(--r-xl)" }} />
      <div className="prep-dims">
        {[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 130 }} />)}
      </div>
      <div className="prep-grid">
        {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 190 }} />)}
      </div>
    </div>
  );
}

function PrepDashboard() {
  const { id } = useParams<{ id: string }>();
  const [prep, setPrep] = useState<PrepOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [links, setLinks] = useState<Record<string, StudyLink[]>>({});

  useEffect(() => {
    setError(null);
    interviewApi.prep(id).then(setPrep).catch((e: unknown) => setError(errMsg(e, "We couldn't load this prep.")));
    interviewApi.studyLinks(id).then(setLinks).catch(() => setLinks({}));  // optional: the graph may not be built yet
  }, [id, tick]);

  async function recompute() {
    setBusy(true);
    setActionErr(null);
    setStatus("");
    try {
      setPrep(await interviewApi.recompute(id));
      setStatus("Updated with your latest resume, job description and practice.");
    } catch (e) {
      setActionErr(errMsg(e, "We couldn't update this prep. Try again in a moment."));
    } finally {
      setBusy(false);
    }
  }

  function onSkillUpdated(s: SkillMatch) {
    setPrep((p) => p && { ...p, skills: p.skills.map((x) => (x.id === s.id ? s : x)) });
  }

  if (error) {
    return (
      <div className="prep-root stack">
        <PrepStyles />
        <BackLink href="/prep">Prep</BackLink>
        <div className="notice bad row spread" role="alert">
          <span>{error} Check your connection and try again.</span>
          <button type="button" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      </div>
    );
  }
  if (!prep) {
    return (
      <div className="prep-root stack">
        <PrepStyles />
        <BackLink href="/prep">Prep</BackLink>
        <DashboardSkeleton />
      </div>
    );
  }

  const nGaps = gapsFirst(prep.skills);
  const subline = [
    prep.company,
    prep.interview_date ? `Interview on ${longDate(prep.interview_date)}` : null,
  ].filter(Boolean).join(". ");

  return (
    <div className="prep-root stack">
      <PrepStyles />
      <BackLink href="/prep">Prep</BackLink>

      <header className="stack-sm">
        <div className="row spread" style={{ alignItems: "flex-end" }}>
          <div style={{ minWidth: 0, flex: "1 1 320px" }}>
            <h1 className="prep-title-xl">{prep.role_title}</h1>
            {subline && <p className="prep-sub">{subline}.</p>}
          </div>
          <span className="prep-chip">
            {nGaps > 0 ? <><b>{nGaps} gap{nGaps === 1 ? "" : "s"}</b> to close first</> : <><b>No urgent gaps</b> right now</>}
          </span>
        </div>
        <div className="row" style={{ gap: ".5rem" }}>
          <DateEditor prep={prep} onSaved={setPrep} />
          <button type="button" onClick={recompute} disabled={busy} title="Use your latest resume, job description and practice answers">
            {busy && <span className="spinner" />} {busy ? "Updating…" : "Update"}
          </button>
        </div>
        <div aria-live="polite" className="muted small">{status}</div>
        {actionErr && <div className="notice bad" role="alert">{actionErr}</div>}
      </header>

      <ReadinessProfile dims={prep.readiness} />
      <SkillMatrix prepId={prep.id} skills={prep.skills} onSkillUpdated={onSkillUpdated} studyLinks={links} />

      <div className="grid2" style={{ alignItems: "start" }}>
        <Sessions prepId={prep.id} />
        <PrepPlan plan={prep.plan} skills={prep.skills} />
        <SharePanel prepId={prep.id} />
      </div>
      <DeepDive prepId={prep.id} version={prep.updated_at} />
    </div>
  );
}

function DateEditor({ prep, onSaved }: { prep: PrepOut; onSaved: (p: PrepOut) => void }) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(prep.interview_date ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save(value: string | null) {
    setBusy(true);
    setErr(null);
    try {
      onSaved(await interviewApi.patchPrep(prep.id, { interview_date: value }));
      setEditing(false);
    } catch (e) {
      setErr(errMsg(e, "We couldn't save the date. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <div className="row small" style={{ gap: ".5rem" }}>
        <span className={`badge ${prep.interview_date ? "info" : ""}`}>{countdown(prep.interview_date)}</span>
        <button type="button" className="ghost small" onClick={() => { setDate(prep.interview_date ?? ""); setEditing(true); }}>
          {prep.interview_date ? "Change date" : "Set interview date"}
        </button>
      </div>
    );
  }

  return (
    <form className="glass row small" style={{ padding: ".6rem .75rem" }} onSubmit={(e) => { e.preventDefault(); save(date || null); }}>
      <label htmlFor="prep-date" style={{ margin: 0 }}>Interview date</label>
      <input id="prep-date" type="date" value={date} autoFocus onChange={(e) => setDate(e.target.value)} style={{ width: "auto" }} />
      <button type="submit" className="dark small" disabled={busy}>{busy && <span className="spinner" />} Save</button>
      {prep.interview_date && <button type="button" className="small" disabled={busy} onClick={() => save(null)}>Clear date</button>}
      <button type="button" className="ghost small" onClick={() => setEditing(false)}>Cancel</button>
      {err && <div className="notice bad" role="alert">{err}</div>}
    </form>
  );
}
