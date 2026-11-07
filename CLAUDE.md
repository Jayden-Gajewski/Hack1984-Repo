# Hack1984: personal data exposure finder

**Pitch:** Find out where your personal data is exposed, which company most likely leaked it, and get it taken down, without handing your data to yet another company.

**Tracks:** Surge (Exa and Tavily run the core), Most Startup-able (people already pay for data removal), Privacy-First (analysis runs locally; every outbound request is logged).

## Privacy rules (non-negotiable)

These rules are the product. Do not break them, even temporarily, even to debug.

1. **Analysis runs locally.** Page text, policy text and all LLM analysis go only to Ollama on localhost. Never send page content to Exa, Tavily or a hosted LLM. Never add a hosted LLM API.
2. **One door out.** Every request to an outside service goes through `backend/app/outbound.py`. No direct `httpx`/`requests` calls or vendor SDKs anywhere else. That module feeds the outbound log panel. The Next.js app talks only to the FastAPI backend on localhost. Its server code (route handlers, server components) never calls Exa, Tavily or any other external service.
3. **Minimal queries.** Search with name + city/state only, or a company name. Never send phone numbers, emails, SSNs or birthdates. `outbound.py` rejects queries that contain them. Don't weaken that check.
4. **Self-scan only.** A scan requires a `consent: true` flag. Demos use a consenting teammate.
5. **User data stays on this laptop and out of git.** User data lives in memory, in `backend/local/` (gitignored), or in the local Postgres container (never a hosted database). Never commit real scan results, names or page text. Fixtures use fictional people and `.example` domains.
6. **Wording.** Say "likely source", never "who leaked it" or "leaked by". Every date shows its source. A missing date is "unknown", never a guess.

## Stack

- **Backend:** Python 3.13, FastAPI, async `httpx`, pydantic v2. Call the Exa and Tavily REST APIs directly (not their SDKs), so the log captures exactly what was sent.
- **Database:** PostgreSQL 16 in Docker (`docker-compose.yml`), plain SQL through `psycopg` in `backend/app/db.py`. It holds saved scans for the "load last scan" fallback, and it runs on this laptop only.
- **Local LLM:** Ollama in JSON mode. The model is set by `OLLAMA_MODEL` (default `llama3.1:8b`).
- **Frontend:** Next.js (App Router, React, TypeScript) in `frontend/`, on port 3000. It proxies `/api/*` to FastAPI on port 8000, so the browser only ever talks to localhost.
- **Config:** `.env` at the repo root (`EXA_API_KEY`, `TAVILY_API_KEY`, `OLLAMA_URL`, `OLLAMA_MODEL`, `ALIAS_DOMAIN`, `DATABASE_URL`). `config.py` refuses an `OLLAMA_URL` or `DATABASE_URL` that isn't localhost. Commit `.env.example`, never `.env`.
- **State:** the current scan in memory, saved scans in Postgres, and aliases and reports as JSON in `backend/local/`. Single user, runs on one laptop.

## Don't build

Hosted accounts or third-party auth (the local accounts in `auth.py`, stored in the local Postgres, are the only kind), real Gmail/IMAP integration, vector databases, agent frameworks (LangChain, CrewAI, etc.), multiple agents, an ORM or a second database, hosted or cloud databases, analytics or telemetry of any kind, extra frontend frameworks or UI component libraries on top of Next.js. If a task seems to need one of these, stop and ask.

## Layout (target; create files here as you build)

```
backend/
  app/
    main.py          FastAPI routes (JSON API only; Next.js serves the frontend)
    config.py        loads .env; refuses a non-localhost OLLAMA_URL or DATABASE_URL
    outbound.py      logged HTTP client + minimal-query check
    models.py        pydantic models = the API contract with the frontend
    prompts.py       local LLM prompts
    db.py            PostgreSQL: saved scans, local users and sessions
    auth.py          local accounts: scrypt password hashes, session tokens
    clients/         exa.py, tavily.py, wayback.py, ollama.py
    stages/          s1_exposures.py ... s7_aliases.py
    data/            checked-in reference data: brokers.json, companies.json,
                     breach_sources.json, mock_inbox.json, mock_aliases.json
  local/             gitignored: aliases, reports
  scripts/           one-off tests, e.g. test_extract.py
  tests/             pytest, offline
  requirements.txt
frontend/
  app/               Next.js pages and components
  lib/api.ts         typed API client; mirrors models.py
  lib/display.ts     wording rules (tier labels, date sources) and safe links
  next.config.ts     /api proxy to the backend
  proxy.ts           sends /app to /login when there's no session cookie
docker-compose.yml   local Postgres
```

## Pipeline and owners

| Stage | Module | Owner |
|---|---|---|
| 1. Find exposures | `stages/s1_exposures.py` | Search & extract |
| 2. Date them (Wayback) | `stages/s2_dating.py` | Evidence |
| 3. Breach timelines | `stages/s3_breaches.py` | Evidence |
| 4. Policy check | `stages/s4_policy.py` | Evidence |
| 5. Rank likely sources | `stages/s5_ranking.py` | Local LLM & ranking |
| 6. Resolve (opt-outs, re-scan) | `stages/s6_resolve.py` | Search & extract |
| 7. Aliases + inbox check | `stages/s7_aliases.py` | Local LLM & ranking |
| Prompts | `prompts.py` | Local LLM & ranking |
| Cards, outbound log, pitch | `frontend/` | UI & demo |

Details for each stage are in `backend/app/stages/CLAUDE.md`.

**Shared files:** `models.py`, `db.py`, `outbound.py`, the API routes in `main.py`, and `frontend/lib/api.ts` (which mirrors `models.py`) affect everyone. Keep changes to them additive, and call them out in the commit message. Every stage starts as a stub that raises `NotImplementedError`, and its route already exists, so you can usually fill in your stage without touching the shared files.

## Build order

1. **First hour:** `backend/scripts/test_extract.py` runs Tavily Extract on Spokeo, Whitepages and similar sites with a teammate's name. The result decides whether Stage 1 relies on extracted text or on search snippets.
2. **MVP:** Stages 1, 4 and 6 plus the outbound log. That is a complete demo on its own.
3. **Then:** Wayback dates (2), breach timelines (3), evidence-tier ranking (5).
4. **Last:** a mocked inbox showing one alias match (7).

Finish the current tier before starting the next.

## Commands

```bash
docker compose up -d              # local Postgres (from the repo root)
ollama pull llama3.1:8b

# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload     # API on http://localhost:8000
pytest                            # offline tests
python -m scripts.test_extract --name "Jane Doe" --city "Boston" --state "MA"

# Frontend (second terminal)
cd frontend
npm install
npx next telemetry disable        # once per laptop: Next.js telemetry isn't in our outbound log
npm run dev                       # UI on http://localhost:3000
npm run demo                      # production build for the demo (no dev-only network calls)
```

## Demo script (about 3 minutes)

1. Scan a consenting teammate live and show the exposure cards with sources.
2. Open one card: its fields, the Wayback date, and the likely source with its evidence tier.
3. Show a policy flag: "this wasn't a hack, they sold it."
4. Click to draft an opt-out request.
5. Show the mocked alias match as Proven.
6. End on the outbound log: "Here's everything that left this laptop."

When choosing what to build next, favor whatever makes this script work end to end.

## Git

Commit to short-lived branches and merge to `main` often. Four people share this repo for one weekend, so keep commits small and don't reformat files you don't own.
