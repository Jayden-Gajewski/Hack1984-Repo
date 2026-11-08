// The popup: the privacy check for the site in the current tab. Opening it also starts the Gemini
// pass for that site, and the popup asks again every few seconds until it's done.
//
// Everything shown comes from a web page (quotes, links), so it's added as text nodes, never as
// HTML, and links must be plain http(s).
//
// It reads like a dossier of the visit: plain claims in the second person, each with the evidence
// behind it and how Dossier knows. A claim says only what was seen, and how sure it is ("can",
// "may"); silence beats a confident claim that turns out wrong.
//
// Layout: the site in a header, then three views behind the tab bar. "This site" is the verdict
// card and four tiles (risks, trackers, what it collects, what it shares) that pick the panel
// below them. "Sites" lists the sites you opened this session, from session storage. "Settings"
// holds the browsing preferences.
import {
  APP_URL,
  DEFAULTS,
  HOSTED,
  LOGIN_URL,
  Offline,
  SignedOut,
  WHERE,
  aliasRequest,
  cachedResult,
  checkPage,
  forgetSites,
  isCheckable,
  readPage,
  rememberResult,
  setBadge,
  sightings,
  visitedSites,
} from "./shared.js";

const POLL_MS = 2500;
const VERDICT = { high: "High risk", medium: "Some risk", low: "Low risk" };
const LEVEL = { high: "High", medium: "Medium", low: "Low" };
const CLAUSE = {
  sale: "Sells data",
  data_broker: "Data brokers",
  sharing: "Shares data",
  advertising: "Targeted ads",
  affiliates: "Affiliates",
};
const TRACKER = {
  session_recording: ["Records sessions", "Can capture your clicks, scrolling and typing on this page."],
  data_broker: ["Data broker", "Links your visit to a profile that other companies buy."],
  advertising: ["Ads", "Can add this visit to an ad profile and follow you across sites."],
  social: ["Social", "Learns you were here, even if you don't click anything."],
  analytics: ["Analytics", "Sees your visit and what you do here."],
  tag_manager: ["Tag manager", "Loads other scripts for the site, often trackers."],
};
const FIELD_LABEL = {
  email: "email address",
  phone: "phone number",
  address: "street address",
  birthdate: "date of birth",
  password: "password",
  card: "card number",
  bank_account: "bank account number",
  ssn: "Social Security number",
  government_id: "government ID number",
};
// The tiles under the verdict, in order. Each one picks the panel below it.
const TILES = [
  { key: "risks", icon: "alert", label: "Risks" },
  { key: "page", icon: "eye", label: "Trackers" },
  { key: "collects", icon: "file", label: "Collects" },
  { key: "shares", icon: "share", label: "Shares" },
];
// The verdict card's icon: a warning for a risk, a shield when nothing concerning was found.
const DISC = { high: "alert", medium: "alert", low: "shield" };

// Line icons on a 24px grid, drawn with the current text color.
const ICONS = {
  refresh: ["M20 12a8 8 0 1 1-8-8c2.2 0 4.3.9 5.9 2.4L20 8.5", "M20 3.5v5h-5"],
  open: ["M14 4h6v6", "M20 4l-9 9", "M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"],
  shield: ["M12 3.5 5 6.5v5c0 4.4 2.9 7.6 7 9 4.1-1.4 7-4.6 7-9v-5Z"],
  clock: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Z", "M12 7.5V12l3 2"],
  sliders: [
    "M4 8h9",
    "M17 8h3",
    "M4 16h3",
    "M11 16h9",
    "M15 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z",
    "M9 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z",
  ],
  alert: [
    "M10.3 4.5 2.9 17.3a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.5a2 2 0 0 0-3.4 0Z",
    "M12 9.5v4",
    "M12 17h.01",
  ],
  eye: [
    "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z",
    "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z",
  ],
  file: ["M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5Z", "M14 3.5v5h5", "M9 13h6", "M9 16.5h4"],
  share: ["M14 5l6 6-6 6", "M20 11h-8a7 7 0 0 0-7 7v1"],
  question: [
    "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Z",
    "M9.6 9.3a2.5 2.5 0 0 1 4.9.7c0 1.7-2.5 2.2-2.5 3.7",
    "M12 17h.01",
  ],
  power: ["M12 3.5v8", "M7 6.3a7.5 7.5 0 1 0 10 0"],
  check: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Z", "M8.5 12.2l2.4 2.4 4.6-4.8"],
};

const main = document.getElementById("main");
const avatar = document.getElementById("avatar");
const siteLabel = document.getElementById("site");
const siteSub = document.getElementById("site-sub");
const recheckButton = document.getElementById("recheck");
const statusLine = document.getElementById("status");
const autoBox = document.getElementById("auto");
const readBox = document.getElementById("read-policies");
const forgetButton = document.getElementById("forget");
const forgetResult = document.getElementById("forget-result");
const siteList = document.getElementById("site-list");
const aliasBox = document.getElementById("alias");
const views = { main, sites: document.getElementById("sites"), settings: document.getElementById("settings") };
const tabButtons = [...document.querySelectorAll(".tabbar button")];
const mark = [...avatar.childNodes]; // the app's mark, shown until a site is known
// Trackers that can follow a browser from site to site; analytics and tag managers only see the visit.
const FOLLOWS = new Set(["advertising", "data_broker", "social"]);

