import type { Metadata } from "next";
import Link from "next/link";
import Icon from "@/components/Icon";
import { SIGN_IN_PATH, SIGN_UP_PATH } from "@/lib/auth-mode";
import MenuToggle from "./MenuToggle";
import "./about.css";

// Public front page (P4, DECISIONS #65). Ported from the brand landing page (docs/brand/): knowledge
// first, career as its application. Every picture on it is an example and says so; nothing here is
// live user data, and there is no mailing-list form: the calls to action open real sign-up.

export const metadata: Metadata = {
  title: "Mindmesh: your learning, finally connected",
  description: "Books, papers and courses become a connected map of what you know, and a clearer path to what comes next.",
};

const NAV = [["#how", "How it works"], ["#graph", "Your knowledge map"], ["#career", "Career intelligence"]] as const;

const FAQ: [string, string][] = [
  ["Is Mindmesh just another place to save notes?",
    "It holds your learning material, but the point is what happens between the files. Mindmesh finds the concepts in each source, links them across sources and shows how they build on each other, so your library becomes a picture of what you're learning, not another inbox."],
  ["Who can see my material?",
    "Only you. Your library, map and progress are private to your account. A plan you choose to share is a read-only, expiring link you can revoke."],
  ["Does every question go to an AI?",
    "No. Mindmesh answers from your own notes first and quotes the page it used. It only offers the AI when your notes don't cover a question clearly, and you decide whether to use it."],
  ["How does it connect learning to career readiness?",
    "Your knowledge map is the foundation. For a role you're aiming at, Mindmesh compares what the job asks for with what your material and practice show, then builds interview practice from your own sources."],
  ["Do I need a perfect study system first?",
    "Not at all. Start with a few things you've read or studied. The map grows as you add more and as you practise."],
];

