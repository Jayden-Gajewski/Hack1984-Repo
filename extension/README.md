# Dossier Privacy Check (browser extension)

On every site you visit, it tells you what the site's privacy policy says the company collects, whether it sells or shares your data, and what the page itself does: which trackers it loads, what personal data its forms ask for, and whether it's a people-search site. It works even when a site has no privacy policy. Fixed rules run on this laptop; when you open the popup, the policy's selling and sharing sentences also go to Google's Gemini, with the site's name.

## Two copies: from the repo, or from the public site

The extension finds Dossier through `config.js`:

- **The copy in this repo** (and the download from the app on a laptop) checks sites with the backend on this laptop. Nothing leaves the laptop except the requests listed below.
- **The copy downloaded from the public site** (`/extension`, signed in) is for people without the repo. `backend/app/extension_package.py` rewrites its `config.js` to point at the public site (`SITE_URL`) and its manifest's only host permission to that site. It checks sites with the user's own account: it sends their session cookie, the outbound log entries land in their account's log, and each account has its own results on the server, kept in memory only. Signed out, the popup asks them to sign in. **Check every site I visit** starts off in this copy, because it would send each site's address to Dossier's server; opening the popup still checks the site. The site fetches come from Dossier's server, not from the user's computer. The AI pass is capped at 100 a day per account (2,000 for everyone together, counted in the backend's memory); past that the popup shows the rules-based check.

## Install from the public site (no repo needed)

1. Sign in on the public site, open `/extension` and download the zip. Unzip it somewhere you'll keep it.
2. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
3. Click **Load unpacked** and pick the `dossier-privacy-check` folder.
4. Pin the extension, then reload any tabs that were already open. Stay signed in to the site in the same browser.

## Install from the repo (Chrome or Edge)

1. Start the backend: `cd backend`, then `uvicorn app.main:app --reload` (it must be on port 8000).
2. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
3. Click **Load unpacked** and pick this `extension/` folder.
4. Pin the extension, then reload any tabs that were already open.

The LLM pass needs `GEMINI_API_KEY` in `.env`, as for the rest of the app. Without it, you still get the rules-based check.

## What you see

- **Toolbar badge:** `!!` high risk, `!` some risk, `?` the policy couldn't be read. No badge means nothing concerning was seen. Finding nothing isn't proof a site is safe, so there's no green "OK". High is kept for what would expose you directly: the policy says it sells your data or passes it to data brokers, it's a people-search site, it asks for sensitive data without https, or it has no policy but asks for an SSN, bank, ID or card number. Tags a page loads (session recorders, ad and data-broker pixels) say what it *can* do, so they top out at medium. No badge also means the site isn't checkable (this computer, the local network, browser pages) or the backend isn't running.
- **Popup:** three tabs along the bottom, **This site**, **Sites** and **Settings**, with the site you're on in the header (its first letter tinted by its risk, the time it was checked, and buttons to check again and open the Dossier app).
  - **This site** opens on a verdict card: the overall risk, the main risk in a sentence, and the opt-out button when the site has one. Under it, four tiles count the risks, the trackers, the kinds of data the policy says it collects, and its selling and sharing clauses. Pick a tile (or use the arrow keys) to see its list below. A tile shows "–" when the policy wasn't read, because nobody knows the count.
  - Each risk with its evidence (the policy sentence, what was seen on the page, or both) and a **How Dossier knows** line: what kind of evidence it is and what wasn't read.
  - **Promises that don't add up:** when the policy says it doesn't sell your data but the page loads ad trackers or data brokers, both pieces of evidence side by side. It isn't a claim the policy lies: California law calls passing data on for targeted ads "sharing", which a promise not to sell doesn't cover.
  - A **people-search site** banner on sites in `backend/app/data/brokers.json`, with "Scan yourself with Dossier" and the site's opt-out page.
  - **What this page does:** it opens with the visit in plain words ("Loading this page told *5 companies* you were here", and the company Dossier saw on the most other sites you opened). Then the known trackers it loaded (session recorders, data brokers, ad and social trackers, analytics), each with the other sites you opened where Dossier saw it, the kinds of personal data its forms ask for and whether they're sent without https, and how many ad companies its `ads.txt` lets sell its ads.
  - **See what each bidder can be sent:** under the ad sellers, the OpenRTB bid request an ad auction on the page can send, filled in from your browser in the popup and sent nowhere. What only the ad exchange knows (your IP address, where it puts you, its ID for you) stays a labeled placeholder, never a guess.
  - From the policy: what it says it collects, its selling and sharing clauses, and any "we do not sell" statement.
  - An opt-out button, with the address it opens under it, when the site's own pages or footer have a "Do Not Sell or Share" link.
  - **Private email for this site** (at the bottom of This site): when the page asks for an email address, the popup offers an alias just for this site (`shop.1a2b3c@…`). It reuses the one you already made for the site, if any. **Fill in** puts it into the page's email field, only when you click it; **Copy** copies it. You need to be signed in to Dossier (localhost:3000) in the same browser, because aliases belong to your account. Only the site's hostname is sent, to the app on this laptop.
  - **Sites:** the sites you opened since the browser started, newest first, each with its risk and how many risks and trackers it had. **Forget the sites I've visited** is here.
