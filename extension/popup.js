// The popup: the privacy check for the site in the current tab. Opening it also starts the local
// LLM pass for that site, and the popup asks again every few seconds until it's done.
//
// Everything shown comes from a web page (quotes, links), so it's added as text nodes, never as
// HTML, and links must be plain http(s).
import { APP_URL, Offline, cachedResult, checkPage, isCheckable, readPage, rememberResult, setBadge } from "./shared.js";

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
  address: "home address",
  birthdate: "date of birth",
  password: "password",
  card: "card number",
  bank_account: "bank account number",
  ssn: "Social Security number",
  government_id: "passport or driver's license number",
};

const main = document.getElementById("main");
const siteLabel = document.getElementById("site");
const statusLine = document.getElementById("status");
const autoBox = document.getElementById("auto");

let tabId = null;
let page = null;
let pollTimer = null;
let shown = "";

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

/** Replace the content, keeping open rows open (the popup re-renders when the local AI finishes). */
function show(...nodes) {
  const open = new Set([...main.querySelectorAll("details[open][data-key]")].map((d) => d.dataset.key));
  main.replaceChildren(...nodes.flat().filter(Boolean));
  for (const details of main.querySelectorAll("details[data-key]")) {
    if (open.has(details.dataset.key)) details.open = true;
  }
}

function announce(text) {
  if (statusLine.textContent !== text) statusLine.textContent = text;
}

// ---------- states ----------

function renderLoading(text) {
  shown = "";
  show(h("section", { class: "message" }, h("p", { class: "working" }, h("span", { class: "spinner", "aria-hidden": "true" }), text)));
  announce(text);
}

function renderMessage(title, text, ...extra) {
  shown = "";
  show(h("section", { class: "message" }, h("h1", {}, title), text ? h("p", {}, text) : null, ...extra));
  announce(title);
}