export default function AboutPage() {
  return (
    <div className="lp">
      <a href="#top" className="sr-only">Skip to content</a>
      <header className="lp-wrap lp-head">
        <Link href="/about" className="brand" aria-label="Mindmesh home">
          <span className="brand-mark" aria-hidden><Icon name="mesh" size={18} /></span><span>mindmesh<span className="brand-dot" aria-hidden>.</span></span>
        </Link>
        <nav className="lp-nav" aria-label="Sections">
          {NAV.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
        </nav>
        <div className="lp-head-cta">
          <Link href={SIGN_IN_PATH} className="lp-signin">Sign in</Link>
          <Link href={SIGN_UP_PATH} className="btn primary">Start free <Icon name="next" size={16} /></Link>
        </div>
        <MenuToggle links={[...NAV, [SIGN_IN_PATH, "Sign in"], [SIGN_UP_PATH, "Start free"]]} />
      </header>

      <main id="top">
        <section className="lp-wrap lp-hero">
          <div>
            <p className="lp-pill"><i aria-hidden /> A learning workspace that sees the whole picture</p>
            <h1 className="display lp-h1">Your learning,<br />finally <span className="lp-underline">connected.</span></h1>
            <p className="lp-lead">Books, papers and courses become a living map of what you know, and a clearer path to what comes next.</p>
            <div className="row lp-ctas">
              <Link href={SIGN_UP_PATH} className="btn primary lg">Start your map <Icon name="next" size={17} /></Link>
              <a href="#how" className="lp-link"><span className="lp-play" aria-hidden><Icon name="play" size={12} /></span> See how it works</a>
            </div>
            <p className="lp-note">Free while in early access. Your material stays private to you.</p>
          </div>
          <HeroMock />
        </section>

        <div className="lp-band">
          <div className="lp-wrap lp-band-in">
            <span className="eyebrow">One place for everything you're learning</span>
            <span className="lp-formats">
              <span><Icon name="book" size={15} /> Books &amp; PDFs</span>
              <span><Icon name="library" size={15} /> Papers &amp; Word files</span>
              <span><Icon name="quote" size={15} /> Notes, Markdown &amp; web pages</span>
            </span>
          </div>
        </div>

        <section id="how" className="lp-wrap lp-sec lp-split">
          <div>
            <p className="eyebrow">01 · The shift</p>
            <h2 className="display lp-h2">Less saving.<br /><span className="lp-soft">More seeing.</span></h2>
          </div>
          <div>
            <p className="lp-lead">Learning happens everywhere. The useful connections usually don&apos;t.</p>
            <p className="muted">Mindmesh brings what you study into one workspace, then finds the threads between it. Not another pile of highlights: a picture of how your understanding is taking shape.</p>
            <ol className="lp-steps">
              <li><b className="display">01</b>Bring your learning together</li>
              <li><b className="display">02</b>See ideas become connected</li>
              <li><b className="display lp-coral">03</b>Turn knowledge into momentum</li>
            </ol>
          </div>
        </section>

        <section id="graph" className="lp-dark">
          <div className="lp-wrap lp-sec lp-split lp-split-wide">
            <div className="lp-dark-copy">
              <p className="eyebrow">02 · The knowledge map</p>
              <h2 className="display lp-h2">Your mind isn&apos;t a folder. <span className="lp-warm">It&apos;s a mesh.</span></h2>
              <p>Mindmesh finds the ideas that recur across your reading, so a concept from a paper can light up a lesson from last month. Every link points back to the page it came from.</p>
              <Link href={SIGN_UP_PATH} className="lp-warm-link">Build your map <Icon name="next" size={16} /></Link>
            </div>
            <MeshMock />
          </div>
        </section>

        <section className="lp-wrap lp-sec lp-split">
          <div>
            <p className="eyebrow">03 · From sources to signal</p>
            <h2 className="display lp-h2">The quiet work of <span className="lp-coral">understanding.</span></h2>
            <p className="muted">A useful workspace does more than collect. Mindmesh helps make sense of what you&apos;ve taken in, and what it says about what you can do.</p>
          </div>
          <div className="lp-cards">
            <Feature n="01" icon="upload" tone="mint" title="Bring it all in" body="PDFs, Word files, notes, Markdown and web pages. Your library starts with the material that matters to you." />
            <Feature n="02" icon="mesh" tone="peach" title="Find the throughline" body="Concepts surface across sources, with what each one builds on. Every connection carries the quote that supports it." />
            <Feature n="03" icon="target" tone="gold" title="See your skill signals" body="Quizzes and practice show which ideas you can use, not just which ones you've read." />
            <Feature n="04" icon="prep" tone="sky" title="Make the next move" body="Turn your learning into interview practice, sharper stories and a more confident next step." />
          </div>
        </section>

        <section id="career" className="lp-sand">
          <div className="lp-wrap lp-sec lp-split lp-career">
            <CareerMock />
            <div>
              <p className="eyebrow">04 · The application</p>
              <h2 className="display lp-h2">Make what you know <span className="lp-green">count.</span></h2>
              <p className="muted">A clearer view of your knowledge leads to a clearer story about your strengths. Mindmesh turns your learning into career intelligence, without pretending a number can define you.</p>
              <ul className="lp-checks">
                <li><Icon name="check" size={16} /> Skill signals tied to what you&apos;ve actually studied</li>
                <li><Icon name="check" size={16} /> Interview practice grounded in your own material</li>
                <li><Icon name="check" size={16} /> A gap report for any job ad, before you even sign up</li>
              </ul>
              <Link href="/welcome" className="btn lg">Try a free gap report <Icon name="next" size={16} /></Link>
            </div>
          </div>
        </section>

        <section className="lp-wrap lp-sec lp-split">
          <div>
            <p className="eyebrow">05 · A considered order</p>
            <h2 className="display lp-h2">Start with the learning you have.</h2>
            <p className="muted">Mindmesh is built in two steps: first a home for your knowledge, then a bridge from that knowledge to your career.</p>
          </div>
          <div className="stack">
            <article className="lp-phase">
              <span className="lp-tag">Phase I · The foundation</span>
              <h3 className="display">A personal knowledge system that connects the dots.</h3>
              <p className="muted">Bring in learning materials, build a connected knowledge map, ask questions your notes can answer, and see your understanding grow.</p>
            </article>
            <article className="lp-phase lp-phase-warm">
              <span className="lp-tag">Phase II · The application</span>
              <h3 className="display">A clearer view of your skills, and how to talk about them.</h3>
              <p className="muted">Use your knowledge map for skill gaps, career intelligence and interview readiness that feel specific to you.</p>
            </article>
          </div>
        </section>

        <section className="lp-wrap lp-sec lp-split">
          <div>
            <p className="eyebrow">06 · Questions</p>
            <h2 className="display lp-h2">A little more clarity.</h2>
          </div>
          <div className="lp-faq">
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>{q}<span aria-hidden>+</span></summary>
                <p className="muted">{a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="lp-wrap lp-final-wrap">
          <div className="lp-final">
            <p className="eyebrow">Your learning is already connected to something.</p>
            <h2 className="display">Let&apos;s help you see it.</h2>
            <p>Start with one document. Your map grows from there.</p>
            <div className="row lp-final-ctas">
              <Link href={SIGN_UP_PATH} className="btn lp-coral-btn lg">Start your map <Icon name="next" size={16} /></Link>
              <Link href={SIGN_IN_PATH} className="lp-final-link">I already have an account</Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-wrap lp-foot">
        <span className="brand"><span className="brand-mark" aria-hidden><Icon name="mesh" size={15} /></span><span>mindmesh<span className="brand-dot" aria-hidden>.</span></span></span>
        <span>Scattered learning, made visible.</span>
        <span>© 2026 Mindmesh</span>
      </footer>
    </div>
  );
}

function Feature({ n, icon, tone, title, body }: { n: string; icon: "upload" | "mesh" | "target" | "prep"; tone: string; title: string; body: string }) {
  return (
    <article className="lp-card">
      <div className="spread row"><span className={`lp-ico lp-${tone}`} aria-hidden><Icon name={icon} size={19} /></span><span className="mono tiny lp-num">{n}</span></div>
      <h3 className="display">{title}</h3>
      <p className="muted small">{body}</p>
    </article>
  );
}

/** Illustration: the map with a "thought to keep" side panel (example content, labelled). */
function HeroMock() {
  const around: [number, number, string][] = [[115, 110, "Decision theory"], [142, 270, "Cognitive bias"], [339, 95, "Nudge design"],
    [382, 238, "Product strategy"], [330, 300, "User research"], [83, 205, "Mental models"], [204, 76, "Loss aversion"], [427, 154, "Choice architecture"]];
  return (
    <figure className="lp-mock" aria-label="Example of a Mindmesh knowledge map">
      <div className="lp-mock-bar"><span className="lp-dots" aria-hidden><i /><i /><i /></span><span className="tiny muted">mindmesh / my knowledge</span><span className="mono lp-chip">EXAMPLE</span></div>
      <div className="lp-mock-body">
        <div className="lp-mock-map">
          <p className="tiny muted lp-mock-title"><b>Learning map</b> · 38 concepts</p>
          <svg viewBox="0 0 500 365" role="img" aria-label="Concepts connected around behavioural economics">
            <g stroke="#B8C9B7" strokeWidth="1.3">{around.map(([x, y], i) => <line key={`a${i}`} x1={243} y1={188} x2={x} y2={y} />)}</g>
            {around.map(([x, y, t]) => (
              <g key={t}><circle cx={x} cy={y} r={5} fill="#A8C2A4" /><text x={x} y={y - 10} textAnchor="middle" fontSize="10" fill="#4F5F62">{t}</text></g>
            ))}
            <circle cx={243} cy={188} r={46} fill="#D9E8D5" className="lp-pulse" />
            <circle cx={243} cy={188} r={33} fill="#1C6C5B" />
            <text x={243} y={185} textAnchor="middle" fontSize="10" fontWeight="600" fill="#FFF9EC">behavioural</text>
            <text x={243} y={199} textAnchor="middle" fontSize="10" fontWeight="600" fill="#FFF9EC">economics</text>
          </svg>
          <p className="lp-toast tiny"><i aria-hidden /> New connection found · 2 sources</p>
        </div>
        <aside className="lp-mock-side">
          <p className="small"><Icon name="sparkle" size={14} /> <b>A thought to keep</b></p>
          <p className="small muted">Your notes on <b>choice architecture</b> connect to a pattern in your product strategy course.</p>
          <p className="lp-src tiny"><span className="mono">FROM YOUR LIBRARY</span><br />Thinking, Fast and Slow · p. 181</p>
          <div className="tiny"><span className="spread row"><span className="muted">Skill signal</span><b>Pattern thinking</b></span><div className="meter"><div style={{ width: "72%" }} /></div></div>
        </aside>
      </div>
      <figcaption className="lp-mock-foot tiny"><span>Every idea has a source. Every connection has a reason.</span><span className="mono">01 / YOUR MINDMESH</span></figcaption>
    </figure>
  );
}

function MeshMock() {
  const pts: [number, number, string][] = [[186, 93, "Feedback loops"], [80, 145, "Cognitive science"], [94, 270, "Decision making"], [204, 320, "Product design"],
    [426, 100, "Complexity"], [526, 150, "Research methods"], [490, 281, "Strategy"], [370, 331, "Behavioural econ."], [244, 53, "Emergence"], [186, 220, "Mental models"], [393, 209, "Organisations"]];
  const links = [[0, 1], [1, 2], [2, 3], [4, 5], [5, 6], [6, 7], [0, 8], [8, 4], [1, 9], [9, 2], [3, 9], [4, 10], [10, 5], [10, 6]];
  return (
    <figure className="lp-mesh" aria-label="Example of concepts linked across sources">
      <div className="spread row"><div><span className="mono tiny lp-dim">A growing picture</span><p className="lp-mesh-h">How your ideas meet</p></div><span className="lp-mesh-chip tiny">Example · 38 concepts · 54 links</span></div>
      <svg viewBox="0 0 620 400" role="img" aria-label="Systems thinking at the centre of eleven linked concepts">
        <g stroke="#8FB39B" strokeOpacity=".5" strokeWidth="1.2">
          {pts.map(([x, y], i) => <line key={`c${i}`} x1={303} y1={194} x2={x} y2={y} />)}
          {links.map(([a, b]) => <line key={`${a}-${b}`} x1={pts[a][0]} y1={pts[a][1]} x2={pts[b][0]} y2={pts[b][1]} />)}
        </g>
        {pts.map(([x, y, t]) => <g key={t}><circle cx={x} cy={y} r={5} fill="#C9D7B5" /><text x={x} y={y - 11} textAnchor="middle" fontSize="10" fill="#DCE6DD">{t}</text></g>)}
        <circle cx={303} cy={194} r={39} fill="#E88767" className="lp-pulse" />
        <text x={303} y={191} textAnchor="middle" fontSize="10" fontWeight="700" fill="#243E39">systems</text>
        <text x={303} y={205} textAnchor="middle" fontSize="10" fontWeight="700" fill="#243E39">thinking</text>
      </svg>
      <figcaption className="row tiny lp-legend"><span><i className="lp-k-coral" /> Emerging theme</span><span><i className="lp-k-sage" /> Source-backed idea</span></figcaption>
    </figure>
  );
}

function CareerMock() {
  return (
    <figure className="lp-career-card" aria-label="Example of a career lens for a product analyst role">
      <div className="spread row"><div><span className="mono tiny muted">YOUR CAREER LENS · EXAMPLE</span><p className="display lp-role">Product analyst</p></div><span className="lp-ico lp-mint" aria-hidden><Icon name="arrow" size={17} /></span></div>
      <div className="lp-evidence">
        <p className="spread row small"><b>Your evidence is taking shape</b><span className="mono tiny">3 strengths</span></p>
        {[["Analytical thinking", 75], ["Research synthesis", 61], ["Product judgement", 48]].map(([s, v]) => (
          <div key={s} className="tiny"><span className="spread row"><span>{s}</span><span>{v}%</span></span><div className="meter"><div style={{ width: `${v}%` }} /></div></div>
        ))}
      </div>
      <div className="lp-nextq"><span className="mono tiny muted">A good next question</span><p className="small">Tell me about a time you used research to change a product decision.</p></div>
      <figcaption className="tiny muted lp-center">Signals are a guide to reflection, not a score of your potential.</figcaption>
    </figure>
  );
}
