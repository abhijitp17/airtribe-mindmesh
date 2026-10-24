/**
 * Scoped Mesh helpers for the Prep area (interview + goals screens).
 * globals.css is read-only, so anything extra lives here with a `prep-` prefix.
 * Render <PrepStyles /> once near the root of a screen (duplicates are harmless).
 */
const CSS = `
.prep-root button, .prep-root .btn, .prep-root select { min-height: 44px; }
.prep-sub { color: var(--ink-2); margin: .35rem 0 0; }
.prep-kicker { font-size: .84rem; color: var(--ink-2); }
.prep-name { display: block; font-weight: 500; font-size: 1.06rem; line-height: 1.25; color: var(--ink); }
.prep-title-xl { font-size: clamp(1.6rem, 1.1rem + 2vw, 2.3rem); font-weight: 500; margin: 0; }
.prep-chip { display: inline-flex; align-items: center; gap: .35rem; padding: .45rem .9rem; border-radius: var(--r-pill);
  background: var(--glass-strong); border: 1px solid var(--glass-edge); font-size: .92rem; color: var(--ink); white-space: nowrap; }
.prep-chip b { font-weight: 600; }
.prep-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.prep-chips button { border-radius: var(--r-pill); background: rgba(255,255,255,0.55); font-size: .9rem; padding: .5rem .95rem; }
.prep-chips button[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: #fff; }
.prep-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; list-style: none; padding: 0; margin: 0; }
@media (max-width: 720px) { .prep-grid { grid-template-columns: minmax(0, 1fr); } }
.prep-skill { border-radius: var(--r-lg); border: 1px solid var(--glass-edge); box-shadow: var(--shadow); overflow: hidden;
  display: flex; flex-direction: column; -webkit-backdrop-filter: blur(var(--blur)); backdrop-filter: blur(var(--blur)); }
.prep-skill.plain { background: var(--glass); }
.prep-skill.open { grid-column: 1 / -1; }
.prep-skill-btn { display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; gap: .45rem; width: 100%; flex: 1;
  text-align: left; padding: 1.1rem 1.15rem; border: 0; border-radius: 0; background: transparent; font-weight: 400; }
.prep-skill-btn:hover:not(:disabled) { background: rgba(255,255,255,0.35); }
.prep-skill-btn:active:not(:disabled) { transform: none; }
.prep-why { color: var(--ink-2); font-size: .93rem; }
.prep-quote { display: block; margin: .1rem 0; padding-left: .7rem; border-left: 2px solid rgba(29,51,56,0.18); font-size: .93rem; }
.prep-next { display: flex; align-items: center; justify-content: space-between; gap: .75rem; margin-top: auto; padding-top: .5rem; font-weight: 500; }
.prep-arrow { transition: transform .15s ease; }
.prep-skill.open .prep-arrow { transform: rotate(90deg); }
.prep-panel { border-top: 1px solid var(--line); padding: 1.1rem 1.15rem 1.25rem; background: rgba(255,255,255,0.55); }
.prep-sec-h { font-size: 1rem; font-weight: 500; margin: 0 0 .4rem; }
.prep-dims { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: .75rem; }
.prep-dim { padding: .95rem 1rem; display: flex; flex-direction: column; gap: .4rem; }
.prep-items { list-style: none; padding: 0; margin: 0; display: grid; gap: .55rem; }
.prep-item { background: rgba(255,255,255,0.62); border: 1px solid var(--glass-edge); border-radius: var(--r-md); padding: .8rem .95rem;
  display: flex; gap: .75rem; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; }
.prep-item.dim { opacity: .68; }
.prep-followup { margin-left: 1.25rem; padding-left: 1rem; border-left: 1.5px solid rgba(29,51,56,0.22); }
@media (max-width: 480px) { .prep-followup { margin-left: .4rem; padding-left: .75rem; } }
.prep-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; }
@media (max-width: 560px) { .prep-stats { grid-template-columns: minmax(0, 1fr); } }
.prep-stat { padding: .85rem 1rem; border-radius: var(--r-md); background: rgba(255,255,255,0.6); border: 1px solid var(--glass-edge); }
.prep-stat-v { display: block; font-size: 1.3rem; font-weight: 500; line-height: 1.2; }
.prep-list { list-style: none; padding: 0; margin: 0; display: grid; gap: .75rem; }
.prep-q { font-size: 1.14rem; font-weight: 500; line-height: 1.35; margin: 0; }
.prep-steps { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.prep-steps li { display: flex; flex-direction: column; gap: .35rem; font-size: .84rem; color: var(--ink-2); }
.prep-steps li span.bar { height: 6px; border-radius: 4px; background: rgba(29,51,56,0.1); }
.prep-steps li.done span.bar, .prep-steps li[aria-current="step"] span.bar { background: var(--ink); }
.prep-steps li[aria-current="step"] { color: var(--ink); font-weight: 500; }
.prep-tile-meta { color: var(--ink-2); font-size: .9rem; }
.prep-section-h { display: flex; justify-content: space-between; align-items: baseline; gap: .75rem; flex-wrap: wrap; margin: 0 0 .75rem; }
.prep-section-h h2 { margin: 0; }
`;

export default function PrepStyles() {
  return <style>{CSS}</style>;
}
