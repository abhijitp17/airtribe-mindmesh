// Typed client for the interview prep API (docs/CONTRACTS.md §2, §3). All paths are under /api/interview.

import { json, request } from "@/lib/api";

// ---- §2 shared enums ----
export type Importance = "critical" | "high" | "medium" | "low";
export type EvidenceStrength = "strong" | "partial" | "none";
export type AssessedLevel = "strong" | "developing" | "weak" | "unverified";
export type Confidence = "high" | "medium" | "low";
export type GapType =
  | "strong"
  | "knowledge_gap"
  | "application_gap"
  | "evidence_gap"
  | "communication_gap"
  | "unverified"
  | "stretch";
export type Priority = "critical" | "high" | "medium" | "low";
export type CompetencyCat = "technical" | "domain" | "tool" | "behavioral" | "leadership" | "communication";
export type QuestionCat = "technical" | "behavioral" | "case" | "resume_deep_dive" | "role_specific";

// ---- §3 types ----
export type ResumeBullet = { id: string; text: string }; // text = verbatim from resume
export type ResumeRole = { id: string; title: string; company: string; start: string | null; end: string | null; bullets: ResumeBullet[] };
export type ResumeParsed = {
  name: string | null;
  summary: string | null;
  roles: ResumeRole[];
  skills: string[];
  education: { id: string; text: string }[];
  certifications: string[];
};
export type ResumeOut = {
  id: string;
  source_filename: string | null;
  parsed: ResumeParsed;
  warnings: string[];
  user_confirmed: boolean;
  created_at: string;
  updated_at: string;
};

export type Competency = {
  id: string;
  name: string;
  category: CompetencyCat;
  importance: Importance;
  required: boolean;
  evidence_quote: string; // verbatim from JD
};
export type JobParsed = {
  role_title: string;
  company: string | null;
  seniority: string | null;
  responsibilities: string[];
  competencies: Competency[];
};
export type JobOut = { id: string; parsed: JobParsed; user_confirmed: boolean; created_at: string; updated_at: string };

export type EvidenceRef = { bullet_id: string; text: string; role_title: string };
export type PriorityFactors = {
  importance: number;
  gap_severity: number;
  evidence_confidence: number;
  urgency: number;
  feasibility: number;
}; // each 0..1
export type LinkedSource = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  page_start: number;
  page_end: number;
  section: string;
};
export type SkillMatch = {
  id: string;
  competency_id: string;
  name: string;
  category: CompetencyCat;
  jd_importance: Importance;
  resume_strength: EvidenceStrength;
  resume_evidence: EvidenceRef[];
  assessed_level: AssessedLevel;
  assessed_explanation: string;
  confidence: Confidence;
  gap_type: GapType;
  priority: Priority;
  priority_factors: PriorityFactors;
  recommended_action: string;
  linked_sources: LinkedSource[];
  user_override: { priority?: Priority; note?: string } | null;
};
export type PlanActivity = "learn" | "practice" | "story" | "mock_interview" | "drill";
export type PrepPlanItem = {
  id: string;
  competency_id: string | null;
  title: string;
  activity: PlanActivity;
  estimated_minutes: number;
  reason: string;
};
export type ReadinessDimension =
  | "role_knowledge"
  | "applied_problem_solving"
  | "resume_evidence"
  | "behavioral_examples"
  | "communication";
export type ReadinessDim = { dimension: ReadinessDimension; level: AssessedLevel; evidence_count: number; explanation: string };
export type PrepOut = {
  id: string;
  resume_id: string;
  job_id: string;
  role_title: string;
  company: string | null;
  interview_date: string | null; // YYYY-MM-DD
  document_ids: string[];
  skills: SkillMatch[]; // sorted by priority (critical first), then importance
  plan: PrepPlanItem[];
  readiness: ReadinessDim[];
  created_at: string;
  updated_at: string;
};
export type PrepSummary = {
  id: string;
  role_title: string;
  company: string | null;
  interview_date: string | null;
  critical_gaps: number;
  sessions: number;
  updated_at: string;
};

export type CriterionStatus = "met" | "partial" | "missing";
export type Criterion = { criterion: string; points: number; status: CriterionStatus; evidence: string };
export type Verdict = "strong" | "adequate" | "needs_work" | "unassessed";
export type StarCheck = { situation: boolean; task: boolean; action: boolean; result: boolean; reflection: boolean };
export type Evaluation = {
  verdict: Verdict;
  score: number; // 0..1, computed in code from criteria
  criteria: Criterion[];
  star: StarCheck | null; // behavioral only
  strengths: string[];
  improvements: string[];
  missing_details: string[]; // facts the CANDIDATE must supply; never invented
  feedback: string;
};
export type InterviewTurn = {
  id: string;
  position: number;
  kind: "question" | "follow_up";
  category: QuestionCat;
  competency_id: string | null;
  competency_name: string | null;
  question: string;
  answer: string | null;
  evaluation: Evaluation | null;
  asked_at: string;
  answered_at: string | null;
};
export type SessionSummary = {
  overall: string;
  by_competency: { competency_id: string; name: string; score: number; attempts: number }[];
  top_improvements: string[];
  suggested_drills: string[];
};
export type SessionFocus = "mixed" | "technical" | "behavioral" | "resume" | "case";
export type InterviewSession = {
  id: string;
  prep_id: string;
  focus: SessionFocus;
  status: "active" | "completed";
  target_questions: number;
  turns: InterviewTurn[];
  summary: SessionSummary | null;
  started_at: string;
  ended_at: string | null;
};
export type SessionListItem = {
  id: string;
  focus: string;
  status: string;
  questions: number;
  avg_score: number | null;
  started_at: string;
};
export type DeepDiveItem = { bullet_id: string; bullet: string; questions: string[] };

