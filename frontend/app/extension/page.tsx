import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import ExtensionDownload, { CopyText } from "../components/ExtensionDownload";
import Logo from "../components/Logo";
import NavScroll from "../components/NavScroll";
import { Check, Lock } from "../components/icons";
import "./extension.css";

// The browser extension's page. Public; the download itself needs a signed-in account during the
// beta. ShopCo, in the screenshot and the sample receipt, is a fictional store.

export const metadata: Metadata = {
  title: "Browser extension",
  description:
    "See what every site's privacy policy allows, which trackers it loads and what its forms ask for.",
};

const SHOWS = [
  {
    title: "A verdict on every site",
    body: "A badge in your toolbar marks sites with real concerns. Finding nothing isn't proof a site is safe, so there's no green light.",
  },
  {
    title: "What the policy allows",
    body: "What the site says it collects, and whether it sells or shares it, with the exact sentence from its policy.",
  },
  {
    title: "Who's watching",
    body: "Ad trackers, session-recording tools and data brokers the page loaded, each with the address it came from.",
  },
  {
    title: "What a form asks for",
    body: "Card numbers, Social Security numbers and passwords, and whether they'd be sent without encryption.",
  },
  {
    title: "People-search sites",
    body: "A warning on sites that publish profiles of people, with a link to scan yourself and the site's own opt-out page.",
  },
  {
    title: "Who sells its ads",
    body: "How many ad companies the site's ads.txt lets sell its ad space, and the names it lists most.",
  },
];

const GUARANTEES = [
  "It never reads what you type. Form fields are judged by their labels.",
  "Trackers are matched by hostname. The rest of a tracker's address, where account IDs hide, is dropped.",
  "Checking each site you visit contacts no site. Opening the popup reads that site's own policy and ads.txt, and logs each request.",
  "Nothing goes to a search engine or a Dossier server. Opening the popup sends the policy's selling and sharing sentences to Google's Gemini, and that's logged too.",
];

const RECEIPT = [
  { service: "Website", local: false, method: "GET", url: "shopco.example/legal/privacy", note: "No cookies sent. Read straight from the site.", status: "200" },
  { service: "Website", local: false, method: "GET", url: "shopco.example/ads.txt", note: "Who may sell its ads.", status: "200" },
  { service: "Gemini", local: false, method: "POST", url: "generativelanguage.googleapis.com/…:generateContent", note: "Policy sentences, read by Google's Gemini.", status: "200" },
];

