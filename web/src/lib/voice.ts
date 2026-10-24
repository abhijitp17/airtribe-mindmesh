// Voice mock interviews (P3): browser speech recognition and synthesis, with no extra provider.
// Mindmesh receives only the text the learner chooses to submit. Note for users: in Chrome and Edge
// the browser's speech recognition runs on the vendor's servers; Safari can run it on the device.

const FILLERS = ["um", "uh", "erm", "er", "like", "you know", "sort of", "kind of", "basically", "actually", "i mean"];

export type Delivery = { seconds: number; words: number; wpm: number; fillers: number; topFiller: string | null };

/** Pace and filler words for a spoken answer. */
export function delivery(text: string, seconds: number): Delivery {
  const lower = ` ${text.toLowerCase().replace(/[^a-z' ]+/g, " ").replace(/\s+/g, " ")} `;
  const words = lower.trim() ? lower.trim().split(" ").length : 0;
  const counts = FILLERS.map((f) => [f, lower.split(` ${f} `).length - 1] as const).filter(([, n]) => n > 0);
  counts.sort((a, b) => b[1] - a[1]);
  const fillers = counts.reduce((a, [, n]) => a + n, 0);
  const wpm = seconds > 0 ? Math.round((words / seconds) * 60) : 0;
  return { seconds: Math.round(seconds), words, wpm, fillers, topFiller: counts[0]?.[0] ?? null };
}

/** One plain sentence of coaching on pace and fillers. */
export function deliveryTip(d: Delivery): string {
  const pace = d.wpm === 0 ? "" : d.wpm > 170 ? "a little fast; slow down on the key points" : d.wpm < 110 ? "on the slow side; keep the story moving" : "a comfortable pace";
  const filler = d.fillers === 0 ? "no filler words" : `${d.fillers} filler ${d.fillers === 1 ? "word" : "words"}${d.topFiller ? ` (mostly "${d.topFiller}")` : ""}`;
  const mins = Math.floor(d.seconds / 60);
  const time = mins ? `${mins}m ${d.seconds % 60}s` : `${d.seconds}s`;
  return `You spoke for ${time} at ${d.wpm} words a minute${pace ? `, ${pace}` : ""}, with ${filler}.`;
}

type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  start(): void; stop(): void; abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

export function recognitionAvailable(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export function speechAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function createRecognition(): Recognition | null {
  if (!recognitionAvailable()) return null;
  const w = window as unknown as Record<string, new () => Recognition>;
  const R = w.SpeechRecognition || w.webkitSpeechRecognition;
  const r = new R();
  r.lang = navigator.language || "en-US";
  r.continuous = true;
  r.interimResults = true;
  return r;
}

/** Read text aloud. Never throws: a broken speech engine must not break the interview. */
export function speak(text: string): void {
  if (!speechAvailable()) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    window.speechSynthesis.speak(u);
  } catch {
    /* speech unavailable: the question is on screen */
  }
}

export function stopSpeaking(): void {
  try {
    if (speechAvailable()) window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
}
