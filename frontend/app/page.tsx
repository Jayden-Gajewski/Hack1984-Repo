import Link from "next/link";
import type { CSSProperties } from "react";
import FilmPlayer from "./components/FilmPlayer";
import ListingCycler from "./components/ListingCycler";
import LogDemo from "./components/LogDemo";
import Logo from "./components/Logo";
import Motion from "./components/Motion";
import Words from "./components/Words";
import { Arrow, Check, Lock } from "./components/icons";

// Landing page. Every person, site and company shown here is fictional sample data.

const HEADLINE = "Find out where your data is exposed. Then take it down.";

const POWERED_BY = [
  { name: "Exa", role: "Finds listings that match you" },
  { name: "Tavily", role: "Searches and reads broker pages" },
  { name: "Wayback Machine", role: "Dates when a listing went public" },
  { name: "Ollama", role: "Runs the analysis on your laptop" },
];

const STEPS = [
  {
    group: "Find it",
    items: [
      {
        title: "Find your listings",
        body: "Exa and Tavily search people-search sites for your name and city. A local model lists what each page shows about you.",
      },
      {
        title: "Date each one",
        body: "The earliest Wayback Machine snapshot shows when a listing went public. With no snapshot, the date says unknown.",
      },
    ],
  },
  {
    group: "Trace it",
    items: [
      {
        title: "Check breaches",
        body: "For the accounts you pick, news reports and state attorney general notices show when each company was breached and what was taken.",
      },
      {
        title: "Read the fine print",
        body: "A local model reads each company's privacy policy and flags clauses that allow selling or sharing your data.",
      },
      {
        title: "Rank likely sources",
        body: "Every lead gets an evidence tier, Proven, Likely or Possible, with the evidence right next to it.",
      },
    ],
  },
  {
    group: "Remove it",
    items: [
      {
        title: "Send opt-outs",
        body: "Dossier finds each site's opt-out page and drafts the request. A re-scan later confirms the listing came down.",
      },
      {
        title: "Use email aliases",
        body: "Give each company its own alias. When someone else writes to that alias, you know whose copy got out.",
      },
    ],
  },
];
const STEP_START = STEPS.map((_, i) => STEPS.slice(0, i).reduce((n, g) => n + g.items.length, 0));

const TIERS = [
  { tier: "proven", label: "Proven", body: "An email alias you gave to one company got mail from someone else." },
  {
    tier: "likely",
    label: "Likely",
    body: "A breach at the company lines up with your listing, in timing and in the data it exposed.",
  },
  { tier: "possible", label: "Possible", body: "The company's privacy policy lets it sell or share your data." },
];

// Stagger index and delay for the scroll reveals in site.css.
const order = (n: number) => ({ "--i": n }) as CSSProperties;
const delay = (ms: number) => ({ "--d": `${ms}ms` }) as CSSProperties;

