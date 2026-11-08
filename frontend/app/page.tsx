import { cookies } from "next/headers";
import Link from "next/link";
import FilmPlayer from "./components/FilmPlayer";
import ListingCycler from "./components/ListingCycler";
import LogDemo from "./components/LogDemo";
import Logo from "./components/Logo";
import NavScroll from "./components/NavScroll";
import { Check, Lock } from "./components/icons";

// Landing page. Every person, site and company shown here is fictional sample data.

const HEADLINE = "Find out where your data is exposed. Then take it down.";

const POWERED_BY = [
  { name: "Exa", role: "Finds listings that match you" },
  { name: "Tavily", role: "Searches and reads broker pages" },
  { name: "Wayback Machine", role: "Dates when a listing went public" },
  { name: "Google AI", role: "Reads each page and privacy policy" },
];

const STEPS = [
  {
    group: "Find it",
    items: [
      {
        title: "Find your listings",
        body: "Exa and Tavily search people-search sites for your name and city. An AI model lists what each page shows about you.",
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
        body: "An AI model reads each company's privacy policy and flags clauses that allow selling or sharing your data.",
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

export default async function Landing() {
  // Signed in: the buttons go back to the app instead of to sign-up.
  const signedIn = (await cookies()).has("h84_session");
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
            <Link href="/extension">Browser extension</Link>
          </nav>
          <div className="nav-actions">
            {signedIn ? (
              <Link href="/app" className="btn btn-secondary btn-sm">
                Open Dossier
              </Link>
            ) : (
              <>
                <Link href="/login" className="btn btn-ghost btn-sm">
                  Log in
                </Link>
                <Link href="/signup" className="btn btn-secondary btn-sm">
                  Sign up
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        <section className="wrap hero">
          <div className="hero-copy">
            <h1 className="hero-title">{HEADLINE}</h1>
            <p className="hero-lede">
              Dossier finds you on people-search sites, shows what each listing reveals and which company
              is the likely source, then drafts the opt-out.
            </p>
            <div className="hero-ctas">
              <Link href={signedIn ? "/app" : "/signup"} className="btn btn-primary btn-lg">
                Start a scan
              </Link>
              <a href="#watch" className="btn btn-ghost btn-lg">
                Watch the 35-second demo
              </a>
            </div>
            <p className="hero-note">
              <Lock /> Every request Dossier sends is logged, with its exact contents.
            </p>
          </div>

          <div className="hero-visual">
            <ListingCycler />
            <div className="mock-float">
              <span className="mock-float-icon">
                <Check />
              </span>
              <div>
                <p className="mock-float-title">5 requests sent</p>
                <p className="mock-float-sub">Searches got your name and city only.</p>
              </div>
            </div>
          </div>
        </section>

        <dl className="wrap credits" aria-label="What powers Dossier">
          {POWERED_BY.map((p, n) => (
            <div key={p.name}>
              <dt>{p.name}</dt>
              <dd>{p.role}</dd>
            </div>
          ))}
        </dl>

        <section id="watch" className="film" aria-labelledby="watch-title">
          <div className="wrap">
            <div className="film-head">
              <h2 id="watch-title" className="sec-title">See Dossier in 35 seconds</h2>
              <p className="sec-lede">
                Find it, trace it, take it down: from a listing with your name on it to an opt-out sent from your
                laptop.
              </p>
            </div>
            <div>
              <FilmPlayer />
            </div>
          </div>
        </section>

        <section id="how" className="lp-section">
          <div className="wrap">
            <h2 className="sec-title">From your name to a sent opt-out</h2>
            <p className="sec-lede">
              Seven steps. Each one shows you the evidence it found.
            </p>
            <div className="how-grid">
              {STEPS.map((g, gi) => (
                <div className="how-col" key={g.group}>
                  <h3 className="how-group">{g.group}</h3>
                  <ol className="how-steps">
                    {g.items.map((s, si) => (
                      <li key={s.title}>
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
              <h2 className="sec-title">Here&apos;s everything Dossier sent</h2>
              <p className="sec-lede">
                You shouldn&apos;t have to hand your data to another company to get it removed. Dossier sends
                search services your name and city, nothing else, and shows you the receipt.
              </p>
              <ul className="dark-points">
                <li>
                  <Check /> Phone numbers, emails, birthdates and SSNs are blocked before a search is sent.
                </li>
                <li>
                  <Check /> Pages and privacy policies are read by Google&apos;s AI, and the log shows exactly what it was sent.
                </li>
                <li>
                  <Check /> Your saved scans belong to your account. Nobody else can see them.
                </li>
              </ul>
            </div>
            <LogDemo />
          </div>
        </section>

        <section id="evidence" className="lp-section">
          <div className="wrap ev-grid">
            <div>
              <h2 className="sec-title">A likely source, with the evidence attached</h2>
              <p className="sec-lede">
                Dossier doesn&apos;t guess who&apos;s to blame. Each lead says how strong its evidence is and links
                to it.
              </p>
              <dl className="lp-tiers">
                {TIERS.map((t, n) => (
                  <div className="lp-tier-row" key={t.tier}>
                    <dt>
                      <span className={`lp-tier lp-tier-${t.tier}`}>{t.label}</span>
                    </dt>
                    <dd>{t.body}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <figure className="ev-quote">
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
            <h2 className="sec-title">Take your data back.</h2>
            <p className="sec-lede">
              {signedIn
                ? "You're signed in. Pick up where you left off."
                : "Create an account to run your first scan."}
            </p>
          </div>
          <div className="hero-ctas">
            {signedIn ? (
              <Link href="/app" className="btn btn-primary btn-lg">
                Open Dossier
              </Link>
            ) : (
              <>
                <Link href="/signup" className="btn btn-primary btn-lg">
                  Create account
                </Link>
                <Link href="/login" className="btn btn-ghost btn-lg">
                  Log in
                </Link>
              </>
            )}
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <div className="foot-brand">
          <Logo />
          <p>Every request Dossier sends is logged.</p>
        </div>
        <nav className="foot-nav" aria-label="Footer">
          <a href="#how">How it works</a>
          <a href="#privacy">Privacy</a>
          <a href="#evidence">Evidence</a>
          <Link href="/extension">Browser extension</Link>
          {signedIn ? <Link href="/app">Open Dossier</Link> : <Link href="/login">Log in</Link>}
        </nav>
      </footer>

      <NavScroll />
    </div>
  );
}
