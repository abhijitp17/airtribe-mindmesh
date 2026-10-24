"use client";

import Link from "next/link";
import Icon from "@/components/Icon";
import type { Countdown } from "@/lib/api-engagement";
import type { Journey } from "@/lib/api-journey";
import { daysLeftPhrase } from "./labels";

/** The notebook cover (Notebook + Trail, DECISIONS #67): your name and goal, one "continue" ribbon,
 *  a handwritten next step, goal bookmarks along the top edge, and the trail. The trail shows progress
 *  only: every stop is a link, nothing is locked. */
const COVER_CSS = `
  .cover { position: relative; margin-top: 1.4rem; margin-bottom: 1.25rem; border-radius: 10px var(--r-xl) var(--r-xl) 10px;
    background: linear-gradient(90deg, rgba(25,77,67,.08) 0, rgba(25,77,67,0) 14px), var(--glass-strong);
    border: 1px solid var(--glass-edge); border-left: 6px solid var(--green); box-shadow: 0 18px 44px rgba(55,65,52,.10); }
  .cover-tabs { position: absolute; top: 0; right: 1.4rem; transform: translateY(-100%); display: flex; gap: .3rem; max-width: calc(100% - 3rem); overflow-x: auto; }
  .cover-tabs a { flex: none; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: .35rem .75rem .3rem; border-radius: 10px 10px 0 0;
    font-size: .78rem; font-weight: 600; text-decoration: none; background: var(--peach); color: var(--ink); border: 1px solid var(--glass-edge); border-bottom: 0; }
  .cover-tabs a[aria-current="true"] { background: var(--green); color: var(--on-green); border-color: var(--green); }
  .cover-tabs a.add { background: var(--paper-2); color: var(--ink-2); }
  .cover-main { display: grid; gap: 1.25rem; padding: 1.5rem 1.4rem 1.2rem; }
  @media (min-width: 860px) { .cover-main { grid-template-columns: minmax(0, 1fr) 270px; align-items: center; padding: 1.9rem 2rem 1.4rem; } }
  .cover h1 { font-size: clamp(1.6rem, 1.1rem + 2vw, 2.35rem); margin: .35rem 0 .2rem; }
  .ribbon { display: inline-flex; align-items: center; gap: .9rem; margin-top: 1rem; padding: .75rem 1.2rem .75rem .95rem; border-radius: 4px var(--r-md) var(--r-md) 4px;
    background: var(--green); color: var(--on-green); text-decoration: none; position: relative; box-shadow: 0 10px 24px rgba(25,77,67,.22); max-width: 100%; }
  .ribbon::before { content: ""; position: absolute; left: -6px; top: 6px; bottom: 6px; width: 6px; background: var(--coral); border-radius: 3px 0 0 3px; }
  .ribbon:hover { background: var(--green-press); }
  .ribbon small { display: block; opacity: .85; font-size: .78rem; }
  .ribbon b { display: block; font-size: 1.02rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ribbon svg.icon { stroke: var(--on-green); flex: none; }
  .note { position: relative; padding: 1rem 1.1rem 1.1rem; background: #FBF3D9; border: 1px solid #EBDDB0; border-radius: 4px 4px 14px 4px; transform: rotate(-1.2deg);
    box-shadow: 0 8px 18px rgba(90,80,40,.10); }
  .note::before { content: ""; position: absolute; top: -9px; left: 50%; width: 64px; height: 18px; margin-left: -32px; background: rgba(197,213,189,.75); transform: rotate(2deg); }
  .note p { margin: .2rem 0 0; font-family: var(--hand); font-size: 1.45rem; line-height: 1.2; color: #3B3A2C; }
  .trail { list-style: none; margin: 0; padding: 1rem 1.4rem 1.3rem; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .5rem; border-top: 1px dashed #D9D5CA; }
  @media (min-width: 860px) { .trail { padding: 1.1rem 2rem 1.5rem; } }
  .trail li { position: relative; min-width: 0; }
  .trail li + li::before { content: ""; position: absolute; top: 15px; right: calc(50% + 20px); width: calc(100% - 40px + .5rem); height: 2px; background: #D9D5CA; }
  .trail li.done + li::before { background: var(--green-hi); }
  .trail a { display: grid; justify-items: center; text-align: center; gap: .2rem; text-decoration: none; color: var(--ink); padding: 0 .2rem .2rem; border-radius: var(--r-sm); }
  .trail .dot { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; font-size: .85rem; background: var(--solid); border: 2px solid #CFCAB9; color: var(--ink-2); position: relative; z-index: 1; }
  .trail li.done .dot { background: var(--green-hi); border-color: var(--green-hi); color: var(--on-green); }
  .trail li.done .dot svg.icon { stroke: var(--on-green); }
  .trail li.here .dot { border-color: var(--coral); box-shadow: 0 0 0 5px rgba(231,131,99,.22); color: var(--ink); }
  .trail .lbl { font-weight: 600; font-size: .92rem; }
  .trail .det { font-size: .76rem; color: var(--ink-2); line-height: 1.3; }
  .trail .here-tag { font-family: var(--mono); font-size: .62rem; text-transform: uppercase; letter-spacing: .08em; color: var(--coral-text); }
  @media (max-width: 560px) { .trail .det { display: none; } .trail .lbl { font-size: .8rem; } }
`;

