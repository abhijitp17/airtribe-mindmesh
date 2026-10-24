"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Icon from "@/components/Icon";
import { ApiError } from "@/lib/api";
import { engagementApi, type Minutes, type SessionStep } from "@/lib/api-engagement";
import StepList from "./StepList";
import TimePicker from "./TimePicker";
import { errorText, summarizeSteps } from "./labels";

/** The Today hero: "Today's N minutes", time picker, step list and the one orange "Start session" button. */
export default function StartSession({
  suggestions,
  initialMinutes,
  onNothingToPractise,
}: {
  suggestions: Record<"5" | "15" | "30", SessionStep[]>;
  initialMinutes: Minutes;
  /** Called when the server says there is nothing to practise (422), so the page can show its empty state. */
  onNothingToPractise?: () => void;
}) {
  const router = useRouter();
  const [minutes, setMinutes] = useState<Minutes>(initialMinutes);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const steps = suggestions[String(minutes) as "5" | "15" | "30"] ?? [];

  async function start() {
    setBusy(true);
    setErr(null);
    try {
      const s = await engagementApi.startSession(minutes);
      router.push(`/session/${s.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && onNothingToPractise) {
        setBusy(false);
        onNothingToPractise();
        return;
      }
      setErr(errorText(e, "Could not start the session. Try again in a moment."));
      setBusy(false);
    }
  }

  return (
    <section className="glass hero-card stack" aria-labelledby="today-hero-h">
      <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start", gap: ".9rem" }}>
        <span className="icon-well" aria-hidden><Icon name="sparkle" size={24} /></span>
        <div style={{ minWidth: 0 }}>
          <h2 id="today-hero-h" style={{ fontSize: "1.3rem", marginBottom: ".2rem" }}>Today&apos;s {minutes} minutes</h2>
          <p className="muted small" style={{ margin: 0 }} aria-live="polite">
            {steps.length ? summarizeSteps(steps) : "Nothing to suggest for this length yet."}
          </p>
        </div>
      </div>
      <TimePicker value={minutes} onChange={setMinutes} disabled={busy} />
      {steps.length > 0 && (
        <div className="glass" style={{ padding: ".25rem .9rem", background: "rgba(255,255,255,0.55)" }}>
          <StepList steps={steps} />
        </div>
      )}
      {err && <div className="notice bad" role="alert">{err}</div>}
      <button type="button" className="primary lg block" onClick={start} disabled={busy || steps.length === 0} style={{ minHeight: 52 }}>
        {busy && <span className="spinner" aria-hidden />} Start session
      </button>
    </section>
  );
}
