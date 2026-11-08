# Threat monitor

A second section of the app, at `/app/monitor` (the app bar switches between **Exposure scan** and **Threat monitor**). It tracks known breaches at the companies you use and at the email addresses you've proven you own, rates each one, and gives you a checklist of steps.

The exposure scanner asks "where is my data public right now?" The threat monitor asks "which breaches could have put it there, and what should I do about each one?"

## What works with no setup

Add companies on the **What we watch** tab, then press **Scan now**:

- HIBP's whole public breach list (about 1,000 breaches) is downloaded, and your companies are matched against it on this laptop. No key is needed. HIBP never learns which companies you use, because the download is the same for everyone.
- Each match becomes an incident card with:
  - the breach date and the date HIBP added it, each with its source;
  - the account count and the exposed data types;
  - a severity rating and an evidence rating;
  - a checklist of recommended steps.
- **Explain with local AI** asks Ollama on this laptop for a plain-English summary. The summary is checked against the evidence before it's shown.

Tested live: LinkedIn, Canva, AT&T, Experian and Instagram all match real HIBP breaches. Discord and Google have none. Discord.io, a different site, is correctly not matched to Discord.

## Optional setup (`.env` at the repo root)

| Feature | Setting | Without it |
|---|---|---|
| News and official notices (Stage 3: Tavily, Exa, state AG sites) | `TAVILY_API_KEY` or `EXA_API_KEY`, plus Ollama running | The checkbox and "Search news & notices" button are disabled, with the reason shown |
| Email checks | `HIBP_API_KEY` on a **Pro or High RPM** plan; the hashed search isn't on cheaper plans | Verified emails show "needs an HIBP Pro key". Never "safe", never fake results |
| Email ownership codes | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Emails can be added but not verified, and unverified emails are never checked |
| Local AI explanations | Ollama with `OLLAMA_MODEL` pulled | The button is disabled: "Start Ollama to use the local AI" |

The setup line under the page title shows which of these are on.

