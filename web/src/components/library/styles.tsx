/** Library-only styles (lib- prefix), kept out of globals.css per CONTRACTS §10. */
export default function LibStyles() {
  return (
    <style>{`
.lib-grid { list-style: none; padding: 0; margin: 0; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
.lib-card { position: relative; display: flex; flex-direction: column; padding: 0; }
.lib-card > .tile-link { flex: 1; }
.lib-title { overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.lib-foot { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .4rem .6rem .6rem 1rem; border-top: 1px solid var(--line); }
.lib-more { width: 44px; height: 44px; }
.lib-menu { position: absolute; right: .6rem; bottom: 3.6rem; z-index: 6; width: min(280px, calc(100% - 1.2rem)); padding: .6rem;
  border-radius: var(--r-md); background: var(--solid); border: 1px solid var(--line); box-shadow: 0 12px 30px rgba(40,60,50,0.16); }
.lib-quiz { display: flex; align-items: center; gap: .75rem; padding: .75rem .9rem; min-height: 64px; text-decoration: none; color: var(--ink); }
.lib-quiz + .lib-quiz { margin-top: .5rem; }
.lib-chip { border-radius: var(--r-pill); min-height: 44px; background: var(--glass-strong); }
.lib-composer { display: flex; flex-direction: column; gap: .5rem; padding: .6rem; margin: .75rem; border-radius: 20px; }
.lib-composer textarea { border: 0; background: transparent; box-shadow: none; min-height: 52px; padding: .45rem .55rem; }
.lib-composer textarea:focus { box-shadow: none; }
.lib-composer:focus-within { box-shadow: 0 0 0 2px var(--green); }
.lib-ws-switch { display: none; }
@media (max-width: 960px) {
  .lib-ws-switch { display: flex; position: sticky; top: 3.7rem; z-index: 8; padding: 4px; border-radius: var(--r-pill); }
  .lib-ws-switch button { min-height: 44px; border-radius: var(--r-pill); }
  .lib-pane-hidden { display: none !important; }
  .lib-ws .pane { min-height: 70vh; }
}
.lib-qbar { position: sticky; top: 3.7rem; z-index: 8; padding: .65rem .9rem; border-radius: var(--r-lg); }
.lib-dots { display: flex; gap: 6px; flex-wrap: wrap; }
.lib-dots button { width: 44px; height: 44px; padding: 0; border-radius: 50%; font-size: .85rem; }
.lib-dots button[aria-current="step"] { background: var(--ink); border-color: var(--ink); color: #fff; }
.lib-dots button.done { box-shadow: inset 0 0 0 2px var(--sage); }
.lib-qcard { padding: 1.3rem; border-radius: var(--r-xl); }
.lib-qcard .option { min-height: 56px; align-items: center; font-size: 1rem; }
.lib-qcard .option input { width: 20px; height: 20px; flex: none; }
.lib-conf button { min-width: 44px; min-height: 44px; }
.lib-conf button[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: #fff; }
.lib-switch { position: relative; display: inline-block; width: 52px; height: 32px; border-radius: var(--r-pill); flex: none; background: rgba(29,51,56,0.18); transition: background-color .15s ease; }
.lib-switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 26px; height: 26px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.2); transition: left .15s ease; }
.lib-switch[data-on="true"] { background: var(--ink); }
.lib-switch[data-on="true"]::after { left: 23px; }
`}</style>
  );
}
