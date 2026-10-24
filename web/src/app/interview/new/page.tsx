"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Shell, { BackLink } from "@/components/Shell";
import PrepStyles from "@/components/interview/PrepStyles";
import { JobEditor, ResumeEditor } from "@/components/interview/editors";
import { errMsg } from "@/components/interview/labels";
import { api, type Doc } from "@/lib/api";
import { interviewApi, type JobOut, type JobParsed, type ResumeOut, type ResumeParsed } from "@/lib/api-interview";

export default function NewPrepPage() {
  return (
    <Shell>
      <Wizard />
    </Shell>
  );
}

type Step = 1 | 2 | 3;
const STEPS: [Step, string][] = [[1, "Resume"], [2, "Job description"], [3, "Check and confirm"]];
const ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function Wizard() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [resume, setResume] = useState<ResumeOut | null>(null);
  const [job, setJob] = useState<JobOut | null>(null);
  const [resumeEdit, setResumeEdit] = useState<ResumeParsed | null>(null);
  const [jobEdit, setJobEdit] = useState<JobParsed | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  // Move focus to the step heading when the step changes (keyboard and screen-reader users).
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    heading.current?.focus();
  }, [step]);

  return (
    <div className="prep-root stack" style={{ maxWidth: 860, margin: "0 auto" }}>
      <PrepStyles />
      <BackLink href="/prep">Prep</BackLink>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>New role prep</h1>
          <p>Add your resume and the job you want. We&apos;ll show what to work on first.</p>
        </div>
      </div>

      <ol className="prep-steps" aria-label={`Step ${step} of 3`}>
        {STEPS.map(([n, label]) => (
          <li key={n} aria-current={step === n ? "step" : undefined} className={n < step ? "done" : undefined}>
            <span className="bar" aria-hidden="true" />
            <span>
              {n < step && <span className="sr-only">Done: </span>}
              {label}
            </span>
          </li>
        ))}
      </ol>

      <div className="notice info small">
        <span style={{ fontWeight: 500 }}>Your privacy.</span> Remove details you don&apos;t want analysed (phone, address) before uploading. Your resume and job description are used only for your prep.
      </div>

      <div>
        <span className="prep-kicker">Step {step} of 3</span>
        <h2 ref={heading} tabIndex={-1} style={{ outline: "none", margin: ".1rem 0 0" }}>
          {STEPS[step - 1][1]}
        </h2>
      </div>

      {step === 1 && (
        <ResumeStep
          existing={resume}
          onDone={(r) => {
            if (r.id !== resume?.id || !resumeEdit) setResumeEdit(r.parsed); // keep edits when "Keep current"
            setResume(r);
            setStep(2);
          }}
        />
      )}
      {step === 2 && (
        <JobStep
          existing={job}
          onBack={() => setStep(1)}
          onDone={(j) => {
            if (j.id !== job?.id || !jobEdit) setJobEdit(j.parsed);
            setJob(j);
            setStep(3);
          }}
        />
      )}
      {step === 3 && resume && job && resumeEdit && jobEdit && (
        <ReviewStep
          resume={resume}
          job={job}
          resumeEdit={resumeEdit}
          jobEdit={jobEdit}
          setResumeEdit={setResumeEdit}
          setJobEdit={setJobEdit}
          onBack={() => setStep(2)}
          onCreated={(id) => router.push(`/interview/${id}`)}
        />
      )}
    </div>
  );
}

