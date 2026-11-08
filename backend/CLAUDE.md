# Backend

FastAPI app in `app/`. Read the privacy rules in the root `CLAUDE.md` first.

## Conventions

- **Async everywhere.** Run independent calls together with `asyncio.gather(..., return_exceptions=True)`.
- **Network calls go through `outbound.request(...)` only.** It takes:
  - `service`: `"exa"`, `"tavily"`, `"wayback"`, `"gemini"`, `"hibp"`, or `"website"` (a page read straight from a site: the browser extension's policy fetch in `clients/website.py`). Website entries go in their own 200-entry log, so browsing can't push a scan's entries out of the main one.
  - `send_cookies=False` and `max_bytes=...`: optional, used for website fetches (no stored cookies; stop downloading after that many bytes).
  - `purpose`: a plain-English reason shown in the log panel, e.g. `"Find listings on known people-search sites"`. Write it for a non-technical judge.
  - `guard=[query]`: every search query string. The guard rejects emails, phone numbers, SSNs and birthdates.
  - `local=True`: for a call that never leaves the machine. Nothing uses it since the switch from Ollama to Gemini (Gemini calls leave the machine and are logged like any other); the outbound log hides its "stayed on this machine" toggle while there are none.
- **Log what was actually sent.** Each entry records the final URL, the headers that were sent (API keys redacted), the body, the status and the duration. Never log API keys.
- **Partial failure is normal.** A broker blocks extraction, archive.org times out, a key is missing. Stages collect error strings and return them next to their results. One failed source must not fail the whole scan.
- **`models.py` is the contract with the frontend.** Add fields; don't rename or remove them without telling the UI owner, who keeps the types in `frontend/lib/api.ts` in sync.
- **Reference data goes in `app/data/*.json`, and user data in Postgres.** Don't hard-code broker lists or company domains in Python, and don't load reference data into the database.
- **No CORS.** The browser reaches FastAPI only through the Next.js `/api` rewrite (on the public site, Vercel's), so don't add `CORSMiddleware` or `allow_origins=["*"]`. The browser extension (`extension/`) calls `http://127.0.0.1:8000` directly. That works without CORS because the URL is in the extension's `host_permissions`. For aliases it calls the app on `localhost:3000` with the user's session cookie, and `require_session` accepts its `chrome-extension://` Origin on `GET`/`POST /api/aliases` only (`EXTENSION_SESSION_ROUTES`).
- **Treat scraped content as untrusted.** It can contain prompt injection aimed at the LLM. Validate LLM output against enums (e.g. `FIELD_TYPES`, tier names) and drop anything else.
- **Stubs.** Each stage function raises `NotImplementedError` until its owner builds it. `main.py` turns that into an error string, or HTTP 501 for routes without an errors list, so the app runs end to end from day one. Keep each stub's name and signature when you fill it in.
- **Reference data:** `from app.data import load_json`, then `load_json("brokers.json")`. Keys are snake_case; `tests/test_data.py` checks them.

## LLM: Gemini (`prompts.py`, `clients/gemini.py`)

- `gemini.ask_json(prompt, system=..., purpose=...)` calls `generateContent` with `responseMimeType: "application/json"` and low thinking. It returns `{}` on any failure (no key, HTTP error, bad JSON) and never raises on model output. 429 and 503 are retried twice (5 s, then 15 s).
- Every prompt asks for JSON in a fixed shape that is spelled out in the prompt.
- Parse defensively: invalid JSON gives `{}`, and a missing key means no or empty. Never crash on model output.
- Truncate page text (`prompts.MAX_PAGE_CHARS`, 12k chars) and batch long policies (`s4_policy.BATCH_CHARS`). Shorter inputs are faster and cheaper, and keep the model on task.
- `GEMINI_PARALLEL` calls run at once (default 4); lower it if the free tier rate-limits you. `GEMINI_MODEL` picks the model (default `gemini-3.6-flash`). Each call is an outbound request: it's in the log as service `gemini` with the prompt it carried, and on the public site it counts toward the paid work the daily search limits cap.
- Without `GEMINI_API_KEY`, `gemini.ready()` is false: Stage 1 refuses to search (no credits spent on pages it can't read), and other LLM steps fall back to their rules.
- Prompts should be conservative. A false "this broker has your SSN" is worse than missing a field.

## API routes (`main.py`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/status` | | key presence, Gemini set up (`ollama_running`, `ollama_model`: old names, Gemini values), Postgres up, `public` |
| POST | `/api/scan` | `{name, city, state, consent, refresh?}` | `{scan_id, exposures, errors, saved_at}` (Stages 1 and 2); saved to Postgres. A person scanned before gets their newest saved scan back (`saved_at` set, nothing searched) unless `refresh` is true. The scan runs as its own task: a dropped request (Vercel's 120-second limit, a closed tab) doesn't stop it, and asking again for the same person joins it |
| GET | `/api/scans/latest` | | the last saved scan ("load last scan" fallback) |
| GET | `/api/brokers` | | the broker list |
| GET | `/api/companies` | | account list for the picker: `data/companies.json` plus companies the user added |
| POST | `/api/companies` | `{name}` | add any company (`app/companies.py`): a website is used as typed; a name gets one Exa company search, else a labeled guess. Saved to `backend/local/companies.json` on a laptop, per account in Postgres on the public site |
| POST | `/api/accounts` | `{companies: [...]}` | `{breaches, policies, errors}` (Stages 3 and 4) |
| GET | `/api/leads` | | exposures with ranked `leads` (Stage 5) |
| POST | `/api/optout` | `{exposure_id}` or `{company}` | `Draft` (Stage 6) |
| POST | `/api/rescan` | | removal status per listing (Stage 6) |
| GET/POST | `/api/aliases` | `{company}` or `{site, label?}` | this account's aliases (plus the demo ones) with status and mock-inbox counts / new alias for a company or a website, a fresh address each time (Stage 7) |
| PATCH | `/api/aliases/{alias}` | `{status?, note?}` | disable or re-enable an alias, or change its note (404 if it isn't yours) |
| GET | `/api/aliases/{alias}/messages` | | that alias's mail from the mock inbox, newest first, each `expected` or not and `blocked` if it came after the alias was disabled |
| POST | `/api/aliases/{alias}/investigate` | | `AliasInvestigation`: rule facts, unexpected senders (named from `brokers.json`/`companies.json`), the Proven tier, and a Gemini category and explanation checked by `s7_aliases.clean_explanation`. No model call when nothing is unexpected |
| GET | `/api/inbox/check` | | `AliasHit[]` from the mock inbox (Stage 7) |
| GET/DELETE | `/api/outbound-log` | `?include_local=` | log entries / clear |
| POST | `/api/auth/signup`, `/login` | `{email, password}` | `User` `{email, id, role, created_at}` and a session cookie. The first account in the database is the admin. Login is throttled per email (429 after `auth.MAX_FAILURES` misses in `auth.FAILURE_WINDOW` s) |
| POST/GET | `/api/auth/logout`, `/me` | | end this session / the signed-in `User` (401 if none) |
| POST | `/api/auth/password` | `{current_password, new_password}` | change your password; your other sessions end, this one stays (400 wrong current password, 429 throttled) |
| POST | `/api/auth/reset` | `{email, code, new_password}` | spend a one-time code from an admin, set a new password and sign in (400 bad or expired code, 429 throttled). Open route |
| GET | `/api/admin/users` | | admins only (403 otherwise): every account |
| PATCH/DELETE | `/api/admin/users/{id}` | `{role}` | change a role / remove an account with its sessions, saved scans and footprint. 409 for the last admin or your own account |
| POST | `/api/admin/users/{id}/reset-code` | | `ResetCode` `{email, code, expires_at}`, shown once; replaces an earlier code and expires after `auth.RESET_MINUTES` |
| POST | `/api/site-policy` | `{origin, policy_urls, opt_out_url?, page_text?, deep?, refresh?, third_party_hosts?, asks_for?, insecure_fields?}` | `SitePolicyResponse`: what the site's privacy policy says it collects and shares, what the page does (trackers, form fields, people-search site, ads.txt), and the risks. Called by the browser extension (`extension/`). 400 for this computer or the local network, 403 for a web page's origin. Results stay in memory, never in Postgres |
| GET | `/api/monitor` | | threat monitor dashboard: summary, companies, emails, incidents, history, schedule, config |
| GET/POST | `/api/monitor/refresh` | `{company_id?, include_news?}` | refresh status / start a background check (202; 409 if one runs) |
| POST/DELETE | `/api/monitor/companies[/{id}]` | `{name}` | monitor a company (same lookup as `/api/companies`) / stop |
| POST/DELETE | `/api/monitor/emails[/{id}]` | `{address}` | add an address (sends a code if SMTP is set) / remove |
| POST | `/api/monitor/emails/{id}/code`, `/verify` | `{code}` | send a code / verify it |
| POST | `/api/monitor/incidents/{id}/actions/{action}` | `{done}` | mark a step done or not |
| POST | `/api/monitor/incidents/{id}/analyze` | | Gemini explanation, checked against the evidence |
| POST | `/api/monitor/seen`, `/schedule` | | mark alerts seen / save the local schedule |
| GET/POST | `/api/footprint` | `TrackedCompanyInput` | the signed-in account's tracked companies, each with its requests and their history / track a new one |
| PUT/DELETE | `/api/footprint/{company_id}` | `TrackedCompanyInput` | edit a company, including the privacy settings the user recorded / remove it with its requests |
| POST | `/api/footprint/{company_id}/requests` | `{kind, law}` | a new draft request from the local template in `app/footprint.py` |
| PATCH/DELETE | `/api/footprint/requests/{request_id}` | `{subject, body}` | edit the text (only until it's marked sent) / remove the request |
| POST | `/api/footprint/requests/{request_id}/updates` | `{status, happened_on?, note?}` | record a step; `footprint.NEXT` decides which statuses can follow |
| DELETE | `/api/footprint/requests/{request_id}/updates/last` | | undo the last recorded step (409 if there's none) |

**Sign-in gate.** `require_session` in `main.py` answers 401 for every `/api/*` route except `OPEN_ROUTES` (status, brokers, sign-up, login, logout, me, password reset) unless the request carries a valid session cookie, and 403 for any change whose `Origin` isn't this laptop. It sets `auth.current_user()`, which `db.py` uses to keep saved scans per account. New routes are gated automatically; tests get a signed-in client from `conftest.py`. Admin routes add `_admin`, which checks the account's role in Postgres. Session tokens and reset codes are stored only as SHA-256 (`auth.token_hash`); `db.py` hashes them, so callers pass the raw value. The one exception is `EXTENSION_ROUTES` (`/api/site-policy`): the browser extension has no session cookie and sends a `chrome-extension://` Origin, so the route skips the gate and refuses any web page's Origin itself.

Footprint routes (feature 3) need a session cookie (401 otherwise), only read or change the signed-in account's rows (404 for anyone else's), and never call `outbound.request`: drafts are local templates, and Dossier doesn't send requests or change company settings. "Response received" and "Completed" can only follow "Sent", the text locks once a request is marked sent, and step dates can't be in the future or before the last recorded step (409/422).

Reject `/api/scan` with HTTP 400 when `consent` is false. Routes that act on the current scan (`/api/optout`, `/api/rescan`) return 409 until a scan has run or been loaded. FastAPI doesn't serve the frontend: it's a separate Next.js app that proxies `/api/*` here.

## Database (`db.py`)

- Saved scans only: a `scans` table with the request (name, city, state) and the response as `jsonb`.
- Plain SQL through sync `psycopg`, called with `asyncio.to_thread`. (psycopg's async mode doesn't work with the default event loop on Windows.) No ORM and no migrations: edit the `create table if not exists` schema, and reset with `docker compose down -v` if you must.
- If Postgres is down, the app still runs. Scans just aren't saved, and the scan response says so.
- Saved scans have a `user_id`: each account only finds and loads its own. Scans saved before accounts existed have none and aren't shown to anyone signed in.
- Digital footprint (feature 3): `footprint_companies` (per `user_id`, privacy settings as `jsonb`), `footprint_requests` and `footprint_events` (the user's recorded steps, with the date they entered). Deleting a user or a company cascades to everything under it.
- `connect()` swaps a `localhost` host for `127.0.0.1`: docker-compose publishes Postgres on IPv4 only, and on Windows libpq's `::1` attempt cost the full 3-second connect timeout on every query.
- Use parameterized queries only (`%s` placeholders); never build SQL with f-strings. Scraped page text is stored only as far as a feature needs it.

## Testing

- Run `pytest` from `backend/`. The tests are offline: `tests/conftest.py` stubs out Postgres, and the API tests swap stages for fakes. Keep it that way.
- Stage 5 ranking and Stage 7 inbox matching are pure functions. Unit-test them with fixtures; they need no network access.
- Anything that touches Exa or Tavily costs credits. Test with small `max_results`, and use a consenting teammate's name, never a stranger's.
- Unit-test the guard in `outbound.py` too (formats like `617-555-0123`, `(617) 555 0123`, `a.b+c@x.co`).

## Threat monitor (`app/monitor/`)

Details and setup: `docs/THREAT_MONITOR.md`.

- **What leaves the laptop:** HIBP gets its whole breach list downloaded (nothing personal) or a 6-character SHA-1 prefix for a verified email. Tavily and Exa get company names, through Stage 3; Tavily Extract may get one public URL (an official breach notice) when explaining a breach HIBP doesn't describe. SMTP sends ownership codes. All of it goes through `outbound.py`.
- **Rules, not the LLM:** severity, confidence and involvement are set by rules in `severity.py`, and steps by `checklist.py` from `data/breach_data_classes.json`. They're derived when an incident is shown, never stored. The LLM only explains them, and `analysis.py` drops unsupported numbers, unconfirmed "you were affected" claims and banned wording.
- **Involvement:** only a verified email's hashed HIBP match confirms it. Never word a company breach as if it confirmed the user was in it.
- **State:** `backend/local/monitor.json` (`store.py`). Tests point it at a temp dir in `tests/conftest.py`.