let tabId = null;
let page = null;
let pollTimer = null;
let shown = "";
// The tile picked under the verdict; kept while the popup polls, reset for a new site.
let tab = null;
// The other sites you opened where Dossier saw each company and tracker (sightings() in shared.js).
let elsewhere = { byCompany: new Map(), byTracker: new Map() };
let forgotten = false;

// ---------- small DOM helpers ----------

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) node.append(child); // strings become text
  }
  return node;
}

function icon(name) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  for (const [key, value] of Object.entries({
    viewBox: "0 0 24 24",
    width: "24",
    height: "24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  })) {
    svg.setAttribute(key, value);
  }
  for (const d of ICONS[name]) {
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function safeHref(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

const bareHost = (url) => new URL(url).hostname.replace(/^www\./, "");
const shortUrl = (url) => (bareHost(url) + new URL(url).pathname).replace(/\/$/, "");

function link(url, text) {
  const href = safeHref(url);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text ?? shortUrl(href)) : null;
}

function time(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "an unknown time" : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** A claim in plain words. A *starred* phrase is the part to notice. Text nodes only. */
const say = (text) => text.split(/\*([^*]+)\*/).map((part, i) => (i % 2 ? h("strong", {}, part) : part));

const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "a, b and c", or "a, b, c and 4 more" past `max`. */
function listOf(items, max = 4) {
  const shown = items.length > max ? [...items.slice(0, max), `${items.length - max} more`] : items;
  return shown.length < 2 ? shown.join("") : `${shown.slice(0, -1).join(", ")} and ${shown.at(-1)}`;
}

/** Replace the content, keeping open rows open and focus where it was (the popup re-renders when
 *  Gemini finishes). */
function show(...nodes) {
  const open = new Set([...main.querySelectorAll("details[open][data-key]")].map((d) => d.dataset.key));
  const active = main.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = active?.dataset.focusKey ?? active?.closest("details[data-key]")?.dataset.key ?? null;
  main.replaceChildren(...nodes.flat().filter(Boolean), aliasBox);
  for (const details of main.querySelectorAll("details[data-key]")) {
    if (open.has(details.dataset.key)) details.open = true;
  }
  if (focusKey) {
    const again = [...main.querySelectorAll("[data-focus-key], details[data-key]")].find(
      (node) => (node.dataset.focusKey ?? node.dataset.key) === focusKey,
    );
    (again?.matches("details") ? again.querySelector("summary") : again)?.focus();
  }
}

function announce(text) {
  if (statusLine.textContent !== text) statusLine.textContent = text;
}

/** The header: the site's name and first letter (tinted by its risk), and a line under it. */
function setHeader(site, sub, risk = null) {
  siteLabel.textContent = site ?? "Dossier";
  siteSub.textContent = sub;
  if (site) avatar.replaceChildren(site.charAt(0));
  else avatar.replaceChildren(...mark);
  if (risk) avatar.dataset.risk = risk;
  else delete avatar.dataset.risk;
}

// ---------- states ----------

// The verdict card says what's happening now; the tiles and rows below it fade in as shapes only
// if the wait passes 150 ms.
function renderLoading(text) {
  shown = "";
  show(
    h(
      "section",
      { class: "hero hero--loading" },
      h("span", { class: "disc" }, h("span", { class: "spinner", "aria-hidden": "true" })),
      h("p", { class: "hero-summary" }, text),
    ),
    h(
      "div",
      { class: "skeleton", "aria-hidden": "true" },
      h(
        "span",
        { class: "skeleton-tiles" },
        TILES.map(() => h("span", { class: "skeleton-item skeleton-item--tile" })),
      ),
      h("span", { class: "skeleton-item" }),
      h("span", { class: "skeleton-item" }),
    ),
  );
  siteSub.textContent = "Checking…";
  announce(text);
}

/** A button that starts a request: it keeps its label (and width) and shows a spinner. */
function busy(button) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
}

function renderMessage(iconName, title, text, ...extra) {
  shown = "";
  show(
    h(
      "section",
      { class: "hero" },
      h("span", { class: "disc" }, icon(iconName)),
      h("h1", {}, title),
      text ? h("p", { class: "hero-summary" }, text) : null,
      ...extra,
    ),
  );
  announce(title);
}

function tryAgainButton(primary = true) {
  return h(
    "button",
    {
      class: primary ? "button button--primary" : "button",
      type: "button",
      onclick: (event) => {
        busy(event.currentTarget);
        announce("Trying again…");
        start();
      },
    },
    "Try again",
  );
}

function renderOffline() {
  siteSub.textContent = "Not checked";
  if (HOSTED) {
    renderMessage(
      "power",
      "Couldn't reach Dossier",
      `The extension checks privacy policies with Dossier at ${bareHost(APP_URL)}, and it didn't answer. It can take up to a minute to wake up.`,
      h("div", { class: "actions" }, tryAgainButton()),
    );
    return;
  }
  renderMessage(
    "power",
    "Start Dossier on this laptop",
    "The extension checks privacy policies with the Dossier backend on your own computer, and it isn't running. Start it from the repo:",
    h("pre", { class: "code" }, "cd backend\nuvicorn app.main:app"),
    h("div", { class: "actions" }, tryAgainButton()),
  );
}

// The copy from the public site checks sites with the user's own Dossier account.
function renderSignedOut() {
  siteSub.textContent = "Not checked";
  renderMessage(
    "power",
    "Sign in to Dossier",
    `This extension checks sites with your Dossier account. Sign in at ${bareHost(APP_URL)} in this browser, then try again.`,
    h(
      "div",
      { class: "actions" },
      h("a", { class: "button button--primary", href: LOGIN_URL, target: "_blank", rel: "noopener noreferrer" }, "Sign in to Dossier ↗"),
      tryAgainButton(false),
    ),
  );
}

const quote = (text, under = "") =>
  h(
    "figure",
    { class: "quote" },
    h("blockquote", {}, `“${text}”`),
    h("figcaption", {}, under ? `From the policy, under “${under}”` : "From the policy"),
  );

const riskRow = (risk) =>
  h(
    "li",
    { class: `row risk risk--${risk.level}` },
    h(
      "details",
      { "data-key": `risk:${risk.title}` },
      h("summary", {}, h("span", { class: "level" }, LEVEL[risk.level]), h("span", { class: "row-title" }, risk.title)),
      h("p", { class: "detail" }, risk.detail),
      // A quote, what was seen on the page, or both (a promise in the policy against the page's trackers).
      risk.quote ? quote(risk.quote) : null,
      risk.evidence?.length ? h("p", { class: "detail" }, `Evidence: ${risk.evidence.join(", ")}`) : null,
      risk.how
        ? h("p", { class: "how" }, h("strong", {}, "How Dossier knows: "), risk.how)
        : !risk.quote && !risk.evidence?.length
          ? h("p", { class: "detail" }, "Seen on this page.")
          : null,
    ),
  );

const collectedRow = (item) =>
  h(
    "li",
    { class: "row" },
    h(
      "details",
      { "data-key": `collected:${item.category}` },
      h(
        "summary",
        {},
        h("span", { class: "row-title" }, item.label),
        item.sensitive ? h("span", { class: "tag tag--sensitive" }, "Sensitive") : null,
      ),
      quote(item.quote, item.section),
    ),
  );

const clauseRow = (clause) =>
  h(
    "li",
    { class: "row" },
    h(
      "details",
      { "data-key": `clause:${clause.category}:${clause.quote.slice(0, 60)}` },
      h(
        "summary",
        {},
        h("span", { class: "tag" }, CLAUSE[clause.category] ?? clause.category),
        h("span", { class: "row-title" }, clause.explanation.charAt(0).toUpperCase() + clause.explanation.slice(1)),
      ),
      quote(clause.quote),
    ),
  );

const empty = (text) => h("p", { class: "empty" }, text);
const lead = (text) => h("p", { class: "lead" }, text);

/** Why a policy tile has nothing to show. */
function policyMissing(result) {
  return {
    no_policy: "Couldn't find this site's privacy policy, so there's nothing to show here.",
    unreadable: "Couldn't read this site's privacy policy, so there's nothing to show here.",
  }[result.status] ?? "Dossier hasn't read this site's privacy policy yet.";
}

function sharing(result) {
  const body = [];
  if (result.clauses.length) body.push(h("ul", { class: "rows" }, result.clauses.map(clauseRow)));
  else {
    body.push(
      empty(
        result.llm === "running"
          ? "Nothing found yet. Gemini is still reading."
          : "Found nothing in the policy about selling or sharing your data.",
      ),
    );
  }
  if (result.no_sale_quote) body.push(h("div", { class: "also" }, h("p", {}, "It also says:"), quote(result.no_sale_quote)));
  return body;
}

function unreadableHelp(result) {
  const text =
    result.status === "no_policy"
      ? "Couldn't find a privacy-policy link on this page. If you can find the policy, open it and choose “Check this page”."
      : "The site blocked the request, or its policy needs JavaScript to show. Open the policy and choose “Check this page” to read it from your browser instead.";
  return h(
    "section",
    { class: "help" },
    h("p", {}, text),
    result.policy_url ? h("p", {}, link(result.policy_url, `Open the privacy policy on ${bareHost(result.policy_url)}`)) : null,
  );
}

function details(result) {
  const lines = [];
  if (result.status === "ok") {
    const llm = {
      running: [
        h("span", { class: "spinner", "aria-hidden": "true" }),
        "Gemini is reading the policy for more selling and sharing clauses…",
      ],
      done: [`Checked by fixed rules on ${WHERE} and by Gemini.`],
      failed: ["Gemini didn't answer, so this is the rules-based check."],
      off: ["Rules-based check. The Gemini check starts when you open this popup."],
      limit: ["Rules-based check. Your account's Gemini checks for today are used up."],
    }[result.llm];
    lines.push(h("p", { class: `llm llm--${result.llm}` }, ...llm));
  }
  if (safeHref(result.policy_url)) {
    const how =
      result.read_from === "browser"
        ? " Read from the page open in your browser, so nothing was fetched."
        : result.read_from === "site"
          ? ` Fetched straight from ${bareHost(result.policy_url)}, not through a search engine.`
          : "";
    lines.push(h("p", { class: "source" }, "Policy: ", link(result.policy_url), `.${how}`));
  }
  lines.push(h("p", { class: "source" }, `Checked at ${time(result.checked_at)} by ${WHERE}.`));
  if (result.errors.length) {
    lines.push(
      h(
        "details",
        { class: "notes", "data-key": "notes" },
        h("summary", {}, `Notes (${result.errors.length})`),
        h("ul", {}, result.errors.map((error) => h("li", {}, error))),
      ),
    );
  }
  lines.push(
    h(
      "button",
      {
        class: "button",
        type: "button",
        title: "Read the privacy policy open in this tab",
        "data-focus-key": "check-page",
        onclick: () => checkThisPage(),
      },
      "Check this page",
    ),
  );
  return h("section", { class: "info" }, ...lines);
}

function brokerCard(broker) {
  const optOut = safeHref(broker.opt_out_url);
  return h(
    "section",
    { class: "broker" },
    h("p", { class: "broker-title" }, "This is a people-search site"),
    h("p", {}, `${broker.name} publishes and sells profiles of people. It may have one about you.`),
    h(
      "div",
      { class: "actions" },
      h("a", { class: "button button--primary", href: APP_URL, target: "_blank", rel: "noopener noreferrer" }, "Scan yourself with Dossier"),
      optOut
        ? h("a", { class: "button", href: optOut, target: "_blank", rel: "noopener noreferrer" }, `Opt out on ${bareHost(optOut)}`)
        : null,
    ),
  );
}

function pageRow(key, summary, ...body) {
  return h("li", { class: "row" }, h("details", { "data-key": key }, h("summary", {}, ...summary), ...body));
}

/**
 * What a bidder in an ad auction on this page can be sent about you: the OpenRTB 2.6 bid request,
 * filled in from this browser. Built and shown here, sent nowhere. What only the ad exchange knows
 * (your IP address and where it puts you, its ID for you) stays a labeled placeholder, never a guess.
 */
function bidRequest(site) {
  const uad = navigator.userAgentData;
  const mobile = uad ? uad.mobile : /Mobi|Android|iPhone/i.test(navigator.userAgent);
  const fromIp = "<from your IP address>";
  return {
    id: "<a new ID for each auction>",
    at: 1,
    tmax: 120,
    imp: [{ id: "1", banner: { w: 300, h: 250 } }],
    site: { domain: site, page: "<the full address of the page you're on>", ref: "<the page you came from>" },
    device: {
      ua: navigator.userAgent,
      ip: "<your IP address>",
      geo: { type: 2, country: fromIp, region: fromIp, city: fromIp, zip: fromIp, utcoffset: -new Date().getTimezoneOffset() },
      devicetype: mobile ? 4 : 2, // 4 phone, 2 computer
      os: uad?.platform || undefined,
      w: screen.width,
      h: screen.height,
      pxratio: window.devicePixelRatio,
      language: (navigator.language || "en").split("-")[0],
      js: 1,
    },
    user: {
      id: "<the ad exchange's ID for this browser>",
      buyeruid: "<each bidder's own ID for you>",
      data: [{ name: "<a data company>", segment: [{ name: "<interests and traits it has linked to you>" }] }],
    },
  };
}

function receipt(site) {
  return h(
    "details",
    { class: "receipt", "data-key": "receipt" },
    h("summary", {}, "See what each bidder can be sent"),
    h(
      "p",
      { class: "fine" },
      "If this page auctions its ad space, every bidder can get a message like this one, in the OpenRTB format ad " +
        "auctions use. Dossier filled it in from your browser just now and sends it nowhere. The ad exchange fills in " +
        "the parts in angle brackets.",
    ),
    h("pre", { class: "code" }, JSON.stringify(bidRequest(site), null, 2)),
    h("p", { class: "fine" }, "Bidders that lose the auction can keep what they were sent. It's one way data companies learn where you go online."),
  );
}

function adsRow(ads, site) {
  if (ads.status === "running") {
    return h("li", { class: "row" }, h("p", { class: "plain" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Reading its ads.txt…"));
  }
  if (ads.status !== "done") {
    const text = ads.status === "none" ? "No ads.txt: it doesn't publish a list of ad sellers." : "Couldn't read its ads.txt.";
    return h("li", { class: "row" }, h("p", { class: "plain" }, h("span", { class: "tag" }, "Ad sellers"), text));
  }
  const others = ads.count > ads.companies.length ? " and others" : "";
  return pageRow(
    "ads",
    [h("span", { class: "tag" }, "Ad sellers"), h("span", { class: "row-title" }, `${ads.count} ad companies may sell its ads`)],
    h("p", { class: "detail" }, `Its ads.txt names ${ads.companies.join(", ")}${others}. Each ad auction can pass details about your visit to them.`),
    ads.url ? h("p", { class: "detail" }, "From ", link(ads.url), ".") : null,
    receipt(site),
  );
}

/**
 * The visit in plain words, above the rows: which companies learned you were here, and the one
 * Dossier saw on the most other sites you opened. Only what was seen; "can", never "does".
 */
function visitClaims(result) {
  const companies = [...new Set(result.trackers.map((t) => t.company))];
  if (!companies.length) return null;
  const lines = [
    `Loading this page told *${count(companies.length, "company", "companies")}* you were here: ${listOf(companies)}.`,
  ];
  // Ties go to the company listed first, which is the strongest kind of tracker on the page.
  const top = companies
    .map((company) => ({ company, sites: elsewhere.byCompany.get(company)?.size ?? 0 }))
    .reduce((best, next) => (next.sites > best.sites ? next : best));
  if (top.sites) {
    const follows = result.trackers.some((t) => t.company === top.company && FOLLOWS.has(t.category));
    lines.push(
      `Dossier also saw *${top.company}* on *${count(top.sites, "other site", "other sites")}* you opened since the ` +
        `browser started. ${follows ? "That's how ad tech can follow you from site to site." : `Each of those visits reached ${top.company} too.`}`,
    );
  }
  return h("div", { class: "claims" }, lines.map((line) => h("p", { class: "claim" }, ...say(line))));
}

/** What the page itself does: the visit in plain words, then its trackers, forms and ad sellers. */
function pagePanel(result) {
  const rows = result.trackers.map((tracker) => {
    const [tag, help] = TRACKER[tracker.category];
    const strong = tracker.category === "data_broker"; // red only for what Dossier exists to fight
    const others = [...(elsewhere.byTracker.get(tracker.name) ?? [])];
    return pageRow(
      `tracker:${tracker.name}`,
      [
        h("span", { class: strong ? "tag tag--sensitive" : "tag" }, tag),
        h("span", { class: "row-title" }, tracker.name),
        others.length ? h("span", { class: "seen" }, `also on ${count(others.length, "site", "sites")}`) : null,
      ],
      h("p", { class: "detail" }, `${help} Run by ${tracker.company}.`),
      h("p", { class: "detail" }, `Loaded from ${tracker.hosts.join(", ")}.`),
      others.length
        ? h("p", { class: "detail" }, `Dossier also saw it on ${listOf(others, 3)}, since the browser started.`)
        : null,
    );
  });
  if (result.asks_for.length) {
    const insecure = result.insecure_fields.map((f) => FIELD_LABEL[f]);
    rows.push(
      pageRow(
        "asks",
        [
          h("span", { class: "tag" }, "Asks for"),
          h("span", { class: "row-title" }, result.asks_for.map((f) => FIELD_LABEL[f]).join(", ")),
          insecure.length ? h("span", { class: "tag tag--sensitive" }, "Not encrypted") : null,
        ],
        h("p", { class: "detail" }, "From the page's form fields. Dossier reads what each field is for, never what's in it."),
        insecure.length ? h("p", { class: "detail" }, `Sent without https: ${insecure.join(", ")}.`) : null,
      ),
    );
  }
  if (result.ad_sellers) rows.push(adsRow(result.ad_sellers, result.site));
  if (!rows.length) return [empty("No known trackers on this page, and no forms that ask for personal data.")];
  return [visitClaims(result), h("ul", { class: "rows" }, rows)];
}

function panelFor(result, key) {
  const read = result.status === "ok";
  if (key === "risks") {
    return result.risks.length
      ? [h("ul", { class: "rows" }, result.risks.map(riskRow))]
      : [empty(read ? "Nothing concerning found." : "Nothing concerning seen on this page.")];
  }
  if (key === "page") return pagePanel(result);
  if (!read) return [empty(policyMissing(result))];
  if (key === "collects") {
    return result.collected.length
      ? [lead("What its privacy policy says it collects."), h("ul", { class: "rows" }, result.collected.map(collectedRow))]
      : [empty("Found nothing in the policy about what it collects.")];
  }
  return [lead("What its privacy policy says about selling and sharing your data."), ...sharing(result)];
}

/** How many of each a tile counts. Null: the policy wasn't read, so nobody knows. */
function tileCount(result, key) {
  const read = result.status === "ok";
  return {
    risks: result.risks.length,
    page: result.trackers.length,
    collects: read ? result.collected.length : null,
    shares: read ? result.clauses.length : null,
  }[key];
}

/** The four tiles and the panel they pick. They're tabs: arrow keys move between them. */
function tilesAndPanel(result) {
  if (!tab) tab = TILES.find(({ key }) => tileCount(result, key) > 0)?.key ?? "risks";
  const panel = h("div", { class: "panel", role: "tabpanel", id: "panel" });
  const buttons = TILES.map(({ key, icon: name, label }) => {
    const n = tileCount(result, key);
    return h(
      "button",
      {
        type: "button",
        class: "tile",
        role: "tab",
        id: `tile-${key}`,
        "aria-controls": "panel",
        "data-focus-key": `tile:${key}`,
        "data-tile": key,
        "aria-label": n === null ? `${label}: policy not read` : null,
        onclick: () => choose(key),
      },
      icon(name),
      h("span", { class: "tile-count" }, n === null ? "–" : String(n)),
      h("span", { class: "tile-label" }, label),
    );
  });
  function choose(key, focus = false) {
    tab = key;
    for (const button of buttons) {
      const on = button.dataset.tile === key;
      button.setAttribute("aria-selected", String(on));
      button.tabIndex = on ? 0 : -1;
      if (on && focus) button.focus();
    }
    panel.setAttribute("aria-labelledby", `tile-${key}`);
    panel.replaceChildren(...panelFor(result, key).filter(Boolean));
  }
  const list = h("div", { class: "tiles", role: "tablist", "aria-label": "Evidence" }, buttons);
  list.addEventListener("keydown", (event) => {
    const at = TILES.findIndex(({ key }) => key === tab);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: TILES.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    choose(TILES[(to + TILES.length) % TILES.length].key, true);
  });
  choose(tab);
  return [list, panel];
}

function render(result) {
  const json = JSON.stringify(result);
  if (json === shown) return; // polling: nothing new yet
  shown = json;
  const unread =
    { no_policy: "No privacy policy found", not_read: "Nothing concerning seen yet" }[result.status] ?? "Couldn't read the policy";
  const verdict =
    result.status === "ok" && !result.risks.length
      ? "Nothing concerning found"
      : (VERDICT[result.risk] ?? (result.status === "ok" ? "Checked" : unread));
  const discIcon = result.risk ? DISC[result.risk] : result.status === "ok" ? "shield" : "question";
  const optOut = safeHref(result.opt_out_url);
  setHeader(result.site, `Checked at ${time(result.checked_at)}`, result.risk);
  show(
    h(
      "section",
      { class: `hero hero--${result.risk ?? "unknown"}` },
      h("span", { class: "disc" }, icon(discIcon)),
      h("h1", {}, verdict),
      result.summary ? h("p", { class: "hero-summary" }, result.summary) : null,
      optOut
        ? h(
            "div",
            { class: "actions" },
            h(
              "a",
              { class: "button button--primary", href: optOut, target: "_blank", rel: "noopener noreferrer" },
              "Opt out of sale and sharing",
            ),
            h("p", { class: "fine" }, `Opens ${shortUrl(optOut)}`), // say where it goes before anyone types in it
          )
        : null,
    ),
    result.broker ? brokerCard(result.broker) : null,
    result.status === "unreadable" || result.status === "no_policy" ? unreadableHelp(result) : null,
    tilesAndPanel(result),
    details(result),
  );
  announce(`${verdict} on ${result.site}.${result.llm === "done" ? " Gemini check done." : ""}`);
}

// ---------- Sites you opened ----------

function siteSummary(result) {
  const bits = [
    count(result.risks?.length ?? 0, "risk", "risks"),
    count(result.trackers?.length ?? 0, "tracker", "trackers"),
  ];
  if (result.status !== "ok") bits.push({ no_policy: "no policy found", unreadable: "policy unreadable" }[result.status] ?? "policy not read");
  return bits.join(", ");
}

async function renderSites() {
  const sites = await visitedSites();
  if (!sites.length) {
    siteList.replaceChildren(
      h(
        "li",
        { class: "empty" },
        autoBox.checked
          ? "No sites yet. They appear here as you browse."
          : "No sites yet. Turn on “Check every site I visit” in Settings, or open this popup on a site.",
      ),
    );
    return;
  }
  siteList.replaceChildren(
    ...sites.map(({ site, result }) =>
      h(
        "li",
        { class: `row site-row risk--${result.risk ?? "none"}` },
        h("span", { class: "avatar", "data-risk": result.risk ?? null, "aria-hidden": "true" }, site.charAt(0)),
        h("div", { class: "site-row-text" }, h("p", { class: "site-row-name" }, site), h("p", { class: "site-row-sub" }, siteSummary(result))),
        result.risk ? h("span", { class: "level" }, LEVEL[result.risk]) : null,
      ),
    ),
  );
}

// ---------- views ----------

function goTo(name) {
  for (const [key, view] of Object.entries(views)) view.hidden = key !== name;
  for (const button of tabButtons) {
    if (button.dataset.view === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (name === "sites") renderSites();
}

// ---------- private email for this site ----------
// Shown when the page asks for an email address. Only the site's hostname goes to the Dossier app
// (on this laptop, or the public site); the alias is filled into the page only when you click "Fill in".


function aliasShow(...nodes) {
  aliasBox.replaceChildren(
    h("h2", { id: "alias-title" }, "Private email for this site"),
    ...nodes.flat().filter(Boolean),
  );
  aliasBox.hidden = false;
}

async function fillIn(address, note) {
  let filled = false;
  try {
    const reply = await chrome.tabs.sendMessage(tabId, { type: "fill-email", address }, { frameId: 0 });
    filled = reply?.filled === true;
  } catch {
    // content.js isn't on this page (reload it) or the tab is gone.
  }
  if (!filled) {
    try {
      await navigator.clipboard.writeText(address);
      note.textContent = "Couldn't find the email field, so it's copied. Paste it in.";
    } catch {
      note.textContent = "Couldn't find the email field. Select the address above and copy it.";
    }
  } else {
    note.textContent = "Filled in. Check it before you submit the form.";
  }
  announce(note.textContent);
}

function renderAlias(alias) {
  const note = h("p", { class: "fine", role: "status" });
  aliasShow(
    h("p", { class: "alias-address" }, alias.alias),
    h(
      "p",
      { class: "fine" },
      `Made ${alias.created_at} for ${alias.site || alias.company}. If anyone but this site writes to it, Dossier can show where your address went.`,
    ),
    h(
      "div",
      { class: "alias-actions" },
      h("button", { type: "button", class: "button button--primary", onclick: () => fillIn(alias.alias, note) }, "Fill in"),
      h(
        "button",
        {
          type: "button",
          class: "button",
          onclick: async () => {
            try {
              await navigator.clipboard.writeText(alias.alias);
              note.textContent = "Copied.";
            } catch {
              note.textContent = "Couldn't copy. Select the address and copy it.";
            }
            announce(note.textContent);
          },
        },
        "Copy",
      ),
    ),
    note,
  );
}

async function startAlias() {
  if (!page?.asksFor?.includes("email") || !isCheckable(page.origin)) return;
  const host = bareHost(page.origin);
  try {
    const existing = (await aliasRequest("GET")).find((a) => a.site === host && a.status === "active");
    if (existing) {
      renderAlias(existing);
      return;
    }
    const error = h("p", { class: "fine", role: "status" });
    const make = h(
      "button",
      {
        type: "button",
        class: "button button--primary",
        onclick: async () => {
          make.disabled = true;
          make.textContent = "Making…";
          try {
            renderAlias(await aliasRequest("POST", { site: host, label: "made from the extension" }));
            announce(`Made a private email for ${host}.`);
          } catch (err) {
            make.disabled = false;
            make.textContent = `Make one for ${host}`;
            error.textContent = err instanceof SignedOut ? "Sign in to Dossier in this browser, then try again." : err.message;
          }
        },
      },
      `Make one for ${host}`,
    );
    aliasShow(
      h("p", {}, "This page asks for your email. Give it an address of its own instead."),
      h("div", { class: "alias-actions" }, make),
      h("p", { class: "fine" }, HOSTED ? "Only the site's name is sent, to your Dossier account." : "Only the site's name is sent, to Dossier on this laptop."),
      error,
    );
  } catch (err) {
    if (err instanceof SignedOut) {
      aliasShow(
        h("p", {}, "This page asks for your email. Sign in to Dossier to give it a private address instead."),
        h("a", { class: "button", href: LOGIN_URL, target: "_blank", rel: "noopener noreferrer" }, "Sign in to Dossier ↗"),
      );
    }
    // The app isn't running or can't be reached: say nothing here; the main check already explains.
  }
}

// ---------- flow ----------

async function run(options) {
  clearTimeout(pollTimer);
  if (options.refresh) renderLoading("Reading this site's privacy policy again…");
  try {
    const result = await checkPage(page, options);
    if (forgotten) return; // "Forget" was pressed while this was on its way: don't store it again
    // Text from a page that isn't a policy doesn't replace the site's result.
    if (!(options.pageText && result.status !== "ok")) {
      await rememberResult(page.origin, result);
      await setBadge(tabId, result);
    }
    render(result);
    if (result.llm === "running" || result.ad_sellers?.status === "running") {
      pollTimer = setTimeout(() => run({ deep: true }), POLL_MS);
    }
  } catch (error) {
    if (error instanceof Offline) renderOffline();
    else if (error instanceof SignedOut) renderSignedOut();
    else renderMessage("alert", "Couldn't check this site", error.message);
  }
}

async function recheck() {
  goTo("main");
  busy(recheckButton);
  await run({ deep: true, refresh: true });
  recheckButton.removeAttribute("aria-busy");
  recheckButton.disabled = forgotten;
}

async function checkThisPage() {
  renderLoading("Reading the policy on this page…");
  const pageText = await readPage(tabId);
  if (!pageText) {
    renderMessage("question", "Couldn't read this page", "Reload the page and try again.");
    return;
  }
  await run({ deep: true, pageText });
}

async function start() {
  clearTimeout(pollTimer);
  tab = null;
  // Debugging aid: popup.html?tab=<id>, opened as a page, shows the check for that tab.
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  const [current] = forced ? [{ id: forced }] : await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = current?.id ?? null;
  const key = `tab:${tabId}`;
  page = tabId === null ? null : ((await chrome.storage.session.get(key))[key] ?? null);
  // activeTab lets the popup see the tab's address. If the extension hasn't heard from this page
  // (Back from the cache, a PDF, a browser page), don't show the last site's result.
  if (page && current?.url) {
    try {
      if (new URL(current.url).origin !== page.origin) page = null;
    } catch {
      page = null;
    }
  }
  if (!page) {
    setHeader(null, "Privacy check");
    renderMessage("shield", "Nothing to check here", "Dossier checks public websites. If this is one, reload the page so the extension can see it.");
    return;
  }
  setHeader(new URL(page.origin).hostname.replace(/^www\./, ""), "Privacy check");
  if (!isCheckable(page.origin)) {
    renderMessage("shield", "Nothing to check here", "Dossier checks public websites, not this computer or your local network.");
    return;
  }
  elsewhere = await sightings(page.origin);
  void startAlias(); // independent of the policy check
  const cached = await cachedResult(page.origin);
  if (cached) render(cached);
  else renderLoading("Reading this site's privacy policy…");
  const pageText = page.isPolicyPage ? await readPage(tabId) : null;
  await run({ deep: true, pageText });
  recheckButton.disabled = forgotten; // once the first check has answered
}

/** Forget every site, here and in the backend, then say exactly what was and wasn't cleared. */
async function forget() {
  busy(forgetButton);
  forgotten = true;
  recheckButton.disabled = true;
  clearTimeout(pollTimer);
  const { sites, backend, detail } = await forgetSites();
  elsewhere = { byCompany: new Map(), byTracker: new Map() };
  const here = sites
    ? `Cleared ${count(sites, "site", "sites")} from this browser.`
    : "This browser held no sites.";
  const there = HOSTED
    ? {
        cleared: " Dossier's server dropped your account's results and its log entries for them.",
        // It keeps them in memory for at most 6 hours.
        offline: " Dossier's server didn't answer. It drops its results for your account within 6 hours anyway.",
        signed_out: " You're signed out, so Dossier's server wasn't asked. It drops its results for your account within 6 hours anyway.",
        failed: ` Dossier's server didn't clear its copy: ${detail}`,
      }[backend]
    : {
        cleared: " The backend dropped its results and its log entries for them.",
        // Its results live only in memory, so a backend that isn't running holds none.
        offline: " The backend didn't answer. It keeps results only in memory, so if it isn't running it holds none.",
        signed_out: " The backend wasn't asked: sign in to Dossier first.",
        failed: ` The backend didn't clear its copy: ${detail}`,
      }[backend];
  const outcome = `${here}${there} Requests already made can't be recalled.`;
  renderMessage(
    backend === "failed" ? "alert" : "check",
    backend === "failed" ? "Forgotten in this browser only" : "Dossier forgot the sites you've visited",
    `${outcome} Open the popup again to check this site.`,
  );
  forgetResult.textContent = outcome;
  forgetResult.hidden = false;
  forgetButton.removeAttribute("aria-busy");
  forgetButton.textContent = "Forgotten";
  await renderSites();
}

for (const slot of document.querySelectorAll("[data-icon]")) slot.replaceWith(icon(slot.dataset.icon));
document.getElementById("open-app").href = APP_URL;
for (const button of tabButtons) button.addEventListener("click", () => goTo(button.dataset.view));
recheckButton.addEventListener("click", recheck);

// The copy from the public site talks about Dossier's server, not this laptop (popup.html holds
// the laptop's wording).
if (HOSTED) {
  const say = (id, text) => {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  };
  say(
    "auto-note",
    "Off at first: it sends each site's address, and the hostnames of the trackers it loaded, to Dossier's server. The server contacts no site and keeps nothing from it.",
  );
  say(
    "read-policies-note",
    "Dossier's server reads each site's policy straight from the site as you browse, so the site sees a request from Dossier, not from you. Needs the setting above. Opening this popup always reads it.",
  );
  say(
    "handled-note",
    "Policies are read and checked by fixed rules on Dossier's server, with your account. When you open this popup, the policy's selling and sharing sentences also go to Google's Gemini, with the site's name. Nothing goes to a search engine. Form fields are judged by their labels, not by what's in them.",
  );
  say("log-note", `Every request Dossier makes for you is listed in your account's outbound log at ${bareHost(APP_URL)}.`);
  say(
    "forget-note",
    "Clears which sites you've opened from the extension and from Dossier's server, including your account's log of requests for them. It can't recall requests already made: each site saw its policy being read, and for each popup you opened, Gemini got the site's name and sentences from its policy.",
  );
}

chrome.storage.local.get(["auto", "readPolicies"]).then(({ auto = DEFAULTS.auto, readPolicies = DEFAULTS.readPolicies }) => {
  autoBox.checked = auto;
  readBox.checked = readPolicies;
});
autoBox.addEventListener("change", () => chrome.storage.local.set({ auto: autoBox.checked }));
readBox.addEventListener("change", () => chrome.storage.local.set({ readPolicies: readBox.checked }));
forgetButton.addEventListener("click", forget);

start();
