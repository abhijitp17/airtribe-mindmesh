"use client";

import { useEffect, useState } from "react";
import { interviewApi, type PlanShare } from "@/lib/api-interview";

/** Share the prep plan as a read-only link (P3). The full link is shown once, when created. */
export default function SharePanel({ prepId }: { prepId: string }) {
  const [links, setLinks] = useState<PlanShare[]>([]);
  const [fresh, setFresh] = useState<PlanShare | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    interviewApi.shares(prepId).then(setLinks).catch(() => setLinks([]));
  }, [prepId]);

  async function create() {
    setBusy(true);
    setMsg(null);
    try {
      const s = await interviewApi.createShare(prepId);
      setFresh(s);
      setLinks((xs) => [s, ...xs]);
    } catch (e) {
      setMsg(`We couldn't create a link (${e instanceof Error ? e.message : "unknown error"}).`);
    } finally {
      setBusy(false);
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setMsg("Link copied.");
    } catch {
      setMsg("Select the link and copy it.");
    }
  }

  async function turnOff(id: string) {
    try {
      await interviewApi.revokeShare(prepId, id);
      setLinks((xs) => xs.filter((x) => x.id !== id));
      if (fresh?.id === id) setFresh(null);
      setMsg("Link turned off. Anyone who has it now sees that it isn't available.");
    } catch (e) {
      setMsg(`We couldn't turn it off (${e instanceof Error ? e.message : "unknown error"}).`);
    }
  }

  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return (
    <section className="glass card stack-sm" aria-labelledby="share-h">
      <h2 id="share-h" style={{ fontSize: "1.15rem", margin: 0 }}>Share this plan</h2>
      <p className="muted small" style={{ margin: 0 }}>
        A read-only link for a mentor or friend: the role, the plan and skill priorities. Never your resume,
        documents or answers. Links last 30 days and you can turn them off.
      </p>
      {fresh?.url && (
        <div className="row" style={{ gap: ".5rem", flexWrap: "nowrap" }}>
          <input type="text" readOnly value={fresh.url} aria-label="Share link" onFocus={(e) => e.currentTarget.select()} style={{ flex: 1, minWidth: 0 }} />
          <button type="button" onClick={() => void copy(fresh.url!)} style={{ minHeight: 44, flex: "none" }}>Copy</button>
        </div>
      )}
      <button type="button" onClick={() => void create()} disabled={busy} style={{ minHeight: 44, alignSelf: "flex-start" }}>
        {busy && <span className="spinner" aria-hidden />} {links.length ? "Create another link" : "Create a link"}
      </button>
      {links.length > 0 && (
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {links.map((l) => (
            <li key={l.id} style={{ marginBottom: ".3rem" }}>
              Created {day(l.created_at)} · expires {day(l.expires_at)} · {l.views} {l.views === 1 ? "view" : "views"}{" "}
              <button type="button" className="ghost small" onClick={() => void turnOff(l.id)} style={{ minHeight: 44 }}
                      aria-label={`Turn off the link created ${day(l.created_at)}`}>Turn off</button>
            </li>
          ))}
        </ul>
      )}
      <p role="status" className="small muted" style={{ margin: 0 }}>{msg ?? ""}</p>
    </section>
  );
}
