"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { engagementApi, type DebriefNext, type DebriefOutcome, type TodayPreview } from "@/lib/api-engagement";
import { OUTCOMES, errorText, nextStepsFor } from "./labels";

type Due = NonNullable<TodayPreview["debrief_due"]>;

/** "How did your interview go?" One tap for the outcome, then the right next step (UX research: plan for the end of the deadline). */
export default function DebriefCard({ due, onDone }: { due: Due; onDone?: () => void }) {
  const router = useRouter();
  const [outcome, setOutcome] = useState<DebriefOutcome | null>(null);
  const [busy, setBusy] = useState<DebriefNext | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [thanks, setThanks] = useState(false);
  const nextHead = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (outcome) nextHead.current?.focus();
  }, [outcome]);

  const role = due.company ? `${due.company} ${due.role_title}` : due.role_title;

  async function choose(next: DebriefNext) {
    if (!outcome) return;
    setBusy(next);
    setErr(null);
    try {
      const res = await engagementApi.debrief(due.prep_id, outcome, next);
      if (res.follow_up?.type === "prep") router.push(`/interview/${res.follow_up.id}`);
      else if (res.follow_up?.type === "goal") router.push(`/goals/${res.follow_up.id}`);
      else if (next === "new_role") router.push("/interview/new");
      else {
        setThanks(true);
        setBusy(null);
        onDone?.();
      }
    } catch (e) {
      setErr(errorText(e, "Could not save your answer. Check your connection and try again."));
      setBusy(null);
    }
  }

  if (thanks) {
    return (
      <section className="glass card" aria-live="polite">
        <p style={{ margin: 0 }}>Thanks for telling us. Good luck with whatever comes next.</p>
      </section>
    );
  }

  return (
    <section className="glass card tint-warm stack-sm" aria-labelledby="today-debrief-h">
      <h2 id="today-debrief-h" style={{ fontSize: "1.08rem" }}>How did your {role} interview go?</h2>
      <div className="row" role="group" aria-label="Interview outcome" style={{ gap: ".5rem" }}>
        {OUTCOMES.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={outcome === o.value}
            onClick={() => setOutcome(o.value)}
            disabled={busy !== null}
            className={outcome === o.value ? "dark" : undefined}
            style={{ minHeight: 44, borderRadius: "var(--r-pill)" }}
          >
            {o.label}
          </button>
        ))}
      </div>
      <div aria-live="polite">
        {outcome && (
          <div className="stack-sm" style={{ marginTop: ".75rem" }}>
            <h3 ref={nextHead} tabIndex={-1} style={{ fontSize: "1rem" }}>What would help next?</h3>
            <div className="stack-sm">
              {nextStepsFor(outcome).map((n) => (
                <button
                  key={n.value}
                  type="button"
                  className="block"
                  onClick={() => choose(n.value)}
                  disabled={busy !== null}
                  style={{ justifyContent: "space-between", textAlign: "left", minHeight: 52 }}
                >
                  <span>
                    <span style={{ display: "block" }}>{n.label}</span>
                    <span className="muted small" style={{ fontWeight: 400 }}>{n.hint}</span>
                  </span>
                  {busy === n.value && <span className="spinner" aria-label="Saving" />}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {err && <div className="notice bad" role="alert">{err}</div>}
    </section>
  );
}
