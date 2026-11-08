// Dossier content script. It runs on every http(s) page, in the top frame only, and only reads the
// page: it makes no network requests and changes nothing. It tells the extension, which asks the
// Dossier backend on this laptop:
// - the page's privacy-policy links, and any "Do Not Sell or Share" link to the site's own pages;
// - the hostnames, and only the hostnames, of other sites the page loaded scripts, images, frames
//   or beacons from, so known trackers can be named. A tracker's full URL often carries an account
//   id or a hashed email, so the rest of the URL is never kept;
// - the kinds of personal data the page's form fields ask for ("email", "card"...), judged from what
//   the page says about each field: its type, autocomplete hint, name and label. It never reads
//   what's in a field, whether typed by the user or filled in by the site.
// The page's text is read only when the page is itself a privacy policy, or when the user chooses
// "Check this page", and then it goes to the backend on this laptop only.
//
// Pages are untrusted. A page can shadow document methods and form properties with elements named
// "querySelectorAll" or "action", so those are always called through the browser's own prototypes.
(() => {
  const MAX_LINKS = 3;
  const MAX_URL = 2000;
  const MAX_TEXT = 400000;
  const MAX_HOSTS = 200;
  const MAX_FIELDS = 300;
  const OPT_OUT = /do not (sell|share)( or (sell|share))? my|don['’]t (sell|share) my|your privacy choices|opt[- ]out of (the )?(sale|sharing)/i;
  const PRIVACY_WORD = /\bprivacy\b|privacybeleid|datenschutz|confidentialit|privacidad|privacidade/;
  // Privacy links that aren't the policy itself, unless they say "policy" or point at one.
  const NOT_POLICY = /cookie|choices|settings|preferences|opt[- ]?out|request|dashboard|center|centre/i;
  // Field kinds, in order: the first match wins (so "Email address" is an email, not an address).
  const FIELD_KINDS = [
    ["card", /\bcc-(number|csc|exp)|card.?(number|no\b)|credit.?card|\bcvc\b|\bcvv\b|card.{0,20}security.?code|security.?code.{0,20}card/i],
    ["ssn", /\bssn\b|social.?security/i],
    ["government_id", /passport|driver.?s?.?licen[cs]e|national.?id|\btax.?id\b|\bitin\b/i],
    ["bank_account", /routing.?(number|no\b)|bank.?account|\biban\b/i],
    ["birthdate", /\bbday|birth.?(date|day)|date.?of.?birth|\bdob\b/i],
    ["phone", /\btel\b|phone|mobile/i],
    ["email", /e-?mail/i],
    ["address", /street|address-line|\b(home|mailing|postal|billing|shipping)[ -]?address\b/i],
  ];
  const SENSITIVE = new Set(["password", "card", "bank_account", "ssn", "government_id"]);
  const FIELDS =
    "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=checkbox])" +
    ":not([type=radio]):not([type=search]):not([type=image]):not([type=file]):not([type=range]):not([type=color]), select";

  const all = (selector) => Document.prototype.querySelectorAll.call(document, selector);
  const docGet = (name) => Object.getOwnPropertyDescriptor(Document.prototype, name).get.call(document);
  const attr = (el, name) => Element.prototype.getAttribute.call(el, name);
  const here = () => location.origin + location.pathname;

  function clean(href) {
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== "https:" && url.protocol !== "http:") return null;
      url.hash = "";
      url.search = ""; // a link on a logged-in page can carry an account id
      return url.href.length <= MAX_URL ? url.href : null;
    } catch {
      return null;
    }
  }

  const label = (a) =>
    (a.textContent || attr(a, "aria-label") || attr(a, "title") || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120)
      .toLowerCase();
  // Roughly the site's own domain: example.com, or bbc.co.uk. The backend checks it exactly.
  const baseDomain = (host) => {
    const parts = host.split(".");
    const keep = /^(co|com|org|net|ac|gov|edu|ne|or)\.[a-z]{2}$/.test(parts.slice(-2).join(".")) ? 3 : 2;
    return parts.slice(-keep).join(".");
  };
  const sameSite = (url) => baseDomain(new URL(url).hostname) === baseDomain(location.hostname);
  // The page's own footer, not a footer inside a post or comment (WordPress wraps each comment's
  // author links in one).
  const inSiteFooter = (a) => {
    const footer = a.closest("footer, [role='contentinfo']");
    return footer !== null && (footer.matches("[role='contentinfo']") || !footer.parentElement?.closest("article, aside, main, [role='main']"));
  };

  function scanLinks() {
    const scores = new Map();
    const optOuts = [];
    for (const a of all("a[href]")) {
      const url = clean(attr(a, "href"));
      if (!url || url === here()) continue;
      const text = label(a);
      const { pathname } = new URL(url);
      if (OPT_OUT.test(text)) {
        // Only links to the site's own pages: an opt-out link to anywhere else could be a lookalike form.
        if (sameSite(url)) optOuts.push({ url, rank: inSiteFooter(a) ? 1 : 0 });
        continue;
      }
      const relPolicy = (attr(a, "rel") ?? "").split(/\s+/).includes("privacy-policy");
      if (!relPolicy && NOT_POLICY.test(text) && !/policy|notice|statement/.test(text) && !/privacy/i.test(pathname)) continue;
      let score = 0;
      if (relPolicy) score = 12;
      else if (/^(our |global |online |website )?privacy( policy| notice| statement)?$/.test(text)) score = 10;
      else if (/privacy (policy|notice|statement)/.test(text)) score = 8;
      else if (PRIVACY_WORD.test(text)) score = 4;
      if (/privacy|datenschutz|confidentialit|privacidad/i.test(pathname)) score += score ? 2 : 3; // an icon link with no text
      if (!score) continue;
      if (sameSite(url)) score += 20; // the site's own policy first
      else if (!inSiteFooter(a)) continue; // another site's policy only from the site's own footer
      scores.set(url, Math.max(score, scores.get(url) ?? 0));
    }
    const policyUrls = [...scores]
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_LINKS)
      .map(([url]) => url);
    const optOutUrl = optOuts.sort((a, b) => b.rank - a.rank)[0]?.url ?? null; // ties keep page order
    return { policyUrls, optOutUrl };
  }

  // A page that is itself a privacy policy is read from the browser, so nothing is fetched. It's
  // read without a click only when the address says it's the policy and the title or main heading
  // agrees: a title alone isn't enough (a webmail tab showing an email titled "Updates to our
  // Privacy Policy" would count).
  function isPolicyPage() {
    if (!/privacy[-_]?(policy|notice|statement)|\/privacy(\/|\.html?$|$)/i.test(location.pathname)) return false;
    const headings = [docGet("title"), ...Array.from(all("h1"), (h) => h.textContent)].join(" ");
    if (!/privacy (policy|notice|statement)|data (protection|privacy) (policy|notice)/i.test(headings)) return false;
    const text = docGet("body")?.innerText ?? "";
    return text.length > 3000 && /personal (information|data)/i.test(text) && /\bcollect/i.test(text);
  }

  // Hostnames of other sites this page loaded something from: the requests the browser actually
  // made, plus script, frame and image tags. Scripts a consent manager is holding back (marked
  // type="text/plain" until the visitor agrees) haven't loaded, so they don't count.
  function thirdPartyHosts() {
    const hosts = new Set();
    const add = (url) => {
      try {
        const { protocol, hostname } = new URL(url, location.href);
        if ((protocol === "https:" || protocol === "http:") && hostname.length <= 253 && baseDomain(hostname) !== baseDomain(location.hostname)) {
          hosts.add(hostname);
        }
      } catch {
        // not a URL
      }
    };
    for (const entry of performance.getEntriesByType("resource")) add(entry.name);
    for (const el of all("script[src], iframe[src], img[src]")) {
      const type = el.localName === "script" ? (attr(el, "type") ?? "") : "";
      if (!type || /javascript|ecmascript|module/i.test(type)) add(attr(el, "src"));
    }
    return [...hosts].slice(0, MAX_HOSTS);
  }

  // A field's label, from the label's own words only: never the text of a field inside it (a
  // select's options or a textarea's contents).
  function labelText(field) {
    const fieldLabel = field.labels?.[0];
    if (!fieldLabel) return "";
    const walker = Document.prototype.createTreeWalker.call(document, fieldLabel, NodeFilter.SHOW_TEXT);
    let text = "";
    while (walker.nextNode() && text.length < 200) {
      const parent = walker.currentNode.parentElement;
      if (parent && !parent.closest("select, textarea, option, [contenteditable]")) text += `${walker.currentNode.nodeValue} `;
    }
    return text;
  }

  // What the page says a field is for: its type, attributes and label, all written by the page.
  // Never the field's value (what's in it), and never its value attribute (which a site can fill
  // in with the user's own email or name).
  function describe(field) {
    return [field.type, ...["autocomplete", "name", "id", "placeholder", "aria-label"].map((name) => attr(field, name)), labelText(field)]
      .filter(Boolean)
      .join(" ")
      .slice(0, 300);
  }

  function formFields() {
    const asksFor = new Set();
    const insecure = new Set();
    for (const field of Array.from(all(FIELDS)).slice(0, MAX_FIELDS)) {
      if (field.checkVisibility && !field.checkVisibility()) continue;
      if (/one-time-code/.test(attr(field, "autocomplete") ?? "")) continue; // a login code, not personal data
      const kind = field.type === "password" ? "password" : FIELD_KINDS.find(([, pattern]) => pattern.test(describe(field)))?.[0];
      if (!kind) continue;
      asksFor.add(kind);
      if (!SENSITIVE.has(kind)) continue;
      let sendsTo = location.protocol;
      try {
        if (field.form) sendsTo = new URL(attr(field.form, "action") || location.href, location.href).protocol;
      } catch {
        // an unparsable form action: judge by the page alone
      }
      if (location.protocol === "http:" || sendsTo === "http:") insecure.add(kind);
    }
    return { asksFor: [...asksFor], insecureFields: [...insecure] };
  }

  function report() {
    try {
      const { policyUrls, optOutUrl } = scanLinks();
      const { asksFor, insecureFields } = formFields();
      chrome.runtime
        .sendMessage({
          type: "page",
          origin: location.origin,
          policyUrls,
          optOutUrl,
          isPolicyPage: isPolicyPage(),
          thirdPartyHosts: thirdPartyHosts(),
          asksFor,
          insecureFields,
        })
        .catch(() => {});
    } catch {
      // A hostile page broke something, or the extension was reloaded: report nothing rather
      // than something wrong.
    }
  }

  // Listen first, so "Check this page" works even if a report fails.
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "read-page") {
      sendResponse({ text: (docGet("body")?.innerText ?? "").slice(0, MAX_TEXT), url: here() });
    }
  });

  // Report now, once more after trackers and footers drawn by JavaScript have loaded, and again
  // when Back or Forward restores the page from the browser's cache.
  report();
  setTimeout(report, 3000);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) report();
  });
})();
