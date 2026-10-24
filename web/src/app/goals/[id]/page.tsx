"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Icon from "@/components/Icon";
import Shell, { BackLink } from "@/components/Shell";
import AddSessionForm from "@/components/goals/AddSessionForm";
import PlanItemRow from "@/components/goals/PlanItemRow";
import ProposalPanel from "@/components/goals/ProposalPanel";
import { startQuizSession } from "@/components/goals/session";
import PrepStyles from "@/components/interview/PrepStyles";
import {
  GOAL_TYPE_LABEL,
  WEEKDAYS,
  formatDay,
  formatMinutes,
  goalsApi,
  todayIso,
  type GoalOut,
  type PlanItem,
  type PlanItemCreate,
  type PlanItemPatch,
  type PlanProposal,
} from "@/lib/api-goals";

export default function GoalPage() {
  return (
    <Shell>
      <GoalView />
    </Shell>
  );
}

function groupByDate(items: PlanItem[]): [string, PlanItem[]][] {
  const map = new Map<string, PlanItem[]>();
  for (const it of [...items].sort((a, b) => a.position - b.position)) {
    const list = map.get(it.scheduled_date);
    if (list) list.push(it);
    else map.set(it.scheduled_date, [it]);
  }
  return [...map.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
}

function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

function GoalView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [goal, setGoal] = useState<GoalOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setGoal(await goalsApi.get(id));
    } catch (e) {
      setError(errMsg(e, "Could not load this goal"));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setError(errMsg(e, "Something went wrong"));
    } finally {
      setBusy(null);
    }
  }

  if (!goal) {
    return (
      <div className="prep-root stack">
        <PrepStyles />
        <BackLink href="/prep">Prep</BackLink>
        {error ? (
          <div className="notice bad row spread" role="alert">
            <span>{error} Check your connection and try again.</span>
            <button type="button" onClick={() => { setError(null); load(); }}>Try again</button>
          </div>
        ) : (
          <div className="stack" role="status" aria-label="Loading your plan">
            <div className="skeleton" style={{ height: 180, borderRadius: "var(--r-xl)" }} />
            <div className="skeleton" style={{ height: 120 }} />
            <div className="skeleton" style={{ height: 120 }} />
          </div>
        )}
      </div>
    );
  }

  const g = goal;
  const today = todayIso();
  const minDate = today;
  const s = g.stats;
  const pct = s.total_minutes ? Math.round((s.done_minutes / s.total_minutes) * 100) : 0;
  const upcoming = g.items
    .filter((i) => i.scheduled_date >= today && i.status !== "skipped")
    .reduce((n, i) => n + i.estimated_minutes, 0);
  const groups = groupByDate(g.items);
  const proposal: PlanProposal | null = g.pending_proposal;

  const patchItem = (item: PlanItem, body: PlanItemPatch) =>
    run(item.id, async () => {
      await goalsApi.updateItem(item.id, body);
      await load();
    });

  const deleteItem = (item: PlanItem) =>
    run(item.id, async () => {
      if (!confirm(`Delete "${item.topic}" from your plan?`)) return;
      await goalsApi.removeItem(item.id);
      await load();
    });

  const startItem = (item: PlanItem) =>
    run(item.id, async () => {
      const quizId = await startQuizSession(g.document_ids, item);
      router.push(`/quiz/${quizId}`);
    });

  async function addItem(body: PlanItemCreate): Promise<boolean> {
    let ok = false;
    await run("add", async () => {
      await goalsApi.addItem(g.id, body);
      await load();
      ok = true;
      setAdding(false);
    });
    return ok;
  }

  const regenerate = () =>
    run("regenerate", async () => {
      setGoal(await goalsApi.regenerate(g.id, true));
      setNotice("Plan rebuilt. Your edited and finished sessions stayed where they were.");
    });

  const checkPlan = () =>
    run("adapt", async () => {
      const p = await goalsApi.adapt(g.id);
      // The server supersedes any earlier pending proposal on adapt, so always replace it here.
      setGoal({ ...g, pending_proposal: p });
      if (!p) setNotice("Your plan looks fine: no missed sessions and no concepts that need extra review.");
    });

  const decide = (accept: boolean) =>
    run("proposal", async () => {
      if (!proposal) return;
      setGoal(accept ? await goalsApi.acceptProposal(proposal.id) : await goalsApi.rejectProposal(proposal.id));
      setNotice(accept ? "Changes applied to your plan." : "Kept your plan as it was.");
    });

  const setStatus = (status: GoalOut["status"]) =>
    run("status", async () => {
      setGoal(await goalsApi.update(g.id, { status }));
    });

  const removeGoal = () =>
    run("delete", async () => {
      if (!confirm(`Delete the goal "${g.title}" and its whole plan?`)) return;
      await goalsApi.remove(g.id);
      router.push("/prep");
    });

  const disabled = busy !== null;
  const daysLeftLabel = s.days_left === 1 ? "1 day left" : `${s.days_left} days left`;
  const statusWord = g.status === "paused" ? "Paused" : g.status === "completed" ? "Finished" : null;

  return (
    <div className="prep-root stack">
      <PrepStyles />
      <BackLink href="/prep">Prep</BackLink>

      <header className="stack-sm" aria-labelledby="goal-h">
        <span className="prep-kicker">{GOAL_TYPE_LABEL[g.goal_type]}{statusWord && ` · ${statusWord}`}</span>
        <h1 id="goal-h" className="prep-title-xl">{g.title}</h1>
        {g.target_outcome && <p className="prep-sub">{g.target_outcome}</p>}
      </header>

      <section className="glass card stack" aria-label="Progress">
        <div className="prep-stats">
          <div className="prep-stat">
            <span className="muted small">Done</span>
            <span className="prep-stat-v">{pct}%</span>
            <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
                 aria-label={`Progress: ${pct}% of planned minutes done`} style={{ marginTop: ".4rem" }}>
              <div style={{ width: `${pct}%` }} />
            </div>
            <span className="muted tiny">{s.items_done} of {s.items_total} sessions · {formatMinutes(s.done_minutes)} of {formatMinutes(s.total_minutes)}</span>
          </div>
          <div className="prep-stat">
            <span className="muted small">Pace</span>
            <span className="prep-stat-v">{s.on_track ? "On track" : "Behind plan"}</span>
            <span className="muted tiny">
              {s.on_track ? "You're keeping up with your plan." : "Some sessions were missed. Check your plan to catch up."}
            </span>
          </div>
          <div className="prep-stat">
            <span className="muted small">Time left</span>
            <span className="prep-stat-v">{daysLeftLabel}</span>
            <span className="muted tiny">Deadline {formatDay(g.deadline)}</span>
          </div>
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          {formatMinutes(upcoming)} planned of {formatMinutes(s.capacity_minutes)} available · {g.minutes_per_day} min a day on {g.study_days.map((d) => WEEKDAYS[d]).join(", ")}
        </p>

        {g.feasibility_warning && (
          <div className="notice warn" role="status"><span style={{ fontWeight: 500 }}>Not everything fits.</span> {g.feasibility_warning}</div>
        )}

        <div className="row">
          <button className={proposal ? "" : "primary"} onClick={checkPlan} disabled={disabled}>
            {busy === "adapt" && <span className="spinner" />} Check my plan
          </button>
          <button onClick={regenerate} disabled={disabled} title="Rebuild future sessions. Your edits and finished sessions stay in place.">
            {busy === "regenerate" && <span className="spinner" />} Rebuild my plan
          </button>
          <button onClick={() => setAdding((a) => !a)} disabled={disabled} aria-expanded={adding}>
            <Icon name="plus" size={18} /> Add session
          </button>
        </div>
        <div className="row" style={{ gap: ".25rem" }}>
          {g.status === "active" ? (
            <button className="ghost small" onClick={() => setStatus("paused")} disabled={disabled}>Pause goal</button>
          ) : (
            <button className="ghost small" onClick={() => setStatus("active")} disabled={disabled}>Resume goal</button>
          )}
          {g.status !== "completed" && (
            <button className="ghost small" onClick={() => setStatus("completed")} disabled={disabled}>Mark goal finished</button>
          )}
          <button className="ghost small danger" onClick={removeGoal} disabled={disabled}>Delete goal</button>
        </div>
      </section>

      <div aria-live="polite">
        {error && <div className="notice bad" role="alert">{error}</div>}
        {notice && <div className="notice info">{notice}</div>}
      </div>

      {proposal && (
        <ProposalPanel proposal={proposal} items={g.items} busy={busy === "proposal"}
                       onAccept={() => decide(true)} onReject={() => decide(false)} />
      )}

      {adding && (
        <AddSessionForm minDate={minDate} deadline={g.deadline} defaultMinutes={g.minutes_per_day}
                        busy={busy === "add"} onAdd={addItem} onCancel={() => setAdding(false)} />
      )}

      <section className="stack" aria-labelledby="plan-days-h">
        <h2 id="plan-days-h" style={{ margin: 0 }}>Your plan, day by day</h2>
        {groups.length === 0 && (
          <div className="glass empty">
            <p style={{ marginBottom: ".75rem" }}>No sessions in this plan yet.</p>
            <button type="button" onClick={() => setAdding(true)}>Add a session</button>
          </div>
        )}
        {groups.map(([day, items]) => {
          const isToday = day === today;
          const total = items.filter((i) => i.status !== "skipped").reduce((n, i) => n + i.estimated_minutes, 0);
          const over = total > g.minutes_per_day && day >= today;
          const past = day < today;
          return (
            <section key={day} className={`glass ${isToday ? "hero-card" : "card"}`} aria-labelledby={`day-${day}`}
                     style={past ? { opacity: 0.85 } : undefined}>
              <div className="row spread" style={{ marginBottom: ".6rem" }}>
                <h3 id={`day-${day}`} style={{ margin: 0 }} className="row">
                  {isToday && <span className="badge dark">Today</span>}
                  <span>{formatDay(day)}</span>
                  {past && <span className="muted small" style={{ fontWeight: 400 }}>Past</span>}
                </h3>
                <span className="small row" style={{ gap: ".4rem" }}>
                  {formatMinutes(total)} of {formatMinutes(g.minutes_per_day)}
                  {over && <span className="badge warn">Over your daily time</span>}
                </span>
              </div>
              <ul className="prep-items">
                {items.map((it) => (
                  <PlanItemRow key={it.id} item={it} deadline={g.deadline} minDate={minDate}
                               busy={disabled} onPatch={patchItem} onDelete={deleteItem} onStart={startItem} />
                ))}
              </ul>
            </section>
          );
        })}
      </section>
    </div>
  );
}
