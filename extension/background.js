// Dossier service worker. When a page loads, content.js reports the site's privacy links; this
// asks the Dossier backend on this laptop for the quick check and sets the toolbar badge. The
// local LLM pass runs only when you open the popup, so browsing doesn't keep the model busy.
import { checkPage, isCheckable, readPage, rememberResult, setBadge } from "./shared.js";

chrome.runtime.onMessage.addListener((message, sender) => {
  // manifest.json keeps the extension out of incognito windows; this is a second guard.
  if (message?.type === "page" && sender.tab?.id !== undefined && sender.frameId === 0 && !sender.tab.incognito) {
    onPage(sender.tab.id, message);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab:${tabId}`);
});

async function onPage(tabId, page) {
  const key = `tab:${tabId}`;
  const before = (await chrome.storage.session.get(key))[key];
  await chrome.storage.session.set({ [key]: page });
  const { auto = true } = await chrome.storage.local.get("auto");
  if (!auto || !isCheckable(page.origin)) {
    await setBadge(tabId, null);
    return;
  }
  // content.js reports each page twice (again once trackers have loaded): don't flash "…" twice.
  if (before?.origin !== page.origin) await setBadge(tabId, "checking");
  let state;
  try {
    const pageText = page.isPolicyPage ? await readPage(tabId) : null;
    state = await checkPage(page, { pageText });
    await rememberResult(page.origin, state);
  } catch {
    state = "offline";
  }
  // The tab may have moved on to another site while the policy was read.
  const current = (await chrome.storage.session.get(key))[key];
  if (current?.origin === page.origin) await setBadge(tabId, state);
}
