// Dossier service worker. When a page loads, content.js reports what it saw; this asks Dossier (the
// backend on this laptop, or the public site with the user's session: config.js) for a check and
// sets the toolbar badge.
//
// The automatic check contacts no site: it judges what the browser already loaded (trackers, form
// fields, people-search sites), plus any policy result the user already asked for. Reading a
// site's policy is a request from this computer's own connection, outside any VPN or proxy set up
// only in the browser, so it waits until the popup opens, unless the user turns on "Also read each
// site's policy automatically". The Gemini pass also runs only from the popup. In the copy from
// the public site, the automatic check itself is off until the user turns it on (DEFAULTS), since
// it would tell Dossier's server every site they visit.
import { DEFAULTS, SignedOut, checkPage, isCheckable, readPage, rememberResult, setBadge } from "./shared.js";

chrome.runtime.onMessage.addListener((message, sender) => {
  // manifest.json keeps the extension out of incognito windows; this is a second guard.
  if (message?.type !== "page" || sender.tab?.id === undefined || sender.frameId !== 0 || sender.tab.incognito) return;
  // The browser says which site sent the message; use that rather than what the message claims.
  const origin = sender.origin && sender.origin !== "null" ? sender.origin : message.origin;
  onPage(sender.tab.id, { ...message, origin });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab:${tabId}`);
});

async function onPage(tabId, page) {
  const key = `tab:${tabId}`;
  const before = (await chrome.storage.session.get(key))[key];
  await chrome.storage.session.set({ [key]: page });
  const { auto = DEFAULTS.auto, readPolicies = DEFAULTS.readPolicies } = await chrome.storage.local.get(["auto", "readPolicies"]);
  if (!auto || !isCheckable(page.origin)) {
    await setBadge(tabId, null);
    return;
  }
  // content.js reports each page twice (again once trackers have loaded): don't flash "…" twice.
  if (readPolicies && before?.origin !== page.origin) await setBadge(tabId, "checking");
  let state;
  try {
    // A policy page open in the tab is read from the screen: that contacts no site either.
    const pageText = page.isPolicyPage ? await readPage(tabId) : null;
    state = await checkPage(page, { pageText, readPolicy: readPolicies });
    await rememberResult(page.origin, state);
  } catch (error) {
    state = error instanceof SignedOut ? "signed_out" : "offline";
  }
  // The tab may have moved on to another site while the check ran.
  const current = (await chrome.storage.session.get(key))[key];
  if (current?.origin === page.origin) await setBadge(tabId, state);
}
