import Link from "next/link";

/** Centered brand frame around Clerk's sign-in / sign-up cards. */
export default function AuthFrame({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <main className="auth-wrap" style={{ flexDirection: "column", gap: "1.25rem", padding: "2rem 1rem" }}>
      <Link href="/welcome" className="row" style={{ gap: ".5rem", textDecoration: "none", fontWeight: 500 }}>
        <span className="brand-mark" aria-hidden /> Mindmesh
      </Link>
      <h1 className="sr-only">{title}</h1>
      {children}
    </main>
  );
}
