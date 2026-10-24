import type { AnswerStatus, DocStatus, Mastery } from "@/lib/api";

// Mesh badges: colour is always paired with plain words (CONTRACTS §9).
// Classes map to globals.css: gap (orange), warn (peach), good (sage), info (sky), dark (charcoal), "" (white glass).

const DOC_STATUS: Record<DocStatus, [string, string]> = {
  uploaded: ["Waiting to start", "info"],
  processing: ["Processing", "info"],
  ready: ["Ready", "good"],
  needs_attention: ["Couldn't read some pages", "warn"],
  failed: ["Couldn't open this file", "gap"],
};

export function DocStatusBadge({ status }: { status: DocStatus }) {
  const [label, cls] = DOC_STATUS[status];
  const busy = status === "processing" || status === "uploaded";
  return (
    <span className={`badge ${cls}`}>
      {busy && <span className="spinner" aria-hidden style={{ width: 9, height: 9 }} />}
      {label}
    </span>
  );
}

const ANSWER_STATUS: Record<AnswerStatus, [string, string, string]> = {
  verified: ["Checked against your pages", "good", "Every citation was checked against your document."],
  partial: ["Partly checked", "warn", "Some citations couldn't be confirmed, so we removed them."],
  unverified: ["Couldn't check the sources", "gap", "No citation could be confirmed. Treat this answer with caution."],
  not_found: ["Not in your documents", "", "Your selected documents don't cover this."],
  general: ["General knowledge", "info", "Not from your documents. Check it against a trusted source."],
};

export function AnswerStatusBadge({ status }: { status: AnswerStatus }) {
  const [label, cls, title] = ANSWER_STATUS[status];
  return <span className={`badge ${cls}`} title={title}>{label}</span>;
}

const LEVEL: Record<Mastery["level"], [string, string]> = {
  strong: ["Strong", "good"],
  developing: ["Developing", "info"],
  weak: ["Needs work", "gap"],
  unverified: ["Not enough answers yet", ""],
};

export function LevelBadge({ level }: { level: Mastery["level"] }) {
  const [label, cls] = LEVEL[level];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function pages(start: number, end: number) {
  return start === end ? `p. ${start}` : `pp. ${start}–${end}`;
}

export function formatBytes(n: number) {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
