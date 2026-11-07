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
| GET | `/api/companies` | | account list for the picker |
| POST | `/api/accounts` | `{companies: [...]}` | `{breaches, policies, errors}` (Stages 3 and 4) |
| GET | `/api/leads` | | exposures with ranked `leads` (Stage 5) |
| POST | `/api/optout` | `{exposure_id}` or `{company}` | `Draft` (Stage 6) |
| POST | `/api/rescan` | | removal status per listing (Stage 6) |
| GET/POST | `/api/aliases` | `{company}` | aliases / new alias (Stage 7) |
| GET | `/api/inbox/check` | | `AliasHit[]` from the mock inbox (Stage 7) |
| GET/DELETE | `/api/outbound-log` | `?include_local=` | log entries / clear |

Reject `/api/scan` with HTTP 400 when `consent` is false. Routes that act on the current scan (`/api/optout`, `/api/rescan`) return 409 until a scan has run or been loaded. FastAPI doesn't serve the frontend: it's a separate Next.js app that proxies `/api/*` here.

## Database (`db.py`)

- Saved scans only: a `scans` table with the request (name, city, state) and the response as `jsonb`.
- Plain SQL through sync `psycopg`, called with `asyncio.to_thread`. (psycopg's async mode doesn't work with the default event loop on Windows.) No ORM and no migrations: edit the `create table if not exists` schema, and reset with `docker compose down -v` if you must.
- If Postgres is down, the app still runs. Scans just aren't saved, and the scan response says so.
- Use parameterized queries only (`%s` placeholders); never build SQL with f-strings. Scraped page text is stored only as far as a feature needs it.

## Testing

- Run `pytest` from `backend/`. The tests are offline: `tests/conftest.py` stubs out Postgres, and the API tests swap stages for fakes. Keep it that way.
- Stage 5 ranking and Stage 7 inbox matching are pure functions. Unit-test them with fixtures; they need no network access.
- Anything that touches Exa or Tavily costs credits. Test with small `max_results`, and use a consenting teammate's name, never a stranger's.
- Unit-test the guard in `outbound.py` too (formats like `617-555-0123`, `(617) 555 0123`, `a.b+c@x.co`).
