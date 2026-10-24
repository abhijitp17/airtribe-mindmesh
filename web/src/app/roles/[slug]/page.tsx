import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ROLES, roleBySlug } from "@/lib/roles";

export function generateStaticParams() {
  return ROLES.map((r) => ({ slug: r.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const role = roleBySlug((await params).slug);
  if (!role) return {};
  return {
    title: `${role.title} interview prep: skills and a free gap report | Mindmesh`,
    description: `${role.summary} Check your resume against a typical ${role.title} job ad.`,
  };
}

/** A role landing page (P3): what the role asks for, then a gap report with a typical ad pre-filled. */
export default async function RolePage({ params }: { params: Promise<{ slug: string }> }) {
  const role = roleBySlug((await params).slug);
  if (!role) notFound();
  return (
    <div className="container" style={{ maxWidth: 880, paddingBottom: "3rem" }}>
      <header className="row spread" style={{ margin: "1rem 0 2rem" }}>
        <Link href="/welcome" className="brand"><span className="brand-mark" aria-hidden /> Mindmesh</Link>
        <Link href="/roles" className="small" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}>All roles</Link>
      </header>
      <main id="main" className="stack">
        <section className="stack-sm">
          <h1>{role.title} interview prep</h1>
          <p className="muted" style={{ fontSize: "1.05rem", margin: 0 }}>{role.summary}</p>
        </section>

        <section className="glass card stack-sm" aria-labelledby="role-skills-h">
          <h2 id="role-skills-h" style={{ fontSize: "1.25rem", margin: 0 }}>What interviews usually test</h2>
          <ul className="stack-sm" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            {role.skills.map((s) => (
              <li key={s.name}><strong>{s.name}</strong> <span className="muted">· {s.why}</span></li>
            ))}
          </ul>
        </section>

        <section className="glass card stack-sm" aria-labelledby="role-cta-h">
          <h2 id="role-cta-h" style={{ fontSize: "1.25rem", margin: 0 }}>How does your resume compare?</h2>
          <p className="muted" style={{ margin: 0 }}>
            We&apos;ll fill in a typical {role.title} job ad. Add your resume and see the gaps to close first. No account needed.
          </p>
          <Link href={`/welcome?role=${role.slug}`} className="btn primary lg" style={{ alignSelf: "flex-start", minHeight: 52 }}>
            Check my resume against this role
          </Link>
          <p className="small muted" style={{ margin: 0 }}>Applying for a specific job? Paste that ad instead for an exact report.</p>
        </section>
      </main>
    </div>
  );
}
