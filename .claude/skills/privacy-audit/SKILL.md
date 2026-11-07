---
name: privacy-audit
description: Audit the codebase for privacy-track violations. Checks that every external HTTP call goes through outbound.request in backend/app/outbound.py, that search queries never contain an email, phone number, SSN or birthdate, and that extracted page text and personal data are only ever sent to the local Ollama, never to Exa, Tavily or any other cloud API. Use before merging, before the demo, after adding a client or stage, or when someone asks "are we still privacy-safe?"
---

# privacy-audit

These are the Privacy-First track's claims, so each one has to be true in the code:
1. Every outbound request is logged (it goes through `outbound.request(...)` in `backend/app/outbound.py`).
2. Queries use name + city only, never an email, phone number, SSN or birthdate (`guard=[query]` runs `assert_minimal_query`).
3. Page text and analysis never leave the machine (only Ollama sees them).

Report each finding as `file:line`, the rule it breaks, and a one-line fix. Don't auto-fix unless asked.

## Check 1: no bypassing outbound.request

Search `backend/app/` and `backend/scripts/` for raw network calls:
- `import httpx`, `import requests`, `urllib.request`, `aiohttp`, `http.client`, `socket`, vendor SDKs (`exa_py`, `tavily`)
- Hardcoded hosts: `api.exa.ai`, `api.tavily.com`, `archive.org`

Allowed:
- `httpx` inside `backend/app/outbound.py` itself, and `fastapi.testclient` in `backend/tests/`.
- The base URL constants in `backend/app/clients/*.py`, as long as the calls go through `outbound.request`.
- `backend/app/clients/ollama.py` calling `OLLAMA_URL` with `local=True`. `outbound.request` refuses `local=True` for a non-localhost host; flag it if that check was removed.
- `psycopg` in `backend/app/db.py` talking to the local Postgres container. `config.py` refuses a non-localhost `OLLAMA_URL` or `DATABASE_URL`, and `docker-compose.yml` binds Postgres to `127.0.0.1`; flag it if any of these was removed.

Also check `frontend/`: the browser should only call relative `/api/...` URLs (proxied by `next.config.ts` to localhost; it throws if `BACKEND_URL` isn't localhost). Any absolute `https://` fetch, third-party `<script>`, analytics, or `next/font/google` is a violation. On demo laptops, Next.js telemetry should be off (`cd frontend && npx next telemetry status`).

## Check 2: minimal queries

- Every Exa/Tavily **search query** string must be passed as `guard=[query]` to `outbound.request`. Trace each call in `backend/app/clients/exa.py` and `tavily.py` and check that the guard is on the path.
- Look for queries built from anything other than name, city, state, broker or company names: grep for `email`, `phone`, `tel`, `dob`, `birth` and `ssn` near query construction in `backend/app/stages/`.
- `ScanRequest` in `backend/app/models.py` also runs `assert_minimal_query` on the form fields. Check that it still does.
- Quick runtime test: `cd backend && pytest tests/test_outbound.py`. Every "blocked" case must raise.

## Check 3: personal data only goes to Ollama

- Find every place extracted text (Tavily Extract `raw_content`, Exa `text`, privacy policy text, mock inbox messages) flows.
  It may go to: `ask_json` in `backend/app/clients/ollama.py`, the UI via our own API, local memory, `backend/local/`, or the local Postgres.
  It must NOT go into: the body or query of any Exa/Tavily/Wayback request (including `find_similar`), logs shipped elsewhere, or any cloud SDK.
- Grep for cloud LLM SDKs or keys that shouldn't exist: `openai`, `anthropic`, `google.generativeai`, `OPENAI_API_KEY`, `cohere`, `groq`. Any hit is a violation.
- Check `backend/requirements.txt` and `frontend/package.json` for the same.
- Stage 7 (aliases) must check the mock inbox locally. No search call there.

## Check 4: the outbound log is honest

- `GET /api/outbound-log` returns entries with service, purpose, URL, the headers httpx actually sent, body, status and time.
- It must still show what query was sent (that's the point), but API keys (`x-api-key`, `Authorization`, any `key` or `token` URL param) must read `REDACTED`. `backend/tests/test_outbound.py` covers this; check it still passes.
- `.env` is gitignored, and no key literals appear in tracked files (grep the `git ls-files` list for `tvly-` and long hex strings).

## Output

```
PRIVACY AUDIT: PASS | FAIL
Violations: <n>   Warnings: <n>
- [FAIL] backend/app/stages/s3_breaches.py:42  httpx call to api.tavily.com bypasses outbound.request -> use clients/tavily.py
- [WARN] docker-compose.yml:10  Postgres published on all interfaces -> bind to 127.0.0.1
```
End with the pitch line you can now honestly say, or the one you can't yet.