export default function Landing() {
  return (
    <div className="site">
      <header className="nav-bar">
        <div className="wrap nav">
          <Link href="/" className="brand" aria-label="Dossier home">
            <Logo />
          </Link>
          <nav className="nav-links" aria-label="Sections">
            <a href="#watch">Demo</a>
            <a href="#how">How it works</a>
            <a href="#privacy">Privacy</a>
            <a href="#evidence">Evidence</a>
          </nav>
          <div className="nav-actions">
            <Link href="/login" className="btn btn-ghost btn-sm">
              Log in
            </Link>
            <Link href="/signup" className="btn btn-light btn-sm">
              Sign up <Arrow />
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="wrap hero">
          <div>
            <h1 className="hero-title">
              <Words text={HEADLINE} className="hero-word" />
            </h1>
            <p className="hero-lede">
              Dossier finds you on people-search sites, shows what each listing reveals and which company
              is the likely source, then drafts the opt-out. It runs on your laptop, so you aren&apos;t
              handing your data to one more company.
            </p>
            <div className="hero-ctas">
              <Link href="/signup" className="btn btn-primary btn-lg">
                Start a scan <Arrow />
              </Link>
              <a href="#watch" className="btn btn-ghost btn-lg">
                Watch the 35-second demo
              </a>
            </div>
            <p className="hero-note">
              <Lock /> Every request that leaves your laptop is logged, with its exact contents.
            </p>
          </div>

          <div className="hero-visual">
            <ListingCycler />
            <div className="mock-float">
              <span className="mock-float-icon">
                <Check />
              </span>
              <div>
                <p className="mock-float-title">4 requests left this laptop</p>
                <p className="mock-float-sub">Name and city only. Page text stayed here.</p>
              </div>
            </div>
          </div>
        </section>

        <dl className="wrap credits" aria-label="What powers Dossier" data-reveal="stagger">
          {POWERED_BY.map((p, n) => (
            <div key={p.name} style={order(n)}>
              <dt>{p.name}</dt>
              <dd>{p.role}</dd>
            </div>
          ))}
        </dl>

        <section id="watch" className="film" aria-labelledby="watch-title">
          <div className="wrap">
            <div className="film-head">
              <h2 id="watch-title" className="sec-title" data-reveal="words">
                <Words text="See Dossier in 35 seconds" />
              </h2>
              <p className="sec-lede" data-reveal="fade" style={delay(150)}>
                Find it, trace it, take it down: from a listing with your name on it to an opt-out sent from your
                laptop.
              </p>
            </div>
            <div data-reveal="fade" style={delay(200)}>
              <FilmPlayer />
            </div>
            <p className="film-caption">Sample data: Jordan Avery and every site in the film are fictional. No sound.</p>
          </div>
        </section>

        <section id="how" className="lp-section">
          <div className="wrap">
            <h2 className="sec-title" data-reveal="words">
              <Words text="From your name to a sent opt-out" />
            </h2>
            <p className="sec-lede" data-reveal="fade" style={delay(150)}>
              Seven steps, all started from your laptop. Each one shows you the evidence it found.
            </p>
            <div className="how-grid">
              {STEPS.map((g, gi) => (
                <div className="how-col" key={g.group} data-reveal="col" style={delay(gi * 140)}>
                  <h3 className="how-group">{g.group}</h3>
                  <ol className="how-steps">
                    {g.items.map((s, si) => (
                      <li key={s.title} style={order(si + 1)}>
                        <span className="how-num">{STEP_START[gi] + si + 1}</span>
                        <div>
                          <h4 className="how-step">{s.title}</h4>
                          <p className="how-body">{s.body}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="privacy" className="dark">
          <div className="wrap dark-grid">
            <div>
              <h2 className="sec-title" data-reveal="words">
                <Words text="Here's everything that left this laptop" />
              </h2>
              <p className="sec-lede" data-reveal="fade" style={delay(150)}>
                You shouldn&apos;t have to hand your data to another company to get it removed. Dossier sends
                search services your name and city, nothing else, and shows you the receipt.
              </p>
              <ul className="dark-points" data-reveal="stagger" style={delay(250)}>
                <li style={order(0)}>
                  <Check /> Phone numbers, emails, birthdates and SSNs are blocked before a search is sent.
                </li>
                <li style={order(1)}>
                  <Check /> Pages and privacy policies are read by Ollama on this machine, never by a hosted AI.
                </li>
                <li style={order(2)}>
                  <Check /> Your account and saved scans stay in a database on this laptop.
                </li>
              </ul>
            </div>
            <LogDemo />
          </div>
        </section>

        <section id="evidence" className="lp-section">
          <div className="wrap ev-grid">
            <div>
              <h2 className="sec-title" data-reveal="words">
                <Words text="A likely source, with the evidence attached" />
              </h2>
              <p className="sec-lede" data-reveal="fade" style={delay(150)}>
                Dossier doesn&apos;t guess who&apos;s to blame. Each lead says how strong its evidence is and links
                to it.
              </p>
              <dl className="lp-tiers" data-reveal="stagger" style={delay(250)}>
                {TIERS.map((t, n) => (
                  <div className="lp-tier-row" key={t.tier} style={order(n)}>
                    <dt>
                      <span className={`lp-tier lp-tier-${t.tier}`}>{t.label}</span>
                    </dt>
                    <dd>{t.body}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <figure className="ev-quote" data-reveal="fade" style={delay(200)}>
              <p className="ev-quote-title">Sometimes it wasn&apos;t a hack</p>
              <blockquote>
                “We may <mark className="ev-mark">sell or share your personal information</mark> with marketing
                partners, including data brokers.”
              </blockquote>
              <figcaption>
                Flagged in the privacy policy of ExampleShop, a sample company. A policy that allows selling
                makes it a Possible source.
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="wrap cta">
          <div>
            <h2 className="sec-title" data-reveal="words">
              <Words text="Take your data back." />
            </h2>
            <p className="sec-lede" data-reveal="fade" style={delay(150)}>
              Create an account on this laptop to run your first scan.
            </p>
          </div>
          <div className="hero-ctas" data-reveal="fade" style={delay(250)}>
            <Link href="/signup" className="btn btn-primary btn-glow btn-lg">
              Create account <Arrow />
            </Link>
            <Link href="/login" className="btn btn-ghost btn-lg">
              Log in
            </Link>
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <Logo />
        <p>Sample data on this page is fictional. Jane Example, the .example sites and the Example companies don&apos;t exist.</p>
      </footer>

      <Motion />
    </div>
  );
}
