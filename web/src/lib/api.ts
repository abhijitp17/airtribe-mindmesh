import { getToken } from "@clerk/nextjs";
import { isClerk, SIGN_IN_PATH } from "./auth-mode";
// Typed client for the Mindmesh API.

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8300";

export type User = { id: string; email: string; display_name: string; level: string };

export type DocStatus = "uploaded" | "processing" | "needs_attention" | "ready" | "failed";
export type Doc = {
  id: string;
  filename: string;
  title: string | null;
  status: DocStatus;
  status_detail: string | null;
  page_count: number | null;
  low_text_pages: number[];
  size_bytes: number;
  created_at: string;
  /** While processing: pages read so far. Once set, the first pages can already be used. */
  pages_done?: number | null;
  processing_started_at?: string | null;
};

/** A concept the document teaches, grounded in a quote from the page it's on. */
export type DocConcept = { name: string; page: number; quote: string; chunk_id: string };

export type ChunkT = { id: string; ordinal: number; page_start: number; page_end: number; section: string; text: string };

export type Citation = {
  label: string;
  chunk_id: string;
  document_id: string;
  document_title: string;
  quote: string;
  page_start: number;
  page_end: number;
  section: string;
};

export type AnswerStatus = "verified" | "partial" | "unverified" | "not_found" | "general";
export type AskResult = { answer: string; status: AnswerStatus; citations: Citation[] };
export type Message = { id: string; role: "user" | "assistant"; content: string; status: AnswerStatus | null; citations: Citation[]; created_at: string };

export type Attempt = {
  id: string;
  verdict: "correct" | "partial" | "incorrect" | "unassessed";
  score: number;
  feedback: string;
  missing: string[];
  criteria: { criterion: string; points: number; status: string; evidence: string }[];
  answer_key: string;
  explanation: string;
  correct_index: number | null;
  selected_index: number | null;
  response_text: string | null;
  created_at: string;
};

export type SourceInfo = { chunk_id: string; document_id: string; page_start: number; page_end: number; section: string; document_title: string };

export type QuestionT = {
  id: string;
  position: number;
  qtype: "mcq" | "short" | "applied";
  concept: string;
  difficulty: string;
  prompt: string;
  options: string[];
  sources: SourceInfo[];
  flagged: boolean;
  last_attempt: Attempt | null;
};

export type Quiz = { id: string; title: string; focus: string | null; document_ids: string[]; created_at: string; questions: QuestionT[] };
export type QuizSummary = { id: string; title: string; created_at: string; question_count: number; answered: number; avg_score: number | null };

export type Mastery = {
  concept: string;
  estimate: number;
  level: "unverified" | "weak" | "developing" | "strong";
  evidence_count: number;
  last_assessed_at: string | null;
  due_for_review: boolean;
  explanation: string;
};
export type NextAction = { type: "upload" | "quiz" | "review"; label: string; reason: string; focus?: string };
export type Progress = { concepts: Mastery[]; totals: Record<string, number>; next_action: NextAction };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "mindmesh_token";

export const auth = {
  get token(): string | null {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    window.localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    window.localStorage.removeItem(TOKEN_KEY);
  },
};

export type FlagReason = "wrong_answer" | "unclear" | "not_in_document" | "other";
export const FLAG_REASON_LABEL: Record<FlagReason, string> = {
  wrong_answer: "The marked answer is wrong",
  unclear: "The question is unclear",
  not_in_document: "It isn't in my document",
  other: "Something else",
};
export type FlaggedQuestion = {
  id: string; quiz_id: string; quiz_title: string; prompt: string; concept: string;
  reason: FlagReason; note: string; flagged_at: string | null;
};

/** The current session token: Clerk's short-lived token (refreshed by Clerk), or the local one. */
export async function sessionToken(): Promise<string | null> {
  if (!isClerk) return auth.token;
  try {
    return await getToken();
  } catch {
    return null;  // Clerk not loaded / offline: the API answers 401 and we send the user to sign in
  }
}

/** Authorization header for raw fetches (e.g. file downloads) that don't go through request(). */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await sessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Shared fetch wrapper. Feature clients (api-interview.ts, api-goals.ts) import this. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = await sessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  // "Today" (plan items, practice days, interview countdown) is the user's local date.
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (tz) headers.set("X-Timezone", tz);
  const res = await fetch(`${API_URL}/api${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    auth.clear();
    window.location.href = SIGN_IN_PATH;
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const json = (body: unknown) => JSON.stringify(body);

export const api = {
  signup: (email: string, password: string, display_name = "", report_token?: string) =>
    request<{ token: string; user: User }>("/auth/signup", { method: "POST", body: json({ email, password, display_name, report_token: report_token ?? null }) }),
  login: (email: string, password: string) =>
    request<{ token: string; user: User }>("/auth/login", { method: "POST", body: json({ email, password }) }),
  me: () => request<User>("/auth/me"),
  deleteAccount: () => request<void>("/auth/me", { method: "DELETE" }),

  documents: () => request<Doc[]>("/documents"),
  /** First run: a short sample chapter, so the map, quizzes and answers can be tried before uploading. */
  sampleDocument: () => request<Doc>("/documents/sample", { method: "POST" }),
  document: (id: string) => request<Doc>(`/documents/${id}`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Doc>("/documents?rights_confirmed=true", { method: "POST", body: fd });
  },
  renameDocument: (id: string, title: string) => request<Doc>(`/documents/${id}`, { method: "PATCH", body: json({ title }) }),
  retryDocument: (id: string) => request<Doc>(`/documents/${id}/retry`, { method: "POST" }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  concepts: (id: string) => request<DocConcept[]>(`/documents/${id}/concepts`),
  chunks: (id: string, page?: number) => request<ChunkT[]>(`/documents/${id}/chunks${page ? `?page=${page}` : ""}`),
  fileBlob: async (id: string) => {
    const res = await fetch(`${API_URL}/api/documents/${id}/file`, { headers: await authHeaders() });
    if (!res.ok) throw new ApiError(res.status, "Could not load file");
    return res.blob();
  },

  ask: (question: string, document_ids: string[], level: string, allow_general = false) =>
    request<AskResult>("/tutor/ask", { method: "POST", body: json({ question, document_ids, level, allow_general }) }),
  history: (document_ids: string[]) =>
    request<Message[]>(`/tutor/history?${document_ids.map((d) => `document_ids=${encodeURIComponent(d)}`).join("&")}`),

  createQuiz: (document_ids: string[], count: number, difficulty: string, focus?: string) =>
    request<Quiz>("/quizzes", { method: "POST", body: json({ document_ids, count, difficulty, focus: focus || null }) }),
  quizzes: () => request<QuizSummary[]>("/quizzes"),
  quiz: (id: string) => request<Quiz>(`/quizzes/${id}`),
  deleteQuiz: (id: string) => request<void>(`/quizzes/${id}`, { method: "DELETE" }),
  attempt: (qid: string, body: { answer_text?: string; selected_index?: number; confidence?: number }) =>
    request<Attempt>(`/questions/${qid}/attempts`, { method: "POST", body: json(body) }),
  flag: (qid: string, reason: FlagReason, note = "") =>
    request<void>(`/questions/${qid}/flag`, { method: "POST", body: json({ reason, note }) }),
  unflag: (qid: string) => request<void>(`/questions/${qid}/flag`, { method: "DELETE" }),
  flaggedQuestions: () => request<FlaggedQuestion[]>("/questions/flagged"),

  progress: () => request<Progress>("/progress"),
};