export default function Cover({ name, journey, countdown }: { name: string; journey: Journey; countdown: Countdown }) {
  const active = journey.goals.find((g) => g.kind === "interview" && g.id === countdown?.prep_id) ?? journey.goals[0] ?? null;
  const title = countdown ? `${countdown.role_title}${countdown.company ? ` at ${countdown.company}` : ""}` : active ? active.title : "Your learning, connected";
  const owner = name ? `${name}${name.endsWith("s") ? "’" : "’s"} notebook` : "Your notebook";
  const resume = journey.resume;

  return (
    <section className="cover" aria-labelledby="cover-title">
      <style>{COVER_CSS}</style>
      {journey.goals.length > 0 && (
        <nav className="cover-tabs" aria-label="Your goals">
          {journey.goals.map((g) => (
            <Link key={g.id} href={g.href} aria-current={g.id === active?.id ? "true" : undefined} title={g.subtitle ? `${g.title} · ${g.subtitle}` : g.title}>{g.title}</Link>
          ))}
          <Link href="/prep" className="add" aria-label="Add a goal">+ Goal</Link>
        </nav>
      )}
      <div className="cover-main">
        <div style={{ minWidth: 0 }}>
          <p className="eyebrow" style={{ margin: 0 }}>{owner}</p>
          <h1 id="cover-title" className="display">{title}</h1>
          {countdown && <p className="muted" style={{ margin: 0 }}>Interview {daysLeftPhrase(countdown.days_left)}</p>}
          {resume ? (
            <Link href={resume.href} className="ribbon">
              <Icon name="book" size={20} />
              <span style={{ minWidth: 0 }}><small>Continue where you left off</small><b>{resume.title}</b></span>
              <Icon name="next" size={18} />
            </Link>
          ) : (
            <a href="#session" className="ribbon">
              <Icon name="book" size={20} />
              <span><small>Start here</small><b>Today&apos;s session</b></span>
              <Icon name="next" size={18} />
            </a>
          )}
        </div>
        <aside className="note" aria-label="Your next step">
          <span className="eyebrow">Next step</span>
          <p>{journey.next_note}</p>
        </aside>
      </div>
      <ol className="trail" aria-label="Your trail">
        {journey.stages.map((s, i) => {
          const here = s.key === journey.current;
          return (
            <li key={s.key} className={`${s.done ? "done" : ""} ${here ? "here" : ""}`}>
              <Link href={s.href} aria-label={`${s.label}: ${s.done ? "done" : here ? "you are here" : "not yet"}. ${s.detail}`}>
                <span className="dot" aria-hidden>{s.done ? <Icon name="check" size={16} /> : i + 1}</span>
                <span className="lbl">{s.label}</span>
                {here && <span className="here-tag" aria-hidden>You are here</span>}
                <span className="det">{s.detail}</span>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
