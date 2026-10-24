"use client";

import { useEffect, useState } from "react";
import Icon, { type IconName } from "@/components/Icon";
import Shell, { useUser } from "@/components/Shell";
import LibStyles from "@/components/library/styles";
import { API_URL, ApiError, api, authHeaders, request } from "@/lib/api";
import { engagementApi, type Prefs } from "@/lib/api-engagement";
import { useEndSession } from "@/lib/session";

type Usage = { last_24h_tokens: number; daily_budget: number; by_task: { task: string; tokens: number }[] };

const fmt = (n: number) => n.toLocaleString();

function filenameFrom(disposition: string | null): string {
  const m = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return m ? m[1] : `mindmesh-export-${new Date().toISOString().slice(0, 10)}.json`;
}

function SectionHead({ id, icon, title, sub }: { id: string; icon: IconName; title: string; sub?: string }) {
  return (
    <div className="row" style={{ gap: ".75rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
      <span className="icon-well sm" aria-hidden><Icon name={icon} size={20} /></span>
      <div style={{ minWidth: 0 }}>
        <h2 id={id} style={{ fontSize: "1.15rem", margin: ".45rem 0 0" }}>{title}</h2>
        {sub && <p className="small muted" style={{ margin: ".15rem 0 0" }}>{sub}</p>}
      </div>
    </div>
  );
}

function Profile() {
  const user = useUser();
  if (!user) return null;
  const initial = (user.display_name || user.email).trim().charAt(0).toUpperCase() || "M";
  return (
    <section className="glass hero-card stack" aria-labelledby="profile-h">
      <div className="row" style={{ gap: ".9rem", flexWrap: "nowrap" }}>
        <span className="avatar" aria-hidden style={{ width: 56, height: 56, fontSize: "1.3rem" }}>{initial}</span>
        <div style={{ minWidth: 0 }}>
          <h2 id="profile-h" style={{ margin: 0 }}>{user.display_name || "Your profile"}</h2>
          <p className="small muted" style={{ margin: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{user.email}</p>
        </div>
      </div>
      <div>
        <label htmlFor="profile-email">Email</label>
        <input id="profile-email" type="email" value={user.email} readOnly aria-readonly="true" />
      </div>
      {user.display_name && (
        <div>
          <label htmlFor="profile-name">Display name</label>
          <input id="profile-name" type="text" value={user.display_name} readOnly aria-readonly="true" />
        </div>
      )}
    </section>
  );
}

const SOLID_KEY = "mindmesh_solid";

function readSolid(): boolean {
  try {
    return window.localStorage.getItem(SOLID_KEY) === "true";
  } catch {
    return false;
  }
}

function applySolid(on: boolean) {
  if (on) document.documentElement.dataset.solid = "true";
  else delete document.documentElement.dataset.solid;
}

function ReduceTransparency() {
  const [on, setOn] = useState(false);

  // Apply the saved preference on load (the integrator also applies it app-wide).
  useEffect(() => {
    const saved = readSolid();
    setOn(saved);
    applySolid(saved);
  }, []);

  function toggle() {
    const next = !on;
    setOn(next);
    applySolid(next);
    try {
      if (next) window.localStorage.setItem(SOLID_KEY, "true");
      else window.localStorage.removeItem(SOLID_KEY);
    } catch {
      // Storage blocked: the setting still applies for this visit.
    }
  }

  return (
    <section className="glass stack" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="solid-h">
      <SectionHead id="solid-h" icon="settings" title="Display" />
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-labelledby="solid-label"
        aria-describedby="solid-hint"
        onClick={toggle}
        className="ghost block"
        style={{ justifyContent: "space-between", textAlign: "left", gap: "1rem", minHeight: 56, padding: ".5rem .25rem", fontWeight: 400 }}
      >
        <span style={{ minWidth: 0 }}>
          <span id="solid-label" style={{ display: "block", fontWeight: 500 }}>Reduce transparency</span>
          <span id="solid-hint" className="small muted" style={{ display: "block" }}>Solid cards instead of frosted glass. Easier to read, and kinder to older phones.</span>
        </span>
        <span className="lib-switch" data-on={on ? "true" : "false"} aria-hidden />
      </button>
      <p className="small muted" style={{ margin: 0 }} aria-live="polite">{on ? "On: solid surfaces." : "Off: frosted glass."}</p>
    </section>
  );
}

function Reminders() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    engagementApi.prefs().then(setPrefs).catch((e: unknown) => setErr(e instanceof Error ? e.message : "unknown error"));
  }, []);

  async function save(patch: Partial<Pick<Prefs, "reminders" | "quiet_start" | "quiet_end">>) {
    if (!prefs) return;
    const before = prefs;
    setPrefs({ ...prefs, ...patch });  // optimistic
    setErr(null);
    try {
      setPrefs(await engagementApi.updatePrefs(patch));
      setSaved("Saved.");
    } catch (e) {
      setPrefs(before);
      setErr(`We couldn't save that (${e instanceof Error ? e.message : "unknown error"}).`);
    }
  }

  return (
    <section className="glass stack" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="remind-h">
      <SectionHead id="remind-h" icon="bell" title="Reminders" />
      {!prefs && !err && <div role="status" className="skeleton" style={{ height: 56 }} aria-busy="true" aria-label="Loading reminders" />}
      {prefs && (
        <>
          <button
            type="button" role="switch" aria-checked={prefs.reminders} aria-labelledby="remind-label" aria-describedby="remind-hint"
            onClick={() => void save({ reminders: !prefs.reminders })} className="ghost block"
            style={{ justifyContent: "space-between", textAlign: "left", gap: "1rem", minHeight: 56, padding: ".5rem .25rem", fontWeight: 400 }}
          >
            <span style={{ minWidth: 0 }}>
              <span id="remind-label" style={{ display: "block", fontWeight: 500 }}>Email reminders</span>
              <span id="remind-hint" className="small muted" style={{ display: "block" }}>
                An evening nudge on days you haven&apos;t practised and something is ready, and a short summary on Monday
                mornings. Never more than one a day, never in your quiet hours.
              </span>
            </span>
            <span className="lib-switch" data-on={prefs.reminders ? "true" : "false"} aria-hidden />
          </button>
          <fieldset className="row" style={{ border: 0, padding: 0, margin: 0, gap: "1rem", flexWrap: "wrap" }} disabled={!prefs.reminders}>
            <legend className="small muted" style={{ padding: 0, marginBottom: ".35rem" }}>Quiet hours: no emails between</legend>
            <label className="small" style={{ display: "grid", gap: ".25rem" }}>From
              <input type="time" value={prefs.quiet_start} onChange={(e) => e.target.value && void save({ quiet_start: e.target.value })} style={{ minHeight: 44 }} />
            </label>
            <label className="small" style={{ display: "grid", gap: ".25rem" }}>Until
              <input type="time" value={prefs.quiet_end} onChange={(e) => e.target.value && void save({ quiet_end: e.target.value })} style={{ minHeight: 44 }} />
            </label>
          </fieldset>
          <p className="small muted" style={{ margin: 0 }}>Emails only say how much is ready, never what&apos;s in your documents.</p>
        </>
      )}
      {err && <div className="notice bad small" role="alert">{err}</div>}
      <p className="sr-only" aria-live="polite">{saved}</p>
    </section>
  );
}

function SignOut() {
  const endSession = useEndSession();
  function signOut() {
    void endSession();
  }
  return (
    <section className="glass row spread" style={{ padding: "1rem 1.3rem" }} aria-labelledby="signout-h">
      <div style={{ minWidth: 0 }}>
        <h2 id="signout-h" style={{ fontSize: "1.15rem", margin: 0 }}>Sign out</h2>
        <p className="small muted" style={{ margin: 0 }}>Your work stays saved. Sign in again any time.</p>
      </div>
      <button type="button" className="dark" onClick={signOut} style={{ minHeight: 44 }}>Sign out</button>
    </section>
  );
}

function ExportData() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const res = await fetch(`${API_URL}/api/account/export`, { headers: await authHeaders() });
      if (!res.ok) {
        let msg = res.statusText || "Export failed";
        try {
          const body: unknown = await res.json();
          if (body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string") {
            msg = (body as { detail: string }).detail;
          }
        } catch {
          /* not JSON */
        }
        throw new ApiError(res.status, msg);
      }
      const name = filenameFrom(res.headers.get("Content-Disposition"));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDone(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass stack" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="export-h">
      <SectionHead id="export-h" icon="upload" title="Download my data" />
      <p className="small muted" style={{ margin: 0 }}>
        A JSON file with everything stored for your account: documents (metadata and extracted text), chat history,
        quizzes and answers, interview prep, goals and plans, and AI usage. Your password is never included. Uploaded
        files are listed by name; download each one from its document page.
      </p>
      <div className="row">
        <button type="button" className="primary" onClick={download} disabled={busy} style={{ minHeight: 44 }}>
          {busy && <span className="spinner" />} {busy ? "Preparing…" : "Download my data"}
        </button>
      </div>
      {done && <div className="notice good" role="status">Done. We saved {done} to your downloads.</div>}
      {error && <div className="notice bad row spread" role="alert"><span>The download didn&apos;t finish ({error}). Try again.</span><button type="button" className="small" onClick={download} style={{ minHeight: 44 }}>Try again</button></div>}
    </section>
  );
}

