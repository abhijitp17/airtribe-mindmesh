"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Icon from "@/components/Icon";
import Shell, { useUser } from "@/components/Shell";
import Cover from "@/components/today/Cover";
import DebriefCard from "@/components/today/DebriefCard";
import Onboarding from "@/components/today/Onboarding";
import UploadFirstOnboarding from "@/components/today/UploadFirstOnboarding";
import StartSession from "@/components/today/StartSession";
import WeekCard from "@/components/today/WeekCard";
import { errorText, isMinutes, plural } from "@/components/today/labels";
import { api, type Doc } from "@/lib/api";
import { engagementApi, type OnboardingVariant, type Prefs, type TodayPreview } from "@/lib/api-engagement";
import { todayIso } from "@/lib/api-goals";
import { interviewApi, type PrepSummary } from "@/lib/api-interview";
import { journeyApi, type Journey } from "@/lib/api-journey";

export default function TodayPage() {
  return (
    <Shell>
      <Today />
    </Shell>
  );
}

const TODAY_CSS = `
  .today-grid { display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr); }
  .today-grid > * { min-width: 0; }
  .today-side { display: grid; gap: 1rem; align-content: start; }
  .today-pair { display: grid; gap: .75rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  @media (min-width: 900px) { .today-grid { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); align-items: start; } }
  .today-who { display: flex; align-items: center; gap: .75rem; margin-bottom: 1rem; }
  .today-who .avatar { width: 46px; height: 46px; font-size: 1.1rem; }
`;