function ResumeStep({ existing, onDone }: { existing: ResumeOut | null; onDone: (r: ResumeOut) => void }) {
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  function pick(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    if (!/\.(pdf|docx)$/i.test(f.name)) {
      setErr("Please choose a PDF or DOCX file.");
      return;
    }
    setErr(null);
    setFile(f);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = mode === "file" && file ? await interviewApi.uploadResume(file) : await interviewApi.pasteResume(text.trim());
      onDone(r);
    } catch (e2) {
      setErr(errMsg(e2, "Could not read your resume"));
    } finally {
      setBusy(false);
    }
  }

  const ready = mode === "file" ? !!file : text.trim().length > 30;

  return (
    <form className="glass card stack" onSubmit={submit}>
      <div className="tabs" role="tablist" aria-label="How to add your resume">
        <button type="button" role="tab" aria-selected={mode === "file"} onClick={() => setMode("file")}>Upload file</button>
        <button type="button" role="tab" aria-selected={mode === "text"} onClick={() => setMode("text")}>Paste text</button>
      </div>

      {mode === "file" ? (
        <div
          className={`dropzone ${over ? "over" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="Choose a resume file (PDF or DOCX)"
          onClick={() => input.current?.click()}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
        >
          {file ? <span><strong>{file.name}</strong> selected. Click to change.</span> : <span>Drop your resume here or <u>choose a file</u> (PDF or DOCX)</span>}
          <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => pick(e.target.files)} />
        </div>
      ) : (
        <div>
          <label htmlFor="resume-text">Resume text</label>
          <textarea id="resume-text" rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste your resume here…" />
        </div>
      )}

      {existing && <p className="muted small" style={{ margin: 0 }}>You already added a resume{existing.source_filename ? ` (${existing.source_filename})` : ""}. Submitting again replaces it for this prep.</p>}
      {err && <div className="notice bad" role="alert">{err}</div>}

      <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap-reverse" }}>
        {existing && <button type="button" onClick={() => onDone(existing)}>Keep current resume</button>}
        <button type="submit" className="primary" disabled={busy || !ready}>
          {busy && <span className="spinner" />} {busy ? "Reading your resume…" : "Next: job description"}
        </button>
      </div>
    </form>
  );
}

function JobStep({ existing, onBack, onDone }: { existing: JobOut | null; onBack: () => void; onDone: (j: JobOut) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      onDone(await interviewApi.createJob(text.trim()));
    } catch (e2) {
      setErr(errMsg(e2, "Could not read the job description"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="glass card stack" onSubmit={submit}>
      <div>
        <label htmlFor="jd-text">Job description</label>
        <textarea id="jd-text" rows={14} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the full job description, including responsibilities and requirements…" />
      </div>
      {err && <div className="notice bad" role="alert">{err}</div>}
      <div className="row spread">
        <button type="button" onClick={onBack}>Back</button>
        <div className="row">
          {existing && <button type="button" onClick={() => onDone(existing)}>Keep current JD</button>}
          <button type="submit" className="primary" disabled={busy || text.trim().length < 30}>
            {busy && <span className="spinner" />} {busy ? "Reading the job description…" : "Next: review"}
          </button>
        </div>
      </div>
    </form>
  );
}

function ReviewStep(props: {
  resume: ResumeOut;
  job: JobOut;
  resumeEdit: ResumeParsed;
  jobEdit: JobParsed;
  setResumeEdit: (v: ResumeParsed) => void;
  setJobEdit: (v: JobParsed) => void;
  onBack: () => void;
  onCreated: (prepId: string) => void;
}) {
  const { resume, job, resumeEdit, jobEdit, setResumeEdit, setJobEdit, onBack, onCreated } = props;
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [docsErr, setDocsErr] = useState<string | null>(null);
  const [docIds, setDocIds] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.documents()
      .then((d) => setDocs(d.filter((x) => x.status === "ready")))
      .catch((e: unknown) => setDocsErr(errMsg(e, "Could not load your library")));
  }, []);

  const problems: string[] = [];
  if (!jobEdit.role_title.trim()) problems.push("Add a role title.");
  if (jobEdit.competencies.some((c) => !c.name.trim())) problems.push("Every competency needs a name (or remove it).");

  async function create() {
    if (problems.length) return;
    setBusy(true);
    setErr(null);
    try {
      const cleanResume: ResumeParsed = {
        ...resumeEdit,
        roles: resumeEdit.roles.map((r) => ({ ...r, bullets: r.bullets.filter((b) => b.text.trim()) })),
        education: resumeEdit.education.filter((e) => e.text.trim()),
      };
      await interviewApi.updateResume(resume.id, cleanResume);
      await interviewApi.updateJob(job.id, jobEdit);
      const prep = await interviewApi.createPrep({
        resume_id: resume.id,
        job_id: job.id,
        document_ids: docIds,
        ...(date ? { interview_date: date } : {}),
      });
      onCreated(prep.id);
    } catch (e) {
      setErr(errMsg(e, "Could not create the prep"));
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="glass card stack" aria-labelledby="rv-resume-h">
        <h3 id="rv-resume-h">Your resume</h3>
        <p className="muted small" style={{ margin: 0 }}>Check we read it correctly. We only use what&apos;s written here; nothing is added for you.</p>
        {resume.warnings.length > 0 && (
          <div className="notice warn small">
            <span style={{ fontWeight: 500 }}>Things to check</span>
            <ul style={{ margin: ".25rem 0 0", paddingLeft: "1.1rem" }}>{resume.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </div>
        )}
        <ResumeEditor value={resumeEdit} onChange={setResumeEdit} />
      </section>

      <section className="glass card stack" aria-labelledby="rv-jd-h">
        <h3 id="rv-jd-h">The role</h3>
        <JobEditor value={jobEdit} onChange={setJobEdit} />
      </section>

      <section className="glass card stack" aria-labelledby="rv-opt-h">
        <h3 id="rv-opt-h">Optional</h3>
        <div>
          <label htmlFor="iv-date">Interview date</label>
          <input
            id="iv-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            style={{ maxWidth: 240 }}
          />
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="small muted" style={{ marginBottom: ".25rem" }}>Study material to link (ready documents from your library)</legend>
          {docsErr && <div className="notice bad">{docsErr} You can link documents later.</div>}
          {!docs && !docsErr && <div className="skeleton" style={{ height: 44 }} role="status" aria-label="Loading your library" />}
          {docs && docs.length === 0 && <p className="muted small">No ready documents yet. You can link them later from your library.</p>}
          {docs?.map((d) => (
            <label key={d.id} className="row small" style={{ color: "var(--ink)", gap: ".5rem", margin: ".2rem 0", minHeight: 44 }}>
              <input
                type="checkbox"
                checked={docIds.includes(d.id)}
                onChange={(e) => setDocIds((ids) => (e.target.checked ? [...ids, d.id] : ids.filter((x) => x !== d.id)))}
              />
              {d.title || d.filename}
            </label>
          ))}
        </fieldset>
      </section>

      {problems.length > 0 && (
        <div className="notice warn" role="status">
          {problems.map((p) => <div key={p}>{p}</div>)}
        </div>
      )}
      {err && <div className="notice bad" role="alert">{err}</div>}

      <div className="row spread">
        <button type="button" onClick={onBack} disabled={busy}>Back</button>
        <button type="button" className="primary" onClick={create} disabled={busy || problems.length > 0}>
          {busy && <span className="spinner" />} {busy ? "Comparing your resume with the role…" : "Confirm and see my gaps"}
        </button>
      </div>
    </div>
  );
}
