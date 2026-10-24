"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, json, request } from "@/lib/api";
import { takePendingReport } from "@/lib/auth-mode";

/** After sign-in / sign-up: save a gap report made while signed out, then continue to the app. */
export default function ClaimPage() {
  const router = useRouter();
  const [state, setState] = useState<"saving" | "expired" | "error">("saving");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;  // React strict mode runs effects twice in dev; a token works once
    started.current = true;
    const token = takePendingReport();
    if (!token) {
      router.replace("/");
      return;
    }
    request<{ prep_id: string }>("/public/claim", { method: "POST", body: json({ report_token: token }) })
      .then((r) => router.replace(`/interview/${r.prep_id}`))
      .catch((e: unknown) => setState(e instanceof ApiError && e.status === 404 ? "expired" : "error"));
  }, [router]);

  return (
    <main className="auth-wrap" style={{ flexDirection: "column", gap: "1rem", padding: "2rem 1rem", textAlign: "center" }}>
      {state === "saving" && <p className="row" role="status"><span className="spinner" aria-hidden /> Saving your gap report…</p>}
      {state !== "saving" && (
        <div className="glass card stack-sm" role="alert" style={{ maxWidth: "28rem" }}>
          <h1 style={{ fontSize: "1.25rem", margin: 0 }}>
            {state === "expired" ? "That report has expired" : "We couldn't save your report"}
          </h1>
          <p className="muted small" style={{ margin: 0 }}>
            {state === "expired"
              ? "Reports are kept for 30 minutes. Make a new one; it takes about a minute."
              : "You're signed in. You can make the report again from the welcome page."}
          </p>
          <div className="row" style={{ justifyContent: "center", gap: ".75rem" }}>
            <Link href="/welcome" className="btn">Make a new report</Link>
            <Link href="/" className="btn primary">Go to Today</Link>
          </div>
        </div>
      )}
    </main>
  );
}