function UsageCard() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setError(null);
    request<Usage>("/account/usage")
      .then(setUsage)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load usage"));
  }, [reload]);

  const limited = usage !== null && usage.daily_budget > 0;
  const pct = usage !== null && usage.daily_budget > 0
    ? Math.min(100, Math.round((usage.last_24h_tokens / usage.daily_budget) * 100))
    : 0;
  const level = pct >= 100 ? "Limit reached" : pct >= 80 ? "Nearly used up" : "Plenty left";
  const badge = pct >= 100 ? "gap" : pct >= 80 ? "warn" : "good";

  return (
    <section className="glass stack" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="usage-h">
      <SectionHead id="usage-h" icon="chart" title="AI usage today" />
      {error && (
        <div className="notice bad row spread" role="alert">
          <span>We couldn&apos;t load your usage ({error}).</span>
          <button type="button" className="small" onClick={() => setReload((n) => n + 1)} style={{ minHeight: 44 }}>Try again</button>
        </div>
      )}
      {!usage && !error && (
        <div role="status" className="stack-sm" aria-busy="true" aria-label="Loading usage">
          <div className="skeleton" style={{ height: 16, width: "70%" }} />
          <div className="skeleton" style={{ height: 6 }} />
        </div>
      )}
      {usage && (
        <>
          {limited ? (
            <>
              <div className="row spread small">
                <span>
                  {fmt(usage.last_24h_tokens)} of {fmt(usage.daily_budget)} tokens in the last 24 hours ({pct}%)
                </span>
                <span className={`badge ${badge}`}>{level}</span>
              </div>
              <div
                className="meter"
                role="meter"
                aria-label="AI usage in the last 24 hours"
                aria-valuemin={0}
                aria-valuemax={usage.daily_budget}
                aria-valuenow={Math.min(usage.last_24h_tokens, usage.daily_budget)}
                aria-valuetext={`${pct}% of daily limit used`}
              >
                <div style={{ width: `${pct}%`, background: pct >= 100 ? "var(--orange)" : undefined }} />
              </div>
              <p className="small muted">The limit is a rolling 24-hour window, so usage frees up gradually.</p>
            </>
          ) : (
            <p className="small">{fmt(usage.last_24h_tokens)} tokens in the last 24 hours. No daily limit is set.</p>
          )}
          {usage.by_task.length > 0 ? (
            <table className="small" style={{ width: "100%", borderCollapse: "collapse" }}>
              <caption className="sr-only">Tokens by feature</caption>
              <thead>
                <tr>
                  <th scope="col" style={{ textAlign: "left", padding: ".3rem 0" }}>Feature</th>
                  <th scope="col" style={{ textAlign: "right", padding: ".3rem 0" }}>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_task.map((t) => (
                  <tr key={t.task} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={{ padding: ".3rem 0" }}>{t.task.replace(/_/g, " ")}</td>
                    <td style={{ padding: ".3rem 0", textAlign: "right" }}>{fmt(t.tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="small muted">No AI requests in the last 24 hours.</p>
          )}
        </>
      )}
    </section>
  );
}

function Privacy() {
  return (
    <section className="glass stack" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="privacy-h">
      <SectionHead id="privacy-h" icon="user" title="Privacy" sub="Private by default. Not used for training." />
      <ul className="small" style={{ margin: 0, paddingLeft: "1.2rem", display: "grid", gap: ".4rem" }}>
        <li><strong style={{ fontWeight: 500 }}>Private by default.</strong> Your documents, answers and plans are visible only to your account. Nothing is shared.</li>
        <li><strong style={{ fontWeight: 500 }}>Not used for training.</strong> Your content is not used to train AI models. It is sent to the AI provider only to answer your request.</li>
        <li>
          <strong style={{ fontWeight: 500 }}>What we store:</strong> your email and a hashed password; uploaded files and the text extracted from them;
          tutor chats; quizzes, your answers and feedback; resumes, job descriptions and interview sessions; goals and study
          plans; and AI usage counts (token totals per feature, not the content).
        </li>
        <li><strong style={{ fontWeight: 500 }}>You are in control.</strong> Download everything above at any time, or delete your account to remove it all.</li>
      </ul>
    </section>
  );
}

function DeleteAccount() {
  const endSession = useEndSession();
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const armed = confirm === "DELETE";

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    if (!armed) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount();  // the API also removes the Clerk identity (queued)
      await endSession("/welcome");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete account");
      setBusy(false);
    }
  }

  return (
    <section className="glass stack tint-gap" style={{ padding: "1.2rem 1.3rem" }} aria-labelledby="delete-h">
      <h2 id="delete-h" className="danger" style={{ fontSize: "1.15rem", margin: 0 }}>Delete account</h2>
      <p className="small" style={{ margin: 0 }}>
        This permanently deletes your account, every uploaded file, and all derived data (chats, quizzes, progress, interview
        prep, goals). It cannot be undone. Consider downloading your data first.
      </p>
      <form onSubmit={remove} className="stack">
        <div>
          <label htmlFor="delete-confirm">Type DELETE to confirm</label>
          <input
            id="delete-confirm"
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            aria-describedby="delete-help"
          />
          <p id="delete-help" className="small muted" style={{ marginTop: ".25rem" }}>Capital letters, exactly as shown.</p>
        </div>
        {error && <div className="notice bad" role="alert">{error}</div>}
        <div className="row">
          <button type="submit" className="danger" disabled={!armed || busy} style={{ borderColor: "var(--bad)", minHeight: 44, background: "var(--solid)" }}>
            {busy && <span className="spinner" />} Permanently delete my account
          </button>
        </div>
      </form>
    </section>
  );
}

export default function SettingsPage() {
  return (
    <Shell>
      <LibStyles />
      <div className="stack narrow">
        <div className="page-head">
          <div>
            <h1>Profile</h1>
            <p>Your account, display and data.</p>
          </div>
        </div>
        <Profile />
        <ReduceTransparency />
        <Reminders />
        <Privacy />
        <h2 style={{ fontSize: "1rem", margin: "1.5rem 0 0" }} className="muted">Your data</h2>
        <ExportData />
        <UsageCard />
        <SignOut />
        <DeleteAccount />
      </div>
    </Shell>
  );
}