/** Soonest upcoming prep (by interview date), else the most recently updated. */
function soonestPrep(preps: PrepSummary[]): PrepSummary | null {
  if (!preps.length) return null;
  const today = todayIso();
  const upcoming = preps.filter((p) => p.interview_date && p.interview_date >= today).sort((a, b) => (a.interview_date ?? "").localeCompare(b.interview_date ?? ""));
  if (upcoming.length) return upcoming[0];
  return [...preps].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

function Today() {
  const user = useUser();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [preview, setPreview] = useState<TodayPreview | null>(null);
  const [preps, setPreps] = useState<PrepSummary[] | null>(null);
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [journey, setJourney] = useState<Journey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nothingToPractise, setNothingToPractise] = useState(false);
  const [variant, setVariant] = useState<OnboardingVariant | null>(null);
  const needsOnboarding = prefs !== null && !prefs.onboarded;

  // Onboarding experiment: the server picks the arm; record that it was shown (exposure) once it is.
  useEffect(() => {
    if (!needsOnboarding || variant) return;
    engagementApi.experiments()
      .then((x) => setVariant(x.onboarding))
      .catch(() => setVariant("goal_first"));
  }, [needsOnboarding, variant]);
  useEffect(() => {
    if (needsOnboarding && variant) engagementApi.event("onboarding_shown");
  }, [needsOnboarding, variant]);

  const load = useCallback(async () => {
    setError(null);
    setNothingToPractise(false);
    try {
      const [p, t] = await Promise.all([engagementApi.prefs(), engagementApi.todayPreview()]);
      setPrefs(p);
      setPreview(t);
    } catch (e) {
      setError(errorText(e, "Could not load Today."));
    }
    // Secondary data: Today still works without it.
    interviewApi.preps().then(setPreps).catch(() => setPreps([]));
    api.documents().then(setDocs).catch(() => setDocs([]));
    journeyApi.get().then(setJourney).catch(() => setJourney(null));
  }, []);

  useEffect(() => { load(); }, [load]);

  const name = (preview?.greeting_name || user?.display_name || "").trim();

  if (error && !preview) {
    return (
      <div className="stack">
        <div className="notice bad row spread" role="alert">
          <span>{error} Check your connection and try again.</span>
          <button type="button" onClick={load} style={{ minHeight: 44 }}>Try again</button>
        </div>
      </div>
    );
  }

  if (!prefs || !preview) return <TodaySkeleton />;

  if (!prefs.onboarded) {
    if (!variant) return <TodaySkeleton />;
    const finished = (p: Prefs) => { setPrefs(p); load(); };
    return (
      <div className="narrow">
        <style>{TODAY_CSS}</style>
        {variant === "upload_first"
          ? <UploadFirstOnboarding name={name} onFinished={finished} />
          : <Onboarding name={name} initial={prefs} onFinished={finished} />}
      </div>
    );
  }

  const cd = preview.countdown;
  const prep = soonestPrep(preps ?? []);
  const prepId = cd?.prep_id ?? prep?.id ?? null;
  const allSuggestions = [...preview.suggestions["5"], ...preview.suggestions["15"], ...preview.suggestions["30"]];
  // The builder never returns empty suggestions when any material or prep exists (CONTRACTS §7).
  const isEmpty = nothingToPractise || (preview.library_count === 0 && !cd && allSuggestions.length === 0 && (preps === null || preps.length === 0));
  const minutes = isMinutes(prefs.default_minutes) ? prefs.default_minutes : 15;

  return (
    <div>
      <style>{TODAY_CSS}</style>
      {journey ? <Cover name={name} journey={journey} countdown={cd} /> : (
        <h1 className="display" style={{ fontSize: "1.6rem" }}>{name ? `${name}’s notebook` : "Your notebook"}</h1>
      )}

      {error && (
        <div className="notice bad row spread" role="alert" style={{ marginBottom: "1rem" }}>
          <span>{error}</span>
          <button type="button" onClick={load} style={{ minHeight: 44 }}>Try again</button>
        </div>
      )}

      {isEmpty ? (
        <EmptyToday onAdded={load} />
      ) : (
        <div className="today-grid">
          <div className="stack" id="session" style={{ scrollMarginTop: "80px" }}>
            {preview.debrief_due && <DebriefCard due={preview.debrief_due} />}
            <StartSession key={minutes} suggestions={preview.suggestions} initialMinutes={minutes} onNothingToPractise={() => setNothingToPractise(true)} />
          </div>

          <div className="today-side">
            <div className="today-pair">
              <Link href={prepId ? `/interview/${prepId}` : "/interview/new"} className="glass tile-link">
                <span className="tile-top">
                  <span className="icon-well sm" aria-hidden><Icon name="mic" /></span>
                  <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
                </span>
                <strong>Mock interview</strong>
                <span className="muted small">{prepId ? "Practise out loud" : "Add a job to start"}</span>
              </Link>
              <Link href="/map" className="glass tile-link">
                <span className="tile-top">
                  <span className="icon-well sm" aria-hidden><Icon name="mesh" /></span>
                  <span className="arrow-tile" aria-hidden><Icon name="arrow" size={18} /></span>
                </span>
                <strong>Your map</strong>
                <span className="muted small">{plural(preview.library_count, "document")} connected</span>
              </Link>
            </div>

            <WeekCard week={preview.week} />

            {preview.last_win && (
              <section className="glass card tint-warm row" aria-label="Your last win" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                <span className="icon-well sm" aria-hidden><Icon name="sparkle" /></span>
                <div style={{ minWidth: 0 }}>
                  <p className="tiny muted" style={{ margin: 0 }}>Last win</p>
                  <h2 style={{ fontSize: "1.05rem", margin: ".1rem 0" }}>{preview.last_win.title}</h2>
                  <p className="small muted" style={{ margin: 0 }}>{preview.last_win.detail}</p>
                </div>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** A new notebook: try the sample chapter first (no upload needed), or start from your own material or a role. */
function EmptyToday({ onAdded }: { onAdded: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function sample() {
    setBusy(true);
    setErr(null);
    try {
      const doc = await api.sampleDocument();
      onAdded();
      router.push(`/documents/${doc.id}`);
    } catch (e) {
      setErr(errorText(e, "Couldn't add the sample. Try again."));
      setBusy(false);
    }
  }
  return (
    <section className="glass hero-card stack" aria-labelledby="today-empty-h">
      <span className="icon-well" aria-hidden><Icon name="book" size={24} /></span>
      <div>
        <h2 id="today-empty-h">Let&apos;s fill your first page</h2>
        <p className="muted" style={{ margin: 0 }}>Try Mindmesh on a short sample chapter about how learning sticks: see its ideas on your map, take a quick quiz, and ask it questions. Delete it whenever you like.</p>
      </div>
      {err && <div className="notice bad small" role="alert">{err}</div>}
      <button type="button" className="primary lg block" onClick={sample} disabled={busy} style={{ minHeight: 52 }}>
        {busy && <span className="spinner" aria-hidden />} Explore a sample chapter
      </button>
      <div className="row" style={{ justifyContent: "center", gap: ".5rem 1.25rem" }}>
        <Link href="/library" className="small">Upload your own material</Link>
        <Link href="/interview/new" className="small">Start with a job you want</Link>
      </div>
    </section>
  );
}

function TodaySkeleton() {
  return (
    <div role="status" aria-label="Loading Today">
      <style>{TODAY_CSS}</style>
      <div className="today-who">
        <div className="skeleton" style={{ width: 46, height: 46, borderRadius: "50%" }} />
        <div className="stack-sm" style={{ flex: 1 }}>
          <div className="skeleton" style={{ height: 20, width: 140 }} />
          <div className="skeleton" style={{ height: 14, width: 200 }} />
        </div>
      </div>
      <div className="today-grid">
        <div className="stack">
          <div className="skeleton" style={{ height: 52, borderRadius: 20 }} />
          <div className="skeleton" style={{ height: 320, borderRadius: "var(--r-xl)" }} />
        </div>
        <div className="today-side">
          <div className="today-pair">
            <div className="skeleton" style={{ height: 132, borderRadius: "var(--r-lg)" }} />
            <div className="skeleton" style={{ height: 132, borderRadius: "var(--r-lg)" }} />
          </div>
          <div className="skeleton" style={{ height: 110, borderRadius: "var(--r-lg)" }} />
        </div>
      </div>
    </div>
  );
}
