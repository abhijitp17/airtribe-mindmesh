"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import GapCard, { skillState } from "@/components/today/GapCard";
import { errorText, plural } from "@/components/today/labels";
import { isClerk, rememberReport } from "@/lib/auth-mode";
import { publicApi, type PublicReport } from "@/lib/api-engagement";
import { roleBySlug } from "@/lib/roles";

const MIN = 200;
const MAX = 20000;

/** Public front door: a gap report before sign-up (UX research: acquisition). No Shell, no auth. */
export default function WelcomePage() {
  return (
    <Suspense fallback={null}>
      <Welcome />
    </Suspense>
  );
}

function Welcome() {
  const role = roleBySlug(useSearchParams().get("role"));  // from a role landing page: a typical ad pre-filled
  const [job, setJob] = useState(role?.sampleJob ?? "");
  const [resume, setResume] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [report, setReport] = useState<PublicReport | null>(null);
  const [link, setLink] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const resultHead = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (report) resultHead.current?.focus();
  }, [report]);

  function lengthProblem(label: string, text: string): string | null {
    const n = text.trim().length;
    if (n < MIN) return `The ${label} is too short. Paste at least ${MIN} characters (you have ${n}).`;
    if (n > MAX) return `The ${label} is too long. Keep it under ${MAX.toLocaleString()} characters.`;
    return null;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const problem = lengthProblem("job description", job) ?? lengthProblem("resume", resume);
    if (problem) {
      setErr(problem);
      return;
    }
    setBusy(true);
    setErr(null);
    setReport(null);
    try {
      setReport(await publicApi.gapReport(resume.trim(), job.trim()));
    } catch (e2) {
      setErr(errorText(e2, "Could not build the report. Check both texts and try again."));
    } finally {
      setBusy(false);
    }
  }

  async function importLink() {
    const url = link.trim();
    if (!url) {
      setImportMsg({ ok: false, text: "Paste the link to the job ad first." });
      return;
    }
    setImporting(true);
    setImportMsg(null);
    try {
      const page = await publicApi.jobFromUrl(/^https?:\/\//i.test(url) ? url : `https://${url}`);
      setJob(page.text);
      const what = page.title ? `“${page.title}${page.company ? `, ${page.company}` : ""}”` : "the job ad";
      setImportMsg({ ok: true, text: `Imported ${what}. Check the text below and remove anything that isn't part of the ad.` });
    } catch (e2) {
      setImportMsg({ ok: false, text: errorText(e2, "We couldn't import that link. Paste the job ad text instead.") });
    } finally {
      setImporting(false);
    }
  }

  const gaps = report ? report.skills.filter((s) => skillState(s) === "gap").length : 0;

  return (
    <div className="container" style={{ maxWidth: 880, paddingBottom: "3rem" }}>
      <style>{`
        .today-welcome-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 2rem; }
        .today-welcome-hero h1 { font-size: clamp(1.9rem, 1.2rem + 3vw, 2.8rem); font-weight: 500; }
        .today-welcome-fields { display: grid; gap: 1rem; }
        @media (min-width: 760px) { .today-welcome-fields { grid-template-columns: 1fr 1fr; } }
        .today-welcome-fields textarea { min-height: 200px; }
      `}</style>

      <header className="today-welcome-head">
        <span className="brand"><span className="brand-mark" aria-hidden /> Mindmesh</span>
        <Link href="/login" className="small" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}>Sign in</Link>
      </header>

      <main className="stack" id="main">
        <section className="today-welcome-hero">
          <h1>See what this role needs, and what your resume already proves</h1>
          <p className="muted" style={{ fontSize: "1.05rem" }}>
            Paste a job description and your resume. In about a minute you&apos;ll see the skills that matter most, the lines on your resume that back them up, and the gaps to close first.
          </p>
          {role && (
            <p className="notice info small" style={{ margin: 0 }}>
              We&apos;ve filled in a typical {role.title} job ad. Add your resume below, or paste the ad you&apos;re applying for.
            </p>
          )}
        </section>

        <form className="glass card stack" onSubmit={submit} aria-describedby="today-privacy" noValidate>
          <div>
            <label htmlFor="today-job-link">Job ad link <span className="muted small">(optional)</span></label>
            <div className="row" style={{ gap: ".5rem", flexWrap: "nowrap" }}>
              <input id="today-job-link" type="url" inputMode="url" autoComplete="url" value={link} placeholder="https://…"
                     onChange={(e) => setLink(e.target.value)} aria-describedby="today-job-link-msg" style={{ flex: 1, minWidth: 0 }}
                     onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void importLink(); } }} />
              <button type="button" onClick={() => void importLink()} disabled={importing} style={{ minHeight: 44, flex: "none" }}>
                {importing && <span className="spinner" aria-hidden />} {importing ? "Importing…" : "Import"}
              </button>
            </div>
            <p id="today-job-link-msg" className={importMsg ? `notice ${importMsg.ok ? "info" : "bad"} small` : "sr-only"}
               role="status" style={importMsg ? { margin: ".5rem 0 0" } : undefined}>
              {importMsg?.text ?? ""}
            </p>
          </div>
          <div className="today-welcome-fields">
            <div>
              <label htmlFor="today-job">Job description</label>
              <textarea id="today-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Paste the full job ad, including responsibilities and requirements" maxLength={MAX} />
            </div>
            <div>
              <label htmlFor="today-resume">Your resume</label>
              <textarea id="today-resume" value={resume} onChange={(e) => setResume(e.target.value)} placeholder="Paste your resume as plain text" maxLength={MAX} />
            </div>
          </div>
          <p id="today-privacy" className="notice info small row" style={{ margin: 0, gap: ".5rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
            <span aria-hidden style={{ marginTop: 2 }}><Icon name="user" size={16} /></span>
            <span>Remove your phone number and address first. Nothing is saved unless you create an account, and your text is never used to train AI models.</span>
          </p>
          {err && <div className="notice bad" role="alert">{err}</div>}
          <button key={report ? "again" : "first"} type="submit" className={report ? "lg block" : "primary lg block"} disabled={busy} style={{ minHeight: 52 }}>
            {busy && <span className="spinner" aria-hidden />} {busy ? "Reading both texts…" : report ? "Update my gap report" : "Show my gap report"}
          </button>
        </form>

        <div aria-live="polite" aria-busy={busy}>
          {busy && <ReportSkeleton />}
          {report && !busy && (
            <section className="stack" aria-labelledby="today-report-h">
              <div className="page-head" style={{ marginBottom: 0 }}>
                <div>
                  <h2 id="today-report-h" ref={resultHead} tabIndex={-1} style={{ fontSize: "1.5rem" }}>
                    {report.role_title || "Your gap report"}{report.company ? `, ${report.company}` : ""}
                  </h2>
                  {report.skills.length > 0 && (
                    <p>{gaps > 0 ? `${plural(gaps, "gap")} to close first.` : "No clear gaps in the top skills."} The top {plural(report.skills.length, "skill")} {report.skills.length === 1 ? "is" : "are"} below.</p>
                  )}
                </div>
              </div>
              {report.warnings.length > 0 && (
                <div className="notice warn small">
                  {report.warnings.map((w) => <p key={w} style={{ margin: 0 }}>{w}</p>)}
                </div>
              )}
              {report.skills.length === 0 ? (
                <div className="glass card stack-sm" role="status">
                  <h3 style={{ margin: 0 }}>We couldn&apos;t pick out this role&apos;s skills yet</h3>
                  <p className="muted small" style={{ margin: 0 }}>
                    Paste the full job posting with each requirement on its own line, and your resume with one
                    achievement per line. Then press the button above again.
                  </p>
                </div>
              ) : (
                <div className="grid2">
                  {report.skills.map((s) => <GapCard key={s.name} skill={s} />)}
                </div>
              )}
              {report.hidden_count > 0 && (
                <p className="muted small" style={{ margin: 0, textAlign: "center" }}>+{report.hidden_count} more skills after you sign up</p>
              )}
              {report.skills.length > 0 && (
              <div className="glass card hero-card stack-sm">
                <h3 style={{ margin: 0 }}>Close these gaps before the interview</h3>
                <p className="muted small" style={{ margin: 0 }}>Save the report and we&apos;ll turn it into a short daily plan and mock interview questions.</p>
                <Link
                  href={isClerk ? "/sign-up" : `/login?mode=signup&report=${encodeURIComponent(report.token)}`}
                  onClick={() => isClerk && rememberReport(report.token)}
                  className="btn primary lg block"
                  style={{ minHeight: 52, justifyContent: "space-between" }}
                >
                  Save this and build my plan <Icon name="arrow" size={18} />
                </Link>
              </div>
              )}
            </section>
          )}
        </div>
        <p className="small muted" style={{ textAlign: "center" }}>
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </main>
    </div>
  );
}

function ReportSkeleton() {
  return (
    <div className="stack" role="status">
      <span className="sr-only">Building your gap report</span>
      <div className="skeleton" style={{ height: 32, width: "60%" }} />
      <div className="grid2">
        {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 180, borderRadius: "var(--r-lg)" }} />)}
      </div>
    </div>
  );
}
