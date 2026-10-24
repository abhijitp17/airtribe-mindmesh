// Typed client for the Mindmesh API (same endpoints as the web app). The token lives in the
// device's secure storage (Keychain / Keystore); on the web build, in localStorage.
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

// Simulators reach your Mac at localhost; an Android emulator at 10.0.2.2; a phone needs your Mac's LAN IP.
export const API_URL = (process.env.EXPO_PUBLIC_API_URL || "http://localhost:8300").replace(/\/$/, "");
export const WEB_URL = (process.env.EXPO_PUBLIC_WEB_URL || "http://localhost:3300").replace(/\/$/, "");
const KEY = "mindmesh_token";

export const tokenStore = {
  async get(): Promise<string | null> {
    if (Platform.OS === "web") return globalThis.localStorage?.getItem(KEY) ?? null;
    return SecureStore.getItemAsync(KEY);
  },
  async set(token: string | null): Promise<void> {
    if (Platform.OS === "web") {
      if (token) globalThis.localStorage?.setItem(KEY, token);
      else globalThis.localStorage?.removeItem(KEY);
      return;
    }
    if (token) await SecureStore.setItemAsync(KEY, token);
    else await SecureStore.deleteItemAsync(KEY);
  },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn; };

export async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = await tokenStore.get();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api${path}`, {
      method: init.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Can't reach Mindmesh. Check your connection and try again.");
  }
  if (res.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Please sign in again.");
  }
  if (!res.ok) {
    let msg = `Something went wrong (${res.status}). Try again.`;
    try {
      const b = await res.json();
      if (typeof b?.detail === "string") msg = b.detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

// ---- types (subset of the web client's) ----
export type User = { id: string; email: string; display_name: string };
export type Step = { id: string; kind: string; title: string; detail: string; minutes: number; status: string;
  target: { type: string; href?: string; document_ids?: string[]; focus?: string | null } };
export type TodayPreview = { greeting_name: string; suggestions: Record<"5" | "15" | "30", Step[]> };
export type Week = { target: number; done: number; days: { date: string; practised: boolean; is_today: boolean }[] };
export type StudySession = { id: string; minutes: number; status: string; steps: Step[] };
export type Doc = { id: string; title: string | null; filename: string; status: string; page_count: number | null; pages_done?: number | null };
export type PrepSummary = { id: string; role_title: string; company: string | null; interview_date: string | null; critical_gaps: number };
export type Prefs = { reminders: boolean; default_minutes: number; weekly_target: number };
export type NotesAnswer = { mode: string; answer: string; reason: string; ai_tokens_estimate: number;
  citations: { label: string; page_start: number; document_id: string; quote: string }[];
  passages: { chunk_id: string; text: string; page_start: number; document_id: string }[] };
export type NotesStats = { from_notes: number; with_ai: number; tokens_saved_estimate: number; tokens_per_ai_answer: number };

export const api = {
  login: (email: string, password: string) => request<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } }),
  signup: (email: string, password: string) => request<{ token: string; user: User }>("/auth/signup", { method: "POST", body: { email, password } }),
  me: () => request<User>("/auth/me"),
  today: () => request<TodayPreview>("/today/preview"),
  week: () => request<Week>("/week"),
  startSession: (minutes: 5 | 15 | 30) => request<StudySession>("/sessions/study", { method: "POST", body: { minutes } }),
  setStep: (sid: string, stepId: string, status: "done" | "skipped") =>
    request<StudySession>(`/sessions/study/${sid}/steps/${stepId}`, { method: "PATCH", body: { status } }),
  completeSession: (sid: string) => request<StudySession>(`/sessions/study/${sid}/complete`, { method: "POST" }),
  documents: () => request<Doc[]>("/documents"),
  preps: () => request<PrepSummary[]>("/interview/preps"),
  prefs: () => request<Prefs>("/me/prefs"),
  setPrefs: (body: Partial<Prefs>) => request<Prefs>("/me/prefs", { method: "PATCH", body }),
  ask: (question: string, use_ai: "explain" | "general" | null = null) =>
    request<NotesAnswer>("/notes/ask", { method: "POST", body: { question, use_ai } }),
  notesStats: () => request<NotesStats>("/notes/stats"),
  registerPush: (token: string, platform: "ios" | "android") => request<void>("/me/push-tokens", { method: "POST", body: { token, platform } }),
  removePush: (token: string, platform: "ios" | "android") => request<void>("/me/push-tokens", { method: "DELETE", body: { token, platform } }),
};
