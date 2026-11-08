# Dossier Privacy Check (browser extension)

On every site you visit, it tells you what the site's privacy policy says the company collects, whether it sells or shares your data, and what the page itself does: which trackers it loads, what personal data its forms ask for, and whether it's a people-search site. It works even when a site has no privacy policy. The analysis runs on this laptop.

## Install (Chrome or Edge)

1. Start the backend: `cd backend`, then `uvicorn app.main:app --reload` (it must be on port 8000).
2. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
3. Click **Load unpacked** and pick this `extension/` folder.
4. Pin the extension, then reload any tabs that were already open.

The local LLM pass also needs Ollama running with `OLLAMA_MODEL` pulled, as for the rest of the app. Without it, you still get the rules-based check.

## What you see

- **Toolbar badge:** `!!` high risk, `!` some risk, `?` the policy couldn't be read. No badge means nothing concerning was seen. Finding nothing isn't proof a site is safe, so there's no green "OK". No badge also means the site isn't checkable (this computer, the local network, browser pages) or the backend isn't running.
- **Popup:**
  - The overall risk, then each risk with its evidence: the policy sentence, or what was seen on the page.
  - A **people-search site** banner on sites in `backend/app/data/brokers.json`, with "Scan yourself with Dossier" and the site's opt-out page.
  - **What this page does:** known trackers it loaded (session recorders, data brokers, ad and social trackers, analytics), the kinds of personal data its forms ask for and whether they're sent without https, and how many ad companies its `ads.txt` lets sell its ads.
  - From the policy: what it says it collects, its selling and sharing clauses, and any "we do not sell" statement.
  - An opt-out button that names where it goes, when the site's own pages or footer have a "Do Not Sell or Share" link.
- **Check this page:** if the site blocks the backend, or its policy needs JavaScript, open the policy and click this. The extension reads the text already on your screen, so nothing is fetched.
- **Check every site I visit** (on by default): judges each page from what your browser already loaded (trackers, form fields, people-search sites) and **contacts no site**.
- **Also read each site's policy automatically** (off by default): reading a policy sends one request from this computer straight to the site. That request goes outside any VPN or proxy set up only in your browser, and it says it's from Dossier. Opening the popup always reads it.

## How it works

```
page (content.js) --links, hostnames, field kinds--> service worker --> backend on 127.0.0.1:8000 --> the site itself
                                                                        (app/site_policy.py)          (GET, logged)
                                                                                |
                                                                                +--> Ollama on localhost
```

1. `content.js` reads the page and makes no network requests. It collects the privacy-policy links and any "Do Not Sell or Share" link, the **hostnames** of other sites the page loaded things from, and the **kinds** of personal data its form fields ask for.
2. `background.js` sends those, with the site's origin (`https://www.example.com`, never the full URL), to `POST /api/site-policy`.
3. The backend reads the policy **straight from the site you're on**, through `outbound.py`, so it shows in the outbound log as service `website`. **Only that site is contacted.** A policy link or a redirect to another site isn't followed automatically (open that policy and choose "Check this page"), and no search API is involved. When you're already on the policy page, the extension sends that page's text instead and nothing is fetched at all.
4. **On every visit**, the backend contacts no site (`read_policy: false`): it judges the page's trackers, form fields and people-search status, and reuses a policy result you already asked for.
5. **When you open the popup**, the policy is read and gets the quick pass:
   - Fixed rules read the policy: what it says is collected (each with a verbatim sentence), Stage 4's sale and sharing checks, and a "we do not sell" statement.
   - The page's tracker hostnames are matched against `backend/app/data/trackers.json`, a hand-written list of well-known trackers.
   - The site is looked up in `brokers.json`.
   - All of it becomes risks. "Couldn't find a privacy policy" is one of them, but only when no policy was found and the page collects something.
6. **Also when you open the popup:**
   - The backend reads the site's `ads.txt`: one more GET to the same site, same rules.
   - Stage 4's Ollama prompt picks more sale and sharing sentences.
   - The popup polls until both are done.
   - Keeping the LLM out of the automatic check means browsing doesn't keep an 8B model busy.

## Risk review: what each feature reads and sends

