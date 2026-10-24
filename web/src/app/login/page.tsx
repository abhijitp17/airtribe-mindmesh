"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { api, auth, json, request, type User } from "@/lib/api";
import { isClerk, rememberReport } from "@/lib/auth-mode";

type Mode = "login" | "signup";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="auth-wrap muted" role="status"><span className="row"><span className="spinner" /> Loading…</span></div>}>
      <LoginView />
    </Suspense>
  );
}

function LoginView() {
  const router = useRouter();
  const params = useSearchParams();
  const reportToken = params.get("report");

  // With Clerk, sign-in lives at /sign-in and /sign-up; carry a waiting gap report across.
  useEffect(() => {
    if (!isClerk) return;
    if (reportToken) rememberReport(reportToken);
    router.replace(params.get("mode") === "signup" || reportToken ? "/sign-up" : "/sign-in");
  }, [params, reportToken, router]);
  const [mode, setMode] = useState<Mode>(params.get("mode") === "signup" || reportToken ? "signup" : "login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const headRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headRef.current?.focus();
  }, [mode]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res =
        mode === "login"
          ? await api.login(email, password)
          : // api.signup doesn't take report_token yet (CONTRACTS §7), so call request directly with the same shape.
            await request<{ token: string; user: User }>("/auth/signup", {
              method: "POST",
              body: json({ email, password, display_name: name.trim(), ...(reportToken ? { report_token: reportToken } : {}) }),
            });
      auth.set(res.token);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Something went wrong. Check your connection and try again.");
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(mode === "login" ? "signup" : "login");
    setError(null);
  }

  const signup = mode === "signup";

  return (
    <div className="auth-wrap">
      <main className="glass card auth-card stack" style={{ padding: "1.6rem 1.5rem" }}>
        <div className="stack-sm">
          <Link href="/welcome" className="brand" style={{ fontSize: "1.3rem" }}><span className="brand-mark" aria-hidden /> Mindmesh</Link>
          <h1 ref={headRef} tabIndex={-1} style={{ fontSize: "1.6rem", marginTop: ".75rem" }}>
            {signup ? "Create your account" : "Welcome back"}
          </h1>
          <p className="muted small" style={{ margin: 0 }}>
            {signup
              ? "A short plan for each day, built from your own resume, job and notes."
              : "Pick up where you left off."}
          </p>
        </div>

        {reportToken && signup && (
          <div className="notice good small row" role="status" style={{ gap: ".5rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
            <span aria-hidden style={{ marginTop: 2 }}><Icon name="check" size={16} /></span>
            <span>Your gap report will be saved to your account.</span>
          </div>
        )}

        <form onSubmit={submit} className="stack">
          {signup && (
            <div>
              <label htmlFor="today-name">Your first name <span>(optional)</span></label>
              <input id="today-name" type="text" autoComplete="given-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          )}
          <div>
            <label htmlFor="today-email">Email</label>
            <input id="today-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="today-password">Password {signup && <span>(8 or more characters)</span>}</label>
            <input
              id="today-password"
              type="password"
              autoComplete={signup ? "new-password" : "current-password"}
              required
              minLength={signup ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <div className="notice bad" role="alert">{error}</div>}
          <button className="primary lg block" type="submit" disabled={busy} style={{ minHeight: 52 }}>
            {busy && <span className="spinner" aria-hidden />} {signup ? "Create account" : "Sign in"}
          </button>
        </form>

        <p className="small muted" style={{ margin: 0 }}>
          {signup ? "Have an account? " : "New here? "}
          <button type="button" className="ghost small" style={{ padding: "0 .25rem", minHeight: 44, textDecoration: "underline" }} onClick={switchMode}>
            {signup ? "Sign in" : "Create an account"}
          </button>
        </p>
        {!signup && (
          <p className="small muted" style={{ margin: 0 }}>
            Preparing for an interview? <Link href="/welcome">Try a free gap report first</Link>
          </p>
        )}
        <p className="tiny muted" style={{ margin: 0 }}>Your documents are private to your account and are not used to train AI models.</p>
      </main>
    </div>
  );
}
