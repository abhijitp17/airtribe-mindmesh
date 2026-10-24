import type { Metadata } from "next";
import Link from "next/link";
import { ROLES } from "@/lib/roles";

export const metadata: Metadata = {
  title: "Interview prep by role | Mindmesh",
  description: "What each role usually asks for, and a free gap report against your own resume.",
};

/** Role index (P3 landing pages). Static, public, no account. */
export default function RolesPage() {
  return (
    <div className="container" style={{ maxWidth: 880, paddingBottom: "3rem" }}>
      <header className="row spread" style={{ margin: "1rem 0 2rem" }}>
        <Link href="/welcome" className="brand"><span className="brand-mark" aria-hidden /> Mindmesh</Link>
        <Link href="/login" className="small" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}>Sign in</Link>
      </header>
      <main id="main" className="stack">
        <h1>Prepare for a role</h1>
        <p className="muted" style={{ fontSize: "1.05rem" }}>
          Pick a role to see what interviews usually test, then check your resume against it in about a minute.
        </p>
        <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {ROLES.map((r) => (
            <li key={r.slug}>
              <Link href={`/roles/${r.slug}`} className="glass tile-link" style={{ minHeight: 0 }}>
                <strong>{r.title}</strong>
                <span className="muted small">{r.summary}</span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
