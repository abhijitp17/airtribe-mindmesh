"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Icon from "@/components/Icon";
import { engagementApi, type Prefs } from "@/lib/api-engagement";
import { errorText } from "./labels";

/**
 * Onboarding experiment, "upload_first" arm (docs/ux-research.md): start with the material, no questions first.
 * The goal is inferred later from what the learner does (a prep means an interview, a document means study).
 */
export default function UploadFirstOnboarding({ name, onFinished }: { name: string; onFinished: (p: Prefs) => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go(choice: "upload" | "prep" | "skip", href?: string) {
    setBusy(true);
    setErr(null);
    engagementApi.event("onboarding_choice", { variant: "upload_first", choice });
    try {
      const p = await engagementApi.updatePrefs({ onboarded: true });
      if (href) router.push(href);
      else onFinished(p);
    } catch (e) {
      setErr(errorText(e, "Could not continue. Try again."));
      setBusy(false);
    }
  }

  const tiles = [
    { choice: "upload" as const, href: "/library", icon: "upload" as const, label: "Upload a document",
      hint: "Notes, a textbook chapter or slides. Ask questions and get a quiz from it in a minute." },
    { choice: "prep" as const, href: "/interview/new", icon: "prep" as const, label: "Add your resume and a job",
      hint: "See what the role needs and what your resume already proves." },
  ];

  return (
    <section className="glass hero-card stack" aria-labelledby="today-ob-h">
      <div className="row spread">
        <p className="muted small" style={{ margin: 0 }}>Welcome{name ? `, ${name}` : ""}.</p>
        <button type="button" className="ghost small" onClick={() => void go("skip")} disabled={busy} style={{ minHeight: 44 }}>
          Skip for now
        </button>
      </div>
      <div>
        <h1 id="today-ob-h" style={{ fontSize: "1.6rem" }}>Start with your own material</h1>
        <p className="muted" style={{ margin: 0 }}>Everything Mindmesh does comes from what you add. Pick one to begin.</p>
      </div>
      <div className="stack-sm">
        {tiles.map((t) => (
          <Link
            key={t.choice}
            href={t.href}
            className="glass tile-link"
            aria-disabled={busy}
            onClick={(e) => { e.preventDefault(); if (!busy) void go(t.choice, t.href); }}
            style={{ minHeight: 0 }}
          >
            <span className="tile-top">
              <span className="icon-well" aria-hidden><Icon name={t.icon} size={22} /></span>
              <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
            </span>
            <strong>{t.label}</strong>
            <span className="muted small">{t.hint}</span>
          </Link>
        ))}
      </div>
      {err && <div className="notice bad" role="alert">{err}</div>}
    </section>
  );
}