- **Check this page:** if the site blocks the backend, or its policy needs JavaScript, open the policy and click this. The extension reads the text already on your screen, so nothing is fetched.
- **Settings:** the two switches below, and how your data is handled.
- **Check every site I visit** (on by default in the repo's copy, off in the public site's): judges each page from what your browser already loaded (trackers, form fields, people-search sites) and **contacts no site**. In the public site's copy it sends the site's address, tracker hostnames and field kinds to Dossier's server, which keeps nothing from it.
- **Also read each site's policy automatically** (off by default): reading a policy sends one request from this computer straight to the site. That request goes outside any VPN or proxy set up only in your browser, and it says it's from Dossier. Opening the popup always reads it.
- **Forget the sites I've visited:** clears every site result and page report from the browser's session storage, and calls `DELETE /api/site-policy`, which drops the backend's results and every outbound log entry the extension caused (its purpose starts with `Browser extension: `). The popup then says what was and wasn't cleared: requests already made can't be recalled. Each site saw its policy read, and Gemini got the site's name and policy sentences for each popup you opened.

## How it works

```
page (content.js) --links, hostnames, field kinds--> service worker --> backend on 127.0.0.1:8000 --> the site itself
                                                                        (app/site_policy.py)          (GET, logged)
                                                                                |
                                                                                +--> Google's Gemini (popup only, logged)
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
   - Stage 4's Gemini prompt picks more sale and sharing sentences. The prompt holds the site's name and the policy's selling and sharing sentences, nothing from you.
   - The popup polls until both are done.
   - Keeping the LLM out of the automatic check means browsing doesn't tell Google which sites you visit.
7. **In the popup only,** it reads the other sites' results in session storage to count where else each tracker appeared, and builds the sample bid request from `navigator` and `screen`. Neither is sent anywhere.

## Risk review: what each feature reads and sends

| Feature | Reads | Sends, and where | How it's kept safe | Tested by |
|---|---|---|---|---|
| Policy check | the policy page | one GET to the visited site, only when you open the popup (or turn on automatic reads); nothing when you're on the policy page | public https only; links and redirects can't leave the site; no cookies kept; 2 MB cap, including against stacked compression | `test_site_policy.py`, `test_the_automatic_check_contacts_no_site` |
| Trackers | URLs the page already loaded | their **hostnames only**, to the backend on this laptop | `content.js` keeps only the hostname. The backend also drops anything that isn't a bare hostname (a URL, an email), and the result isn't stored | `test_only_bare_hostnames…`, browser test (an email in a pixel URL never reaches storage) |
| Form fields | each field's type, autocomplete hint, name and label, all written by the page | fixed words (`email`, `card`…), to the backend | never reads a field's value or `value` attribute; the backend rejects anything not on the fixed list | browser test (typed and site-filled values never reach storage), `test_only_…field_kinds` |
| People-search sites | the site's domain | nothing | lookup in the checked-in `brokers.json`; worded "it may have one about you" | `test_people_search_sites…` |
| No policy | the results above | nothing | only when no policy was found (not when it couldn't be read) and the page collects something; worded "couldn't find" | `test_no_policy_…`, `test_a_policy_that_couldnt_be_read…` |
| Private email | whether the page asks for an email (the field kinds above) | the site's **hostname**, to the Dossier app on this laptop (`GET`/`POST /api/aliases`, your session cookie), only when the popup is open; the alias goes into the page only when you click "Fill in" | the backend accepts the extension's origin on those two routes only and still needs a signed-in session; the hostname is normalized again by the backend; `content.js` only writes an alias-shaped address and reads nothing back | `test_extension_may_list_and_make_aliases…`, `test_extension_origin_is_refused_everywhere_else` |
| ads.txt | the site's `/ads.txt` | one GET to the visited site, when you open the popup | same rules as the policy fetch; read once per site; parsed as data only | `test_ads_txt_…` |
| Promises that don't add up | the policy's "we do not sell" sentence and the page's trackers | nothing | only with ad or data-broker trackers, and never when the policy also says it sells; worded "can't see what those tags send" | `test_a_promise_not_to_sell_…` |
| Where else a tracker was seen | the other sites' results in session storage | nothing | counted and shown in the popup only; "also saw", never "followed"; gone when the browser closes or you choose Forget | screenshot harness (not checked in) |
| Sites list | the site results in session storage | nothing | shown in the popup only; gone when the browser closes or you choose Forget | screenshot harness (not checked in) |
| Sample bid request | `navigator.userAgent`, screen size, language, time zone offset | nothing | built in the popup; what only the exchange knows stays a labeled placeholder | screenshot harness (not checked in) |
| Forget | the session storage keys `site:*` and `tab:*` | `DELETE /api/site-policy` to the backend on this laptop | refuses web-page origins; drops only the extension's log entries, so a scan's stay | `test_forgetting_drops_every_site_…` |

## Privacy

- The extension talks only to Dossier: in the repo's copy, the backend on 127.0.0.1:8000 and the app on localhost:3000 for private emails; in the public site's copy, that site only, with the user's session (`host_permissions` in `manifest.json`). The backend refuses calls that come from a web page. The extension doesn't run in incognito windows.
- Results live in memory only: the backend's cache (6 hours, per hostname) and the browser's session storage, which is cleared when the browser closes. A policy's text is dropped once the Gemini pass is done. The page's trackers and form fields aren't kept by the backend at all. The sites you visit are browsing history, so nothing is written to disk or Postgres.
- Every request to a site is a plain GET to the site you're already on, listed in the app's outbound log. No cookies are sent, and none a site sets are kept. Those fetches keep their own log, so browsing can't push a scan's requests out.
- A request to a site comes from this computer's own connection, so it goes outside any VPN or proxy set up only in your browser, and it says it's from Dossier. That's why the automatic check never makes one unless you turn that on.
- Links from pages are untrusted. Only public https links on the visited site are fetched: no localhost names, IP addresses or local names, and no query strings. Every redirect is checked again, and a page is read up to 2 MB. Hostnames aren't resolved first, so the https certificate check is what keeps a hostile link away from devices on your network.
- The Gemini pass sends Google the site's name and the policy's selling and sharing sentences, so Google learns which sites' popups you opened. On Gemini's free tier, Google may use what it's sent to improve its products. It's in the outbound log as service `gemini`.
- Policy text can try to steer the LLM, so the model only picks sentence numbers. Its picks must pass Stage 4's checks, and the popup shows fixed wording, never the model's own explanation.
- The extension reads a policy from your screen without a click only when the page's address and its title or main heading both say it's the privacy policy.

**Known limits:**
- The tracker list is short and hand-written, so it misses trackers rather than inventing them.
- Payment fields inside a payment provider's frame aren't seen, because the extension only reads the top page.
- Requests to sites send the backend's `hack1984/0.1` user agent, so a site can tell this tool fetched its policy. It already knows you visited.

## Before a demo

The outbound log lists every policy and ads.txt the extension fetched. With automatic policy reads off (the default), that's only the sites whose popup you opened. If you turn them on for the demo, clear the log (`DELETE /api/outbound-log`) before you present, or press **Forget the sites I've visited** in the popup, which clears only the extension's entries and keeps the scan's.

## Files

| File | What it does |
|---|---|
| `manifest.json` | Manifest V3: `storage` permission, Dossier on this laptop as the only host permissions (the public site's copy: that site), no incognito |
| `config.js` | Where Dossier is: this laptop, or, rewritten in the public site's download, that site |
| `content.js` | Finds policy and opt-out links, tracker hostnames and form field kinds; reads the page text on request |
| `background.js` | Runs the quick check on each visit and sets the badge |
| `shared.js` | The only network code (addresses from `config.js`), plus the badge and session storage helpers |
| `popup.html`, `popup.css`, `popup.js` | The popup. Scraped text is added as text nodes, never as HTML |
| `icons/` | The Dossier folder-and-keyhole mark |

The backend side is `backend/app/site_policy.py`, `backend/app/clients/website.py` and `backend/app/data/trackers.json`, tested offline in `backend/tests/test_site_policy.py`.

**Debugging:** open `chrome-extension://<id>/popup.html?tab=<tabId>` as a page to see the popup for that tab. Use **Inspect views: service worker** on the extensions page for the background log.

**Recent Chrome ignores the `--load-extension` command-line flag**, so automated tests need Edge, Chromium or Chrome for Testing. Load unpacked works normally.