| Feature | Reads | Sends, and where | How it's kept safe | Tested by |
|---|---|---|---|---|
| Policy check | the policy page | one GET to the visited site, only when you open the popup (or turn on automatic reads); nothing when you're on the policy page | public https only; links and redirects can't leave the site; no cookies kept; 2 MB cap, including against stacked compression | `test_site_policy.py`, `test_the_automatic_check_contacts_no_site` |
| Trackers | URLs the page already loaded | their **hostnames only**, to the backend on this laptop | `content.js` keeps only the hostname. The backend also drops anything that isn't a bare hostname (a URL, an email), and the result isn't stored | `test_only_bare_hostnames…`, browser test (an email in a pixel URL never reaches storage) |
| Form fields | each field's type, autocomplete hint, name and label, all written by the page | fixed words (`email`, `card`…), to the backend | never reads a field's value or `value` attribute; the backend rejects anything not on the fixed list | browser test (typed and site-filled values never reach storage), `test_only_…field_kinds` |
| People-search sites | the site's domain | nothing | lookup in the checked-in `brokers.json`; worded "it may have one about you" | `test_people_search_sites…` |
| No policy | the results above | nothing | only when no policy was found (not when it couldn't be read) and the page collects something; worded "couldn't find" | `test_no_policy_…`, `test_a_policy_that_couldnt_be_read…` |
| ads.txt | the site's `/ads.txt` | one GET to the visited site, when you open the popup | same rules as the policy fetch; read once per site; parsed as data only | `test_ads_txt_…` |

## Privacy

- The extension talks only to the backend on this laptop (`host_permissions` in `manifest.json`). The backend refuses calls that come from a web page. The extension doesn't run in incognito windows.
- Results live in memory only: the backend's cache (6 hours, per hostname) and the browser's session storage, which is cleared when the browser closes. A policy's text is dropped once the local LLM pass is done. The page's trackers and form fields aren't kept by the backend at all. The sites you visit are browsing history, so nothing is written to disk or Postgres.
- Every request to a site is a plain GET to the site you're already on, listed in the app's outbound log. No cookies are sent, and none a site sets are kept. Those fetches keep their own log, so browsing can't push a scan's requests out.
- A request to a site comes from this computer's own connection, so it goes outside any VPN or proxy set up only in your browser, and it says it's from Dossier. That's why the automatic check never makes one unless you turn that on.
- Links from pages are untrusted. Only public https links on the visited site are fetched: no localhost names, IP addresses or local names, and no query strings. Every redirect is checked again, and a page is read up to 2 MB. Hostnames aren't resolved first, so the https certificate check is what keeps a hostile link away from devices on your network.
- Policy text can try to steer the local LLM, so the model only picks sentence numbers. Its picks must pass Stage 4's checks, and the popup shows fixed wording, never the model's own explanation.
- The extension reads a policy from your screen without a click only when the page's address and its title or main heading both say it's the privacy policy.

**Known limits:**
- The tracker list is short and hand-written, so it misses trackers rather than inventing them.
- Payment fields inside a payment provider's frame aren't seen, because the extension only reads the top page.
- Requests to sites send the backend's `hack1984/0.1` user agent, so a site can tell this tool fetched its policy. It already knows you visited.

## Before a demo

The outbound log lists every policy and ads.txt the extension fetched. With automatic policy reads off (the default), that's only the sites whose popup you opened. If you turn them on for the demo, clear the log (`DELETE /api/outbound-log`) before you present.

## Files

| File | What it does |
|---|---|
| `manifest.json` | Manifest V3: `storage` permission, the local backend as the only host permission, no incognito |
| `content.js` | Finds policy and opt-out links, tracker hostnames and form field kinds; reads the page text on request |
| `background.js` | Runs the quick check on each visit and sets the badge |
| `shared.js` | The only network code (`BACKEND`), plus the badge and session storage helpers |
| `popup.html`, `popup.css`, `popup.js` | The popup. Scraped text is added as text nodes, never as HTML |
| `icons/` | The Dossier folder-and-keyhole mark |

The backend side is `backend/app/site_policy.py`, `backend/app/clients/website.py` and `backend/app/data/trackers.json`, tested offline in `backend/tests/test_site_policy.py`.

**Debugging:** open `chrome-extension://<id>/popup.html?tab=<tabId>` as a page to see the popup for that tab. Use **Inspect views: service worker** on the extensions page for the background log.

**Recent Chrome ignores the `--load-extension` command-line flag**, so automated tests need Edge, Chromium or Chrome for Testing. Load unpacked works normally.