**SMTP examples**
- **Gmail:** `smtp.gmail.com`, port `587`, your address as username, and an [app password](https://support.google.com/accounts/answer/185833), never your account password.
- **Local test catcher:** [Mailpit](https://mailpit.axllent.org/) on `localhost:1025` with no username. The mail never leaves the laptop, which suits a demo.
- **TLS rule:** a remote server must offer TLS (port 465, or STARTTLS on other ports), or the send is refused. Only `localhost` may skip it.

## Privacy: what leaves the laptop

Everything below goes through `backend/app/outbound.py` and appears in the outbound-log drawer.

| To | What's sent | When |
|---|---|---|
| haveibeenpwned.com `/breaches` | Nothing personal (the same download for everyone) | Each refresh; cached for 30 min |
| haveibeenpwned.com `/breachedaccount/range/{prefix}` | The first 6 hex characters of a verified email's SHA-1 hash, plus the API key (redacted in the log) | Each refresh with verified emails |
| Your SMTP server | The address you typed, plus a message with a 6-digit code (redacted in the log) | When you add an address or ask for a new code |
| Tavily, Exa | The company name only, through Stage 3, unchanged | Only with news search on |
| Tavily Extract | One public URL: the company's official breach notice | Only when explaining a breach HIBP has no description for |
| Ollama (localhost) | Breach evidence, and whether you're confirmed in it. Never your address | Explain with local AI; news search |

**What stays on the laptop:**
- Everything is saved in `backend/local/monitor.json`, which is gitignored.
- An email address is stored in full only until it's verified. After that, only its SHA-1 hash (needed for the check) and a masked form (`j•••e@example.com`) are kept.
- Verification codes are stored as salted hashes. They expire after 15 minutes and allow 5 tries.
- For the hashed email search, HIBP returns every hash suffix under the prefix. Suffixes that don't belong to your address are discarded at once, as HIBP's terms require, and never stored or logged.
- An address that's never verified is deleted a day after its last code expired.
- The app never asks for or stores an account password.

**Limits of the hashed search, stated plainly:**
- HIBP knows who owns the API key, so it can tie prefix queries to the key's subscriber. The prefix doesn't reveal the address.
- The stored SHA-1 isn't anonymous: anyone with `monitor.json` who guesses an address can confirm it. That's why the file stays local and gitignored.
- The outbound log shows the SMTP recipient in full, because that's exactly what was sent. It's in memory, so it stays until the log is cleared or the backend restarts. For a demo, use Mailpit or a `.example` address, or clear the log after verifying.

## How incidents are rated

Three separate answers, all set by rules in code (`backend/app/monitor/severity.py`). The local LLM only explains them.

- **Severity** is how much harm the breach could do to someone in it.
  1. It starts from the worst data exposed (tiers in `backend/app/data/breach_data_classes.json`):
     - government IDs, card numbers and recovery phrases are critical;
     - passwords, login tokens and health data are high;
     - email, phone, address and date of birth are medium;
     - names, usernames and device data are low.
  2. Names, dates of birth and contact details together raise it to at least high.
  3. If your verified email is confirmed in the breach, it goes up one level.
  4. If HIBP flags it as fabricated, it drops to low. A spam list is capped at medium. A breach reported by only one unofficial source can't be critical.
- **Evidence** is how well the incident itself is documented. Verified by HIBP, or an official notice, is "well evidenced". Unverified in HIBP, or two independent reports, is "partly evidenced". One unofficial report is "thinly evidenced".
- **Involvement:**
  - "Your email is in it": only a verified email's hashed HIBP match.
  - "Not found for your email": every verified address was checked and isn't listed.
  - "Not confirmed for you": everything else. A company announcing a breach never confirms that *you* were in it, and the card says so.

A breach can be **critical** and **not confirmed for you** at the same time. The split pill on each card shows both.

## AI explanations and their checks

`backend/app/monitor/analysis.py` sends Ollama the evidence plus the rules' answers. Before the explanation is saved, it drops:

- any sentence with a number that isn't in the evidence ("5 million" when HIBP says 120,000);
- "your data was exposed" style claims unless you're confirmed in the breach (hedged sentences like "if your password was exposed…" stay);
- "leaked by" and "who leaked" wording.

It also:

- replaces a severity explanation that names a different level with the rules' own reasons;
- empties the advice field when the sources contain no advice;
- adds a note when the sources call the breach "alleged" or "denied" and the summary dropped that.

The card says how many sentences were removed. An explanation is marked stale when the incident's facts change.

## Steps, alerts and history

- **Steps** are saved per incident. Checking one records what you did. It never marks an account as secure, and the card says so.
- **Alerts:**
  - A new incident is reported once.
  - Incident ids are stable (`hibp-<name>`, `news-<company>-<year>`). When a news report and an HIBP breach describe the same incident, they merge, so a breach first seen in the news isn't alerted again when HIBP adds it. Its steps carry over.
  - A newly confirmed email match is a separate alert.
- **Scheduled checks** (History tab) run every 6 h, 12 h, 1 day or 1 week.
  - They run as a loop inside the backend, **only while it's running**, and the UI says so.
  - They include news searches only if you tick that option, because those spend credits.
- **History** keeps the last 300 events, also in `monitor.json`.

## Link to the exposure scanner

- Each card links to the scanner ("Run an exposure scan"), or offers "load your last scan" so the two can be compared.
- With a scan loaded, a card lists the listings that show data this breach exposed. Stage 5's own rule decides whether the company counts as a **Likely** source for a listing (breach 0–3 years before the listing went public, with a shared field).
- Overlap alone is described as overlap, never as proof that the breach caused the listing.

## Developer notes

- **Code:**
  - Backend: `backend/app/monitor/` (pure modules first: `breach_data`, `incidents`, `severity`, `checklist`), `backend/app/clients/hibp.py`, and the routes under `/api/monitor/*` in `backend/app/monitor/routes.py`.
  - Frontend: `frontend/app/app/monitor/page.tsx` and components `IncidentCard`, `MonitoredCompanies`, `MonitoredEmails`, `MonitorActivity`, `CompanyMark`, `RadarScope`.
- **Tests:** `cd backend && pytest tests/test_monitor_*.py`. They're offline: HIBP, SMTP, Stage 3 and Ollama are faked, and the store goes to a temp dir (`tests/conftest.py`).
- **Reference data:** `breach_data_classes.json` maps all of HIBP's data classes (`GET /api/v3/dataclasses`) to categories. An unknown class falls back to "profile" (low). Saved incidents re-derive their categories when shown, so editing the file applies everywhere.
- **Licensing:** HIBP data is CC BY 4.0. Threat rows and the Threats tab show "Have I Been Pwned" with a link.

## Not built yet

- Email checks without a Pro plan. The full-address lookup was left out on purpose (privacy rule 3).
- Browser or desktop notifications. Alerts appear in the app, and scheduled checks show up within 30 s while the page is open.
- Per-account (multi-user) monitor data. Like scans, the monitor is single-user per laptop. The API routes are gated only by the UI's login, as with the rest of the app.
