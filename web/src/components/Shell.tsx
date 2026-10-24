"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, auth, type User } from "@/lib/api";
import { isClerk, SIGN_IN_PATH } from "@/lib/auth-mode";
import { AskProvider } from "./AskDock";
import CommandBar from "./CommandBar";
import Icon, { type IconName } from "./Icon";

const UserCtx = createContext<User | null>(null);
export const useUser = () => useContext(UserCtx);

/** Four places (Notebook + Trail, DECISIONS #67): Today is the notebook's cover. Asking lives in the dock on
 *  every screen and in ⌘K, not in a tab. Profile lives under the avatar. */
const NAV: { href: string; label: string; icon: IconName; match: (p: string) => boolean }[] = [
  { href: "/", label: "Today", icon: "today", match: (p) => p === "/" || p.startsWith("/session") || p.startsWith("/progress") },
  { href: "/map", label: "Map", icon: "mesh", match: (p) => p.startsWith("/map") },
  { href: "/library", label: "Library", icon: "library", match: (p) => p.startsWith("/library") || p.startsWith("/documents") || p.startsWith("/quiz") || p.startsWith("/ask") },
  { href: "/prep", label: "Prep", icon: "prep", match: (p) => p.startsWith("/prep") || p.startsWith("/interview") || p.startsWith("/goals") },
];

/** Auth guard, glass top bar on desktop, floating tab bar on phones. */
export default function Shell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    // Clerk mode: proxy.ts already sends signed-out visitors to sign in; here we just load the profile.
    if (!isClerk && !auth.token) {
      router.replace("/about");
      return;
    }
    api.me().then(setUser).catch(() => router.replace(SIGN_IN_PATH));
  }, [router]);

  if (!user) {
    return (
      <div className="auth-wrap muted" role="status">
        <span className="row"><span className="spinner" /> Loading your space…</span>
      </div>
    );
  }

  const initial = (user.display_name || user.email).trim().charAt(0).toUpperCase() || "M";

  return (
    <UserCtx.Provider value={user}>
      <AskProvider dock={!FOCUSED.some((r) => r.test(pathname))}>
      <a href="#main" className="sr-only">Skip to content</a>
      <header className="topbar">
        <Link href="/" className="brand" aria-label="Mindmesh home"><span className="brand-mark" aria-hidden><Icon name="mesh" size={18} /></span><span>mindmesh<span className="brand-dot" aria-hidden>.</span></span></Link>
        <nav className="topnav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={n.match(pathname) ? "page" : undefined}>{n.label}</Link>
          ))}
        </nav>
        <span className="row" style={{ gap: ".6rem", flexWrap: "nowrap" }}>
          <CommandBar />
          <Link href="/settings" className="avatar" aria-label="Profile and settings" title={user.email}>{initial}</Link>
        </span>
      </header>
      <main id="main" className={`container ${wide ? "wide" : ""}`}>{children}</main>
      <nav className="tabbar" aria-label="Main">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} aria-current={n.match(pathname) ? "page" : undefined}>
            <Icon name={n.icon} size={22} />
            {n.label}
          </Link>
        ))}
      </nav>
      </AskProvider>
    </UserCtx.Provider>
  );
}

/** Screens with their own question box or a timed task: no floating dock there. */
const FOCUSED = [/^\/documents\//, /^\/ask/, /^\/session\//, /^\/quiz\//, /\/session\/[^/]+$/];

/** Small back link used at the top of detail screens. */
export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="row small" style={{ gap: ".3rem", textDecoration: "none", color: "var(--ink-2)", marginBottom: ".75rem", display: "inline-flex" }}>
      <Icon name="back" size={16} /> {children}
    </Link>
  );
}