export default function ExtensionPage() {
  return (
    <div className="site">
      <header className="nav-bar">
        <div className="wrap nav">
          <Link href="/" className="brand" aria-label="Dossier home">
            <Logo />
          </Link>
          <nav className="nav-links" aria-label="Sections">
            <a href="#shows">What it shows</a>
            <a href="#install">Install</a>
            <a href="#privacy">Privacy</a>
          </nav>
          <div className="nav-actions">
            <Link href="/login?next=/extension" className="btn btn-ghost btn-sm">
              Log in
            </Link>
            <Link href="/signup?next=/extension" className="btn btn-secondary btn-sm">
              Sign up
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="wrap hero">
          <div className="hero-copy">
            <h1 className="hero-title">A privacy check on every site you visit</h1>
            <p className="hero-lede">
              Dossier for Chrome and Edge shows what a site&apos;s privacy policy allows, which trackers the page
              loads and what its forms ask for. It never reads what you type.
            </p>
            <ExtensionDownload>
              <a href="#install" className="btn btn-ghost btn-lg">
                How to install
              </a>
            </ExtensionDownload>
            <p className="hero-note">
              <Lock /> Free beta. It works while Dossier runs on this computer.
            </p>
          </div>

          <figure className="hero-visual ext-shot">
            <div className="ext-window">
              <div className="ext-bar" aria-hidden>
                <span className="ext-dots">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="ext-url">shopco.example/legal/privacy</span>
                <span className="ext-icon">
                  <svg width="18" height="18" viewBox="0 0 26 26">
                    <path
                      d="M3 8a2.5 2.5 0 0 1 2.5-2.5h4.6l2.2 2.5h8.2A2.5 2.5 0 0 1 23 10.5v8A2.5 2.5 0 0 1 20.5 21h-15A2.5 2.5 0 0 1 3 18.5Z"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinejoin="round"
                    />
                    <circle cx="13" cy="13.4" r="1.9" fill="currentColor" />
                    <path d="M12.2 14.6h1.6l.5 2.8h-2.6Z" fill="currentColor" />
                  </svg>
                  <span className="ext-badge">!!</span>
                </span>
              </div>
              <div className="ext-stage">
                <div className="ext-popup">
                  <Image
                    src="/extension/popup.png"
                    width={760}
                    height={2874}
                    sizes="380px"
                    priority
                    alt="The Dossier popup on a sample store's site. High risk. Main risk: it may sell your personal information. Below it, each risk with the policy sentence behind it."
                  />
                </div>
              </div>
            </div>
            <figcaption>The popup on ShopCo, a sample store that doesn&apos;t exist.</figcaption>
          </figure>
        </section>

        <section id="shows" className="lp-section ext-shows-section">
          <div className="wrap">
            <h2 className="sec-title">What it shows you</h2>
            <p className="sec-lede">The badge appears as you browse. Open the popup for the evidence behind it.</p>
            <ul className="ext-shows">
              {SHOWS.map((s, n) => (
                <li key={s.title}>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="install" className="lp-section ext-install">
          <div className="wrap">
            <h2 className="sec-title">Install it in four steps</h2>
            <p className="sec-lede">
              It isn&apos;t in the Chrome Web Store yet, so you add it yourself. It takes about a minute.
            </p>
            <div className="ext-install-grid">
              <ol className="ext-steps">
                <li>
                  <span className="ext-num">1</span>
                  <div>
                    <h3>Download it and unzip it</h3>
                    <p>
                      You get a folder named <code>dossier-privacy-check</code>. Keep it somewhere you won&apos;t delete it.
                    </p>
                  </div>
                </li>
                <li>
                  <span className="ext-num">2</span>
                  <div>
                    <h3>Open your browser&apos;s extensions page</h3>
                    <p>Paste this into the address bar, then turn on Developer mode.</p>
                    <div className="ext-copies">
                      <CopyText text="chrome://extensions" />
                      <CopyText text="edge://extensions" />
                    </div>
                  </div>
                </li>
                <li>
                  <span className="ext-num">3</span>
                  <div>
                    <h3>Choose Load unpacked</h3>
                    <p>
                      Pick the <code>dossier-privacy-check</code> folder.
                    </p>
                  </div>
                </li>
                <li>
                  <span className="ext-num">4</span>
                  <div>
                    <h3>Pin it and reload your tabs</h3>
                    <p>Pin it from the puzzle-piece menu. Tabs you already had open need a reload before it can see them.</p>
                  </div>
                </li>
              </ol>
            </div>
          </div>
        </section>

        <section id="privacy" className="dark">
          <div className="wrap dark-grid">
            <div>
              <h2 className="sec-title">What it reads, and what it sends</h2>
              <p className="sec-lede">
                A privacy tool shouldn&apos;t become one more thing watching you. Every request it makes is listed in
                Dossier&apos;s outbound log.
              </p>
              <ul className="dark-points">
                {GUARANTEES.map((g, n) => (
                  <li key={g}>
                    <Check /> {g}
                  </li>
                ))}
              </ul>
            </div>
            <div className="demo-log">
              <div className="demo-log-head">
                <span className="demo-log-title">Opening the popup on shopco.example</span>
                <span className="demo-log-count">
                  <span>3 left this computer</span>
                </span>
              </div>
              <ol className="demo-log-rows">
                {RECEIPT.map((r) => (
                  <li key={r.url} className={`demo-log-row${r.local ? " demo-log-local" : ""}`}>
                    <span className="demo-log-svc">{r.service}</span>
                    <span className="demo-log-url">
                      <span className="demo-log-method">{r.method}</span> {r.url}
                    </span>
                    <span className="demo-log-status">{r.status}</span>
                    <span className="demo-log-body">{r.note}</span>
                  </li>
                ))}
              </ol>
              <p className="demo-log-foot">Sample entries for ShopCo, a store that doesn&apos;t exist.</p>
            </div>
          </div>
        </section>

        <section className="wrap cta">
          <div>
            <h2 className="sec-title">Check the next site you visit.</h2>
            <p className="sec-lede">Automated removal plans are coming.</p>
          </div>
          <div>
            <ExtensionDownload />
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <div className="foot-brand">
          <Logo />
          <p>Runs on your laptop. Every request that leaves it is logged.</p>
        </div>
        <nav className="foot-nav" aria-label="Footer">
          <a href="#shows">What it shows</a>
          <a href="#install">Install</a>
          <a href="#privacy">Privacy</a>
          <Link href="/">Dossier</Link>
          <Link href="/login?next=/extension">Log in</Link>
        </nav>
        <p className="foot-note">ShopCo and the .example sites on this page are fictional.</p>
      </footer>

      <NavScroll />
    </div>
  );
}