export type CreatePrepBody = { resume_id: string; job_id: string; document_ids?: string[]; interview_date?: string };
export type PatchPrepBody = { interview_date?: string | null; document_ids?: string[] };
export type PatchSkillBody = { priority?: Priority; note?: string };
export type CreateSessionBody = { focus?: SessionFocus; target_questions?: number }; // target_questions 3..10

const P = "/interview";

export const interviewApi = {
  // Resumes
  uploadResume: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ResumeOut>(`${P}/resumes`, { method: "POST", body: fd });
  },
  pasteResume: (text: string) => request<ResumeOut>(`${P}/resumes`, { method: "POST", body: json({ text }) }),
  resumes: () => request<ResumeOut[]>(`${P}/resumes`),
  resume: (id: string) => request<ResumeOut>(`${P}/resumes/${id}`),
  updateResume: (id: string, parsed: ResumeParsed) =>
    request<ResumeOut>(`${P}/resumes/${id}`, { method: "PUT", body: json({ parsed }) }),
  deleteResume: (id: string) => request<void>(`${P}/resumes/${id}`, { method: "DELETE" }),

  // Jobs
  createJob: (text: string) => request<JobOut>(`${P}/jobs`, { method: "POST", body: json({ text }) }),
  job: (id: string) => request<JobOut>(`${P}/jobs/${id}`),
  updateJob: (id: string, parsed: JobParsed) => request<JobOut>(`${P}/jobs/${id}`, { method: "PUT", body: json({ parsed }) }),
  deleteJob: (id: string) => request<void>(`${P}/jobs/${id}`, { method: "DELETE" }),

  // Preps
  createPrep: (body: CreatePrepBody) => request<PrepOut>(`${P}/preps`, { method: "POST", body: json(body) }),
  preps: () => request<PrepSummary[]>(`${P}/preps`),
  prep: (id: string) => request<PrepOut>(`${P}/preps/${id}`),
  recompute: (id: string) => request<PrepOut>(`${P}/preps/${id}/recompute`, { method: "POST" }),
  /** Where each skill is taught in the learner's own material: {skill id: links}. */
  studyLinks: (id: string) => request<Record<string, StudyLink[]>>(`${P}/preps/${id}/study-links`),
  shares: (id: string) => request<PlanShare[]>(`${P}/preps/${id}/shares`),
  createShare: (id: string) => request<PlanShare>(`${P}/preps/${id}/shares`, { method: "POST" }),
  revokeShare: (id: string, shareId: string) => request<void>(`${P}/preps/${id}/shares/${shareId}`, { method: "DELETE" }),
  patchSkill: (prepId: string, skillId: string, body: PatchSkillBody) =>
    request<SkillMatch>(`${P}/preps/${prepId}/skills/${skillId}`, { method: "PATCH", body: json(body) }),
  patchPrep: (id: string, body: PatchPrepBody) => request<PrepOut>(`${P}/preps/${id}`, { method: "PATCH", body: json(body) }),
  deletePrep: (id: string) => request<void>(`${P}/preps/${id}`, { method: "DELETE" }),
  deepDive: (id: string) => request<DeepDiveItem[]>(`${P}/preps/${id}/deep-dive`),

  // Sessions
  startSession: (prepId: string, body: CreateSessionBody = {}) =>
    request<InterviewSession>(`${P}/preps/${prepId}/sessions`, { method: "POST", body: json(body) }),
  sessions: (prepId: string) => request<SessionListItem[]>(`${P}/preps/${prepId}/sessions`),
  session: (sid: string) => request<InterviewSession>(`${P}/sessions/${sid}`),
  answer: (sid: string, answer: string) =>
    request<InterviewSession>(`${P}/sessions/${sid}/answer`, { method: "POST", body: json({ answer }) }),
  endSession: (sid: string) => request<InterviewSession>(`${P}/sessions/${sid}/end`, { method: "POST" }),
};

/** A concept in the learner's material that teaches a skill (knowledge graph maps_to). */
export type StudyLink = { concept: string; document_id: string; document_title: string; page: number; verified: boolean };

/** A read-only link to a prep plan. `url` is only returned once, when the link is created. */
export type PlanShare = { id: string; url: string | null; expires_at: string; views: number; created_at: string };

/** What a shared link shows: no resume, documents, answers or personal details. */
export type SharedPlan = {
  role_title: string;
  company: string | null;
  interview_date: string | null;
  plan: { title: string; activity: string; estimated_minutes: number; reason: string; skill: string | null }[];
  skills: { name: string; priority: string; status: string }[];
  expires_at: string;
};
