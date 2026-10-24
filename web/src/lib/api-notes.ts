// Notes-first answers (P3): answer from the knowledge base; the AI only when the learner chooses it.
import { json, request } from "./api";

export type NotesMode = "graph" | "reused" | "notes" | "needs_ai" | "not_found" | "ai" | "general";
export type NotesCitation = { label: string; chunk_id: string; document_id: string; quote: string; page_start: number; page_end: number; section?: string };
export type NotesPassage = { chunk_id: string; document_id: string; text: string; page_start: number; page_end: number; section: string };
export type NotesAnswer = {
  mode: NotesMode; answer: string; citations: NotesCitation[]; passages: NotesPassage[];
  reason: string; ai_tokens_estimate: number; status: string | null;
};
export type NotesStats = { days: number; from_notes: number; with_ai: number; tokens_saved_estimate: number; tokens_per_ai_answer: number };

export const notesApi = {
  ask: (question: string, use_ai: "explain" | "general" | null = null) =>
    request<NotesAnswer>("/notes/ask", { method: "POST", body: json({ question, use_ai }) }),
  stats: () => request<NotesStats>("/notes/stats"),
};