function renderOffline() {
  renderMessage(
    "Start Dossier on this laptop",
    "The extension checks privacy policies with the Dossier backend on your own computer, and it isn't running. Start it from the repo:",
    h("pre", { class: "code" }, "cd backend\nuvicorn app.main:app"),
    h("button", { class: "button", type: "button", onclick: () => start() }, "Try again"),
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
      risk.quote
        ? quote(risk.quote)
        : h("p", { class: "detail" }, risk.evidence?.length ? `Evidence: ${risk.evidence.join(", ")}` : "Seen on this page."),
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

function section(title, count, ...body) {
  return h("section", {}, h("h2", {}, h("span", {}, title), count ? h("span", {}, count) : null), ...body);
}

function sharing(result) {
  const body = [];
  if (result.clauses.length) body.push(h("ul", { class: "rows" }, result.clauses.map(clauseRow)));
  else {
    body.push(
      h(
        "p",
        { class: "muted" },
        result.llm === "running"
          ? "Nothing found yet. The local AI is still reading."
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
    result.policy_url ? h("p", {}, link(result.policy_url, "Open the privacy policy ↗")) : null,
  );
}

function details(result) {
  const lines = [];
  if (result.status === "ok") {
    const llm = {
      running: [
        h("span", { class: "spinner", "aria-hidden": "true" }),
        "The local AI is reading the policy on this laptop for more selling and sharing clauses…",
      ],
      done: ["Checked by fixed rules and by the local AI, on this laptop."],
      failed: ["The local AI didn't answer (is Ollama running?), so this is the rules-based check."],
      off: ["Rules-based check. The local AI check starts when you open this popup."],
    }[result.llm];
    lines.push(h("p", { class: `llm llm--${result.llm}` }, ...llm));
  }
  if (safeHref(result.policy_url)) {
    const how =
      result.read_from === "browser"
        ? " Read from the page open in your browser, so nothing was fetched."
        : result.read_from === "site"
          ? ` Fetched straight from ${bareHost(result.policy_url)}, not through a search engine or cloud AI.`
          : "";
    lines.push(h("p", { class: "source" }, "Policy: ", link(result.policy_url), `.${how}`));
  }
  lines.push(h("p", { class: "source" }, `Checked at ${time(result.checked_at)} by this laptop.`));
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
      "div",
      { class: "actions" },
      h(
        "button",
        { class: "button", type: "button", title: "Read the privacy policy open in this tab", onclick: () => checkThisPage() },
        "Check this page",
      ),
      h("button", { class: "button", type: "button", onclick: () => run({ deep: true, refresh: true }) }, "Re-check"),
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
      h("a", { class: "button button--primary", href: APP_URL, target: "_blank", rel: "noopener noreferrer" }, "Scan yourself with Dossier ↗"),
      optOut
        ? h("a", { class: "button", href: optOut, target: "_blank", rel: "noopener noreferrer" }, `Opt out on ${bareHost(optOut)} ↗`)
        : null,
    ),
  );
}

function pageRow(key, summary, ...body) {
  return h("li", { class: "row" }, h("details", { "data-key": key }, h("summary", {}, ...summary), ...body));
}

function adsRow(ads) {
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
  );
}

function pageSection(result) {
  const rows = result.trackers.map((tracker) => {
    const [tag, help] = TRACKER[tracker.category];
    const strong = tracker.category === "session_recording" || tracker.category === "data_broker";
    return pageRow(
      `tracker:${tracker.name}`,
      [h("span", { class: strong ? "tag tag--sensitive" : "tag" }, tag), h("span", { class: "row-title" }, tracker.name)],
      h("p", { class: "detail" }, `${help} Run by ${tracker.company}.`),
      h("p", { class: "detail" }, `Loaded from ${tracker.hosts.join(", ")}.`),
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
  if (result.ad_sellers) rows.push(adsRow(result.ad_sellers));
  if (!rows.length) return null;
  return section("What this page does", null, h("ul", { class: "rows" }, rows));
}

function render(result) {
  const json = JSON.stringify(result);
  if (json === shown) return; // polling: nothing new yet
  shown = json;
  const unread = result.status === "no_policy" ? "No privacy policy found" : "Couldn't read the policy";
  const verdict =
    result.status === "ok" && !result.risks.length
      ? "Nothing concerning found"
      : (VERDICT[result.risk] ?? (result.status === "ok" ? "Checked" : unread));
  const optOut = safeHref(result.opt_out_url);
  show(
    h(
      "section",
      { class: `verdict verdict--${result.risk ?? "unknown"}` },
      h("p", { class: "verdict-label" }, verdict),
      h("p", { class: "verdict-summary" }, result.summary),
    ),
    result.broker ? brokerCard(result.broker) : null,
    result.status !== "ok" ? unreadableHelp(result) : null,
    result.risks.length ? section("Risks", null, h("ul", { class: "rows" }, result.risks.map(riskRow))) : null,
    pageSection(result),
    result.collected.length
      ? section("What it says it collects", String(result.collected.length), h("ul", { class: "rows" }, result.collected.map(collectedRow)))
      : null,
    result.status === "ok" ? section("Selling and sharing", null, ...sharing(result)) : null,
    optOut
      ? h(
          "a",
          { class: "button button--primary", href: optOut, target: "_blank", rel: "noopener noreferrer" },
          `Opt out of sale and sharing on ${bareHost(optOut)} ↗`, // say where it goes before anyone types in it
        )
      : null,
    details(result),
  );
  announce(`${verdict} on ${result.site}.${result.llm === "done" ? " Local AI check done." : ""}`);
}

// ---------- flow ----------

async function run(options) {
  clearTimeout(pollTimer);
  if (options.refresh) renderLoading("Reading this site's privacy policy again…");
  try {
    const result = await checkPage(page, options);
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
    else renderMessage("Couldn't check this site", error.message);
  }
}

async function checkThisPage() {
  renderLoading("Reading the policy on this page…");
  const pageText = await readPage(tabId);
  if (!pageText) {
    renderMessage("Couldn't read this page", "Reload the page and try again.");
    return;
  }
  await run({ deep: true, pageText });
}

async function start() {
  clearTimeout(pollTimer);
  // Debugging aid: popup.html?tab=<id>, opened as a page, shows the check for that tab.
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  const [tab] = forced ? [{ id: forced }] : await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab?.id ?? null;
  const key = `tab:${tabId}`;
  page = tabId === null ? null : ((await chrome.storage.session.get(key))[key] ?? null);
  if (!page) {
    renderMessage("Nothing to check here", "Dossier checks public websites. If this is one, reload the page so the extension can see it.");
    return;
  }
  siteLabel.textContent = new URL(page.origin).hostname.replace(/^www\./, "");
  if (!isCheckable(page.origin)) {
    renderMessage("Nothing to check here", "Dossier checks public websites, not this computer or your local network.");
    return;
  }
  const cached = await cachedResult(page.origin);
  if (cached) render(cached);
  else renderLoading("Reading this site's privacy policy…");
  const pageText = page.isPolicyPage ? await readPage(tabId) : null;
  await run({ deep: true, pageText });
}

chrome.storage.local.get("auto").then(({ auto = true }) => {
  autoBox.checked = auto;
});
autoBox.addEventListener("change", () => chrome.storage.local.set({ auto: autoBox.checked }));

start();
