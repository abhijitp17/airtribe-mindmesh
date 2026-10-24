// Notebook cover (P4): GET /api/me/journey, the trail and where you left off.
import { request } from "./api";

export type StageKey = "learn" | "practise" | "prove" | "interview";
export type Stage = { key: StageKey; label: string; done: boolean; detail: string; href: string };
export type Resume = { kind: "interview" | "session" | "quiz" | "document"; title: string; href: string } | null;
export type Bookmark = { kind: "interview" | "goal"; id: string; title: string; subtitle: string; date: string | null; href: string };
export type Journey = { stages: Stage[]; current: StageKey | null; next_note: string; resume: Resume; goals: Bookmark[] };

export const journeyApi = { get: () => request<Journey>("/me/journey") };
