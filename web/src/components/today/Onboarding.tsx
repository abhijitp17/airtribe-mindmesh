"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { engagementApi, type Prefs, type PreparingFor } from "@/lib/api-engagement";
import { PREPARING_CHOICES, errorText } from "./labels";

/**
 * Three quick steps inside one glass card: goal first, then a weekly target, then the first piece of material.
 * Prefs are saved with onboarded:true when the user leaves via the final link, "Skip for now", or "Go to Today".
 */
export default function Onboarding({ name, initial, onFinished }: { name: string; initial: Prefs; onFinished: (p: Prefs) => void }) {
  const router = useRouter();
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [preparing, setPreparing] = useState<PreparingFor | null>(initial.preparing_for);
  const [weekly, setWeekly] = useState<number>(initial.weekly_target >= 1 && initial.weekly_target <= 7 ? initial.weekly_target : 3);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const head = useRef<HTMLHeadingElement>(null);
  const mounted = useRef(false);

  useEffect(() => {
    // Move focus to the new question after each step (not on first render).
    if (mounted.current) head.current?.focus();
    mounted.current = true;
  }, [step]);

  async function finish(withChoices: boolean): Promise<boolean> {
    setBusy(true);
    setErr(null);
    try {
      const body = withChoices
        ? { onboarded: true as const, weekly_target: weekly, ...(preparing ? { preparing_for: preparing } : {}) }
        : { onboarded: true as const };
      engagementApi.event("onboarding_choice", { variant: "goal_first", choice: withChoices && preparing ? preparing : "skip" });
      const p = await engagementApi.updatePrefs(body);
      onFinished(p);
      return true;
    } catch (e) {
      setErr(errorText(e, "Could not save your choices. Try again."));
      setBusy(false);
      return false;
    }
  }

  const next = preparing === "interview"
    ? { href: "/interview/new", label: "Add your resume and a job", hint: "See what the role needs and what your resume already proves.", icon: "prep" as const }
    : { href: "/library", label: "Upload your first document", hint: "Notes, a textbook chapter or slides. We'll build questions from it.", icon: "upload" as const };

  return (
    <section className="glass hero-card stack" aria-labelledby="today-ob-h">
      <div className="row spread">
        <span className="muted small">Step {step + 1} of 3</span>
        <button type="button" className="ghost small" onClick={() => finish(false)} disabled={busy} style={{ minHeight: 44 }}>
          Skip for now
        </button>
      </div>

      {step === 0 && (
        <div className="stack">
          <div>
            <p className="muted small" style={{ margin: 0 }}>Welcome{name ? `, ${name}` : ""}.</p>
            <h1 id="today-ob-h" ref={head} tabIndex={-1} style={{ fontSize: "1.6rem" }}>What are you preparing for?</h1>
          </div>
          <div className="stack-sm" role="group" aria-labelledby="today-ob-h">
            {PREPARING_CHOICES.map((c) => (
              <button
                key={c.value}
                type="button"
                className="block glass"
                aria-pressed={preparing === c.value}
                onClick={() => { setPreparing(c.value); setStep(1); }}
                style={{
                  justifyContent: "flex-start", textAlign: "left", padding: ".85rem 1rem", minHeight: 72, gap: ".85rem",
                  boxShadow: preparing === c.value ? "inset 0 0 0 2px var(--ink)" : undefined,
                }}
              >
                <span className="icon-well" aria-hidden style={{ width: 44, height: 44 }}><Icon name={c.icon} size={22} /></span>
                <span style={{ flex: 1 }}>
                  <span style={{ display: "block", fontSize: "1.05rem" }}>{c.label}</span>
                  <span className="muted small" style={{ fontWeight: 400 }}>{c.hint}</span>
                </span>
                <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="stack">
          <h1 id="today-ob-h" ref={head} tabIndex={-1} style={{ fontSize: "1.6rem" }}>How many sessions a week feels realistic?</h1>
          <p className="muted" style={{ margin: 0 }}>A session can be as short as 5 minutes. Missing a day is fine; we count the week, not a streak.</p>
          <div className="segmented" role="group" aria-label="Sessions per week">
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <button key={n} type="button" aria-pressed={weekly === n} onClick={() => setWeekly(n)} style={{ minHeight: 48, padding: ".5rem 0" }}>
                {n}
              </button>
            ))}
          </div>
          <p className="small muted" aria-live="polite" style={{ margin: 0 }}>{weekly} {weekly === 1 ? "session" : "sessions"} a week</p>
          <div className="row spread">
            <button type="button" className="ghost" onClick={() => setStep(0)} style={{ minHeight: 44 }}>Back</button>
            <button type="button" className="dark" onClick={() => setStep(2)} style={{ minHeight: 44 }}>Continue</button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="stack">
          <h1 id="today-ob-h" ref={head} tabIndex={-1} style={{ fontSize: "1.6rem" }}>Your first step</h1>
          <Link
            href={next.href}
            className="glass tile-link"
            onClick={async (e) => {
              e.preventDefault();
              const ok = await finish(true);
              if (ok) router.push(next.href);
            }}
            aria-disabled={busy}
            style={{ minHeight: 0 }}
          >
            <span className="tile-top">
              <span className="icon-well" aria-hidden><Icon name={next.icon} size={22} /></span>
              <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
            </span>
            <strong>{next.label}</strong>
            <span className="muted small">{next.hint}</span>
          </Link>
          <div className="row spread">
            <button type="button" className="ghost" onClick={() => setStep(1)} disabled={busy} style={{ minHeight: 44 }}>Back</button>
            <button type="button" onClick={() => finish(true)} disabled={busy} style={{ minHeight: 44 }}>
              {busy && <span className="spinner" aria-hidden />} Go to Today
            </button>
          </div>
        </div>
      )}

      {err && <div className="notice bad" role="alert">{err}</div>}
    </section>
  );
}
