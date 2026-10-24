"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Study goals now live in the Prep hub. Keep the old link working. */
export default function GoalsIndexRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/prep");
  }, [router]);
  return (
    <div className="auth-wrap muted" role="status">
      <span className="row"><span className="spinner" /> Opening Prep…</span>
    </div>
  );
}
