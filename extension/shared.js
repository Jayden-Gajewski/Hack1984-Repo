// Shared by the service worker and the popup. The extension's only network calls are here, and
// they go to the Dossier backend on this laptop. If you run the backend on another port, change
// BACKEND and the host_permissions in manifest.json to match.
export const BACKEND = "http://127.0.0.1:8000";
// The Dossier app on this laptop, for "scan yourself" on a people-search site. Only opened as a
// link, with nothing added to it.
export const APP_URL = "http://localhost:3000/app";

export class Offline extends Error {}

/** Public websites only: not this computer, an IP address or the local network. */
export function isCheckable(origin) {
  try {
    const { protocol, hostname } = new URL(origin);
    if (protocol !== "https:" && protocol !== "http:") return false;
    if (hostname === "localhost" || /\.(localhost|local|internal|lan|home|corp|intranet)$/.test(hostname)) return false;
    if (/^[\d.]+$/.test(hostname) || hostname.includes(":") || hostname.startsWith("[")) return false;
    return hostname.includes(".");
  } catch {
    return false;
  }
}

/**
 * Ask the backend what this site's privacy policy says.
 * page: what content.js reported (origin, links, tracker hostnames, form field kinds).
 * pageText: {text, url} when the policy is the page open in the browser (then nothing is
 * fetched from the site). Resolves to the backend's SitePolicyResponse (backend/app/models.py).
 */
export async function checkPage(page, { deep = false, refresh = false, pageText = null, readPolicy = true } = {}) {
  const body = {
    origin: page.origin,
    policy_urls: pageText ? [pageText.url] : (page.policyUrls ?? []),
    opt_out_url: page.optOutUrl ?? null,
    page_text: pageText?.text ?? null,
    deep,
    refresh,
    read_policy: readPolicy, // false: contact no site, judge only what the browser saw

    third_party_hosts: page.thirdPartyHosts ?? [],
    asks_for: page.asksFor ?? [],
    insecure_fields: page.insecureFields ?? [],
  };
  let res;
  try {
    res = await fetch(`${BACKEND}/api/site-policy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Offline("The Dossier backend isn't running.");
  }
  if (!res.ok) {
    let detail = `The backend answered HTTP ${res.status}.`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/** The text of the page open in a tab, from content.js, or null. */
export async function readPage(tabId) {
  try {
    const reply = await chrome.tabs.sendMessage(tabId, { type: "read-page" }, { frameId: 0 });
    return reply?.text ? reply : null;
  } catch {
    return null;
  }
}

// Results are kept in session storage: in memory, and gone when the browser closes, because the
// list of sites you visit is browsing history.
const siteKey = (origin) => `site:${new URL(origin).hostname.replace(/^www\./, "")}`;

export async function rememberResult(origin, result) {
  const entry = { [siteKey(origin)]: result };
  try {
    await chrome.storage.session.set(entry);
  } catch {
    // Session storage is full (about 10 MB after a long day of browsing): forget the other sites.
    const all = await chrome.storage.session.get(null);
    await chrome.storage.session.remove(Object.keys(all).filter((key) => key.startsWith("site:")));
    await chrome.storage.session.set(entry).catch(() => {});
  }
}

export async function cachedResult(origin) {
  const key = siteKey(origin);
  return (await chrome.storage.session.get(key))[key] ?? null;
}

/**
 * Where else Dossier saw each tracker company: the other sites with a result in session storage,
 * which are the sites you opened since the browser started (while "Check every site I visit" was
 * on, or whose popup you opened). Read here and shown in the popup; it's never sent anywhere.
 * Resolves to {byCompany, byTracker}: Maps from a company or tracker name to a Set of sites.
 */
export async function sightings(origin) {
  const here = siteKey(origin);
  const byCompany = new Map();
  const byTracker = new Map();
  const add = (map, name, site) => {
    if (typeof name !== "string") return;
    if (!map.has(name)) map.set(name, new Set());
    map.get(name).add(site);
  };
  for (const [key, result] of Object.entries(await chrome.storage.session.get(null))) {
    if (!key.startsWith("site:") || key === here || !Array.isArray(result?.trackers)) continue;
    const site = key.slice("site:".length);
    for (const tracker of result.trackers) {
      add(byCompany, tracker?.company, site);
      add(byTracker, tracker?.name, site);
    }
  }
  return { byCompany, byTracker };
}

/**
 * The sites with a result in session storage, newest check first, for the popup's Sites view.
 * Read here and shown in the popup; it's never sent anywhere. Resolves to [{site, result}].
 */
export async function visitedSites() {
  return Object.entries(await chrome.storage.session.get(null))
    .filter(([key, result]) => key.startsWith("site:") && result && typeof result === "object")
    .map(([key, result]) => ({ site: key.slice("site:".length), result }))
    .sort((a, b) => String(b.result.checked_at ?? "").localeCompare(String(a.result.checked_at ?? "")));
}

/**
 * "Forget the sites I've visited": every site result and page report in session storage, then the
 * backend's results and its log entries for those sites. Resolves to how many sites this browser
 * held and what the backend did: "cleared", "offline" or "failed" (with a detail).
 */
export async function forgetSites() {
  const keys = Object.keys(await chrome.storage.session.get(null)).filter((key) => /^(site|tab):/.test(key));
  await chrome.storage.session.remove(keys);
  const sites = keys.filter((key) => key.startsWith("site:")).length;
  let res;
  try {
    res = await fetch(`${BACKEND}/api/site-policy`, { method: "DELETE" });
  } catch {
    return { sites, backend: "offline" };
  }
  if (!res.ok) return { sites, backend: "failed", detail: `The backend answered HTTP ${res.status}.` };
  return { sites, backend: "cleared" }; // not the backend's own counts: they'd overwrite this browser's
}

// Only real concerns get a badge. Finding nothing isn't proof a site is safe, so it shows no
// green "OK", just the tooltip.
const BADGES = {
  high: { text: "!!", color: "#b42318", words: "high privacy risk" },
  medium: { text: "!", color: "#8a5300", words: "some privacy risk" },
};

/** state: a SitePolicyResponse, "checking", "offline" or null (no badge). */
export async function setBadge(tabId, state) {
  let text = "";
  let color = "#545c66";
  let title = "Dossier Privacy Check";
  if (state === "checking") {
    text = "…";
    title = "Dossier: reading this site's privacy policy…";
  } else if (state === "offline") {
    title = "Dossier: start the backend on this laptop to check sites";
  } else if (state && typeof state === "object") {
    const badge = BADGES[state.risk];
    if (badge) {
      ({ text, color } = badge);
      title = `Dossier: ${badge.words} on ${state.site}`;
    } else if (state.status === "unreadable" || state.status === "no_policy") {
      text = "?";
      title = `Dossier: couldn't read ${state.site}'s privacy policy`;
    } else if (state.status === "not_read") {
      title = `Dossier: nothing concerning seen on ${state.site}. Open to read its privacy policy.`;
    } else {
      title = `Dossier: nothing concerning found on ${state.site}`;
    }
  }
  try {
    await chrome.action.setBadgeText({ tabId, text });
    await chrome.action.setBadgeBackgroundColor({ tabId, color });
    await chrome.action.setBadgeTextColor?.({ tabId, color: "#ffffff" });
    await chrome.action.setTitle({ tabId, title });
  } catch {
    // The tab was closed.
  }
}
