# Backend

FastAPI app in `app/`. Read the privacy rules in the root `CLAUDE.md` first.

## Conventions

- **Async everywhere.** Run independent calls together with `asyncio.gather(..., return_exceptions=True)`.
- **Network calls go through `outbound.request(...)` only.** It takes:
  - `service`: `"exa"`, `"tavily"`, `"wayback"` or `"ollama"`.
  - `purpose`: a plain-English reason shown in the log panel, e.g. `"Find listings on known people-search sites"`. Write it for a non-technical judge.
  - `guard=[query]`: every search query string. The guard rejects emails, phone numbers, SSNs and birthdates.
  - `local=True`: for Ollama calls. They're logged, with long text truncated, and marked as never leaving the machine.
- **Log what was actually sent.** Each entry records the final URL, the headers that were sent (API keys redacted), the body, the status and the duration. Never log API keys.
- **Partial failure is normal.** A broker blocks extraction, archive.org times out, a key is missing. Stages collect error strings and return them next to their results. One failed source must not fail the whole scan.
- **`models.py` is the contract with the frontend.** Add fields; don't rename or remove them without telling the UI owner, who keeps the types in `frontend/lib/api.ts` in sync.
- **Reference data goes in `app/data/*.json`, and user data in Postgres.** Don't hard-code broker lists or company domains in Python, and don't load reference data into the database.
- **No CORS.** The browser reaches FastAPI only through the Next.js `/api` rewrite, so don't add `CORSMiddleware` or `allow_origins=["*"]`.
- **Treat scraped content as untrusted.** It can contain prompt injection aimed at the local LLM. Validate LLM output against enums (e.g. `FIELD_TYPES`, tier names) and drop anything else.
- **Stubs.** Each stage function raises `NotImplementedError` until its owner builds it. `main.py` turns that into an error string, or HTTP 501 for routes without an errors list, so the app runs end to end from day one. Keep each stub's name and signature when you fill it in.
- **Reference data:** `from app.data import load_json`, then `load_json("brokers.json")`. Keys are snake_case; `tests/test_data.py` checks them.

## Local LLM (`prompts.py`, `clients/ollama.py`)

- Every prompt asks for JSON in a fixed shape that is spelled out in the prompt. Call Ollama with `format: "json"` and `temperature: 0`.
- Parse defensively: invalid JSON gives `{}`, and a missing key means no or empty. Never crash on model output.
- Truncate page text (about 12k chars) and chunk long policies. Small local models lose the thread on long inputs.
- Ollama calls run `OLLAMA_PARALLEL` at a time (default 1). On an 8 GB laptop a second concurrent call pushes the machine into swap.
- Prompts should be conservative. A false "this broker has your SSN" is worse than missing a field.

## API routes (`main.py`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/status` | | key presence, Ollama up, model pulled, Postgres up |
| POST | `/api/scan` | `{name, city, state, consent, refresh?}` | `{scan_id, exposures, errors, saved_at}` (Stages 1 and 2); saved to Postgres. A person scanned before gets their newest saved scan back (`saved_at` set, nothing searched) unless `refresh` is true |
| GET | `/api/scans/latest` | | the last saved scan ("load last scan" fallback) |
| GET | `/api/brokers` | | the broker list |
| GET | `/api/companies` | | account list for the picker: `data/companies.json` plus companies the user added |
| POST | `/api/companies` | `{name}` | add any company (`app/companies.py`): a website is used as typed; a name gets one Exa company search, else a labeled guess. Saved to `backend/local/` |
| POST | `/api/accounts` | `{companies: [...]}` | `{breaches, policies, errors}` (Stages 3 and 4) |
| GET | `/api/leads` | | exposures with ranked `leads` (Stage 5) |
| POST | `/api/optout` | `{exposure_id}` or `{company}` | `Draft` (Stage 6) |
| POST | `/api/rescan` | | removal status per listing (Stage 6) |
| GET/POST | `/api/aliases` | `{company}` | aliases / new alias (Stage 7) |
| GET | `/api/inbox/check` | | `AliasHit[]` from the mock inbox (Stage 7) |
| GET/DELETE | `/api/outbound-log` | `?include_local=` | log entries / clear |
| GET | `/api/monitor` | | threat monitor dashboard: summary, companies, emails, incidents, history, schedule, config |
| GET/POST | `/api/monitor/refresh` | `{company_id?, include_news?}` | refresh status / start a background check (202; 409 if one runs) |
| POST/DELETE | `/api/monitor/companies[/{id}]` | `{name}` | monitor a company (same lookup as `/api/companies`) / stop |
| POST/DELETE | `/api/monitor/emails[/{id}]` | `{address}` | add an address (sends a code if SMTP is set) / remove |
| POST | `/api/monitor/emails/{id}/code`, `/verify` | `{code}` | send a code / verify it |
| POST | `/api/monitor/incidents/{id}/actions/{action}` | `{done}` | mark a step done or not |
| POST | `/api/monitor/incidents/{id}/analyze` | | local-LLM explanation, checked against the evidence |
| POST | `/api/monitor/seen`, `/schedule` | | mark alerts seen / save the local schedule |
| GET/POST | `/api/footprint` | `TrackedCompanyInput` | the signed-in account's tracked companies, each with its requests and their history / track a new one |
| PUT/DELETE | `/api/footprint/{company_id}` | `TrackedCompanyInput` | edit a company, including the privacy settings the user recorded / remove it with its requests |
| POST | `/api/footprint/{company_id}/requests` | `{kind, law}` | a new draft request from the local template in `app/footprint.py` |
| PATCH/DELETE | `/api/footprint/requests/{request_id}` | `{subject, body}` | edit the text (only until it's marked sent) / remove the request |
| POST | `/api/footprint/requests/{request_id}/updates` | `{status, happened_on?, note?}` | record a step; `footprint.NEXT` decides which statuses can follow |
| DELETE | `/api/footprint/requests/{request_id}/updates/last` | | undo the last recorded step (409 if there's none) |

**Sign-in gate.** `require_session` in `main.py` answers 401 for every `/api/*` route except `OPEN_ROUTES` (status, brokers, auth) unless the request carries a valid session cookie, and 403 for any change whose `Origin` isn't this laptop. It sets `auth.current_user()`, which `db.py` uses to keep saved scans per account. New routes are gated automatically; tests get a signed-in client from `conftest.py`.

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
