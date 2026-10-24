"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ACTIVITY, GAP, PRIORITY_SHORT } from "@/components/interview/labels";
import { API_URL } from "@/lib/api";
import type { GapType, Priority, PlanActivity, SharedPlan } from "@/lib/api-interview";

/** A prep plan someone shared (P3). Public and read-only: the role, the plan and skill priorities only. */
export default function SharedPlanPage() {
  const { token } = useParams<{ token: string }>();
  const [plan, setPlan] = useState<SharedPlan | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/public/shared-plans/${encodeURIComponent(token)}`)
      .then(async (r) => (r.ok ? setPlan(await r.json()) : setGone(true)))
      .catch(() => setGone(true));
  }, [token]);

  const total = plan?.plan.reduce((a, p) => a + p.estimated_minutes, 0) ?? 0;
  return (
    <div className="container" style={{ maxWidth: 760, paddingBottom: "3rem" }}>
      <header className="row spread" style={{ margin: "1rem 0 2rem" }}>
        <Link href="/welcome" className="brand"><span className="brand-mark" aria-hidden /> Mindmesh</Link>
      </header>
      <main id="main" className="stack" aria-busy={!plan && !gone}>
        {gone && (
          <div className="glass card stack-sm" role="alert">
            <h1 style={{ fontSize: "1.5rem", margin: 0 }}>This link isn&apos;t available</h1>
            <p className="muted" style={{ margin: 0 }}>It may have expired or been turned off by the person who shared it.</p>
            <Link href="/roles">See how Mindmesh prepares you for a role</Link>
          </div>
        )}
        {!plan && !gone && <div role="status" className="skeleton" style={{ height: 240 }}><span className="sr-only">Loading…</span></div>}
        {plan && (
          <>
            <section className="stack-sm">
              <p className="muted small" style={{ margin: 0 }}>A shared interview prep plan</p>
              <h1 style={{ margin: 0 }}>{plan.role_title || "Interview prep"}{plan.company ? `, ${plan.company}` : ""}</h1>
              {plan.interview_date && <p className="muted" style={{ margin: 0 }}>Interview on {new Date(plan.interview_date + "T12:00:00").toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</p>}
            </section>
            <section className="glass card stack-sm" aria-labelledby="sp-plan-h">
              <h2 id="sp-plan-h" style={{ fontSize: "1.2rem", margin: 0 }}>The plan</h2>
              <p className="muted small" style={{ margin: 0 }}>{plan.plan.length} steps · about {total} minutes</p>
              <ol className="stack-sm" style={{ margin: 0, paddingLeft: "1.2rem" }}>
                {plan.plan.map((p, i) => (
                  <li key={i}>
                    <strong style={{ fontWeight: 500 }}>{p.title}</strong>{" "}
                    <span className="badge">{ACTIVITY[p.activity as PlanActivity] ?? p.activity}</span>{" "}
                    <span className="badge">{p.estimated_minutes} min</span>
                    {p.reason && <div className="muted small">{p.reason}</div>}
                  </li>
                ))}
              </ol>
            </section>
            <section className="glass card stack-sm" aria-labelledby="sp-skills-h">
              <h2 id="sp-skills-h" style={{ fontSize: "1.2rem", margin: 0 }}>Skills, by priority</h2>
              <ul className="stack-sm" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {plan.skills.map((s) => (
                  <li key={s.name}>
                    {s.name} <span className="muted small">· {PRIORITY_SHORT[s.priority as Priority] ?? s.priority} · {GAP[s.status as GapType]?.[0] ?? s.status}</span>
                  </li>
                ))}
              </ul>
            </section>
            <p className="small muted" style={{ margin: 0 }}>
              Shared from Mindmesh. Resumes, documents and practice answers are never included.{" "}
              <Link href="/roles">Make your own plan</Link>.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
