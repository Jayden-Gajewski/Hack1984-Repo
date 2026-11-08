# Hack1984: personal data exposure finder

**Pitch:** Find out where your personal data is exposed, which company is the likely source, and get it taken down, with every request Dossier makes on your behalf shown in full.

**Tracks:** Surge (Exa and Tavily run the core), Most Startup-able (people already pay for data removal), Privacy-First (minimal queries, and every outbound request is logged with its exact contents, including what Gemini reads).

## Privacy rules (non-negotiable)

These rules are the product. Do not break them, even temporarily, even to debug.

1. **Only Gemini reads page text.** Page text, policy text and breach evidence go to Google's Gemini API (`clients/gemini.py`) and nowhere else. Never send page content to Exa, Tavily or any other service, and don't add a second LLM provider or an LLM SDK. Gemini calls go through `outbound.py` like every other request, so the log shows exactly what Google was sent. Site copy says "the AI", or "Google's AI" where it says who receives the data. It never names Gemini (the outbound log's raw request URLs still show the real endpoint) and never claims the AI runs on this laptop. On Gemini's free tier Google may use what it's sent, so the public site needs a paid key.
2. **One door out.** Every request to an outside service goes through `backend/app/outbound.py`. No direct `httpx`/`requests` calls or vendor SDKs anywhere else. That module feeds the outbound log panel. The Next.js app talks only to the FastAPI backend, through its `/api` rewrite (localhost on a laptop, `BACKEND_URL` on the public site). Its server code (route handlers, server components) never calls Exa, Tavily, Gemini or any other external service.
3. **Minimal queries.** Search with name + city/state only, or a company name. Never send phone numbers, emails, SSNs or birthdates. `outbound.py` rejects queries that contain them. Don't weaken that check. The threat monitor's email check is the one place an email is involved: HIBP gets only the first 6 characters of a verified address's SHA-1 hash (`clients/hibp.py` refuses anything else), and the ownership code goes to the user's own address through their SMTP server via `outbound.send_mail`. Never add HIBP's full-address lookup.
4. **Self-scan only.** A scan requires a `consent: true` flag. Demos use a consenting teammate.
5. **User data stays in Dossier's own storage and out of git.** User data lives in memory, in `backend/local/` (gitignored), or in Dossier's Postgres: the local Docker container on a laptop, or the public site's one hosted Postgres, reached only over TLS (`config.py` enforces both). No other database, cache or store. On the public site each account sees only its own data. Never commit real scan results, names or page text. Fixtures use fictional people and `.example` domains.
6. **Wording.** Say "likely source", never "who leaked it" or "leaked by". Every date shows its source. A missing date is "unknown", never a guess.

## Stack

- **Backend:** Python 3.13, FastAPI, async `httpx`, pydantic v2. Call the Exa, Tavily and Gemini REST APIs directly (not their SDKs), so the log captures exactly what was sent.
- **Database:** PostgreSQL 16, plain SQL through `psycopg` in `backend/app/db.py`: accounts and sessions, saved scans, aliases, the footprint, and on the public site added companies and daily search counts. On a laptop it's the Docker container (`docker-compose.yml`); on the public site a hosted Postgres (Neon) with `sslmode=require`.
- **LLM:** Google's Gemini API (`generateContent` with JSON output) in `clients/gemini.py`. `GEMINI_MODEL` picks the model (default `gemini-3.6-flash`, stable; `gemini-3.8-flash` is newer) and `GEMINI_PARALLEL` how many calls run at once (default 4). Without `GEMINI_API_KEY` the LLM steps are skipped and say so. The status API's `ollama_running` and `ollama_model` fields describe Gemini now; they keep their old names for the API contract.
- **Frontend:** Next.js (App Router, React, TypeScript) in `frontend/`: port 3000 on a laptop, Vercel on the public site. It proxies `/api/*` to the backend (`BACKEND_URL`, default `http://localhost:8000`), so the browser only ever talks to the site it opened.
- **Public site:** Vercel (frontend), Render (backend, `render.yaml`, one instance) and Neon (Postgres). Setting `SITE_URL` on the backend turns on public mode: each account's own scan and log, changes accepted only from `SITE_URL`'s origin, an https-only session cookie, daily search limits, and the Threat Monitor and extension route switched off. Vercel waits at most 120 seconds for any request; a scan keeps running past that and is saved. Steps: `docs/DEPLOY.md`.
- **Config:** `.env` at the repo root: `EXA_API_KEY`, `TAVILY_API_KEY`, `GEMINI_API_KEY` (plus optional `GEMINI_MODEL`, `GEMINI_PARALLEL`, `SCAN_MAX_PAGES`), `ALIAS_DOMAIN`, `DATABASE_URL`; for the public site `SITE_URL`, `SEARCHES_PER_DAY`, `SEARCHES_PER_DAY_TOTAL`; for the threat monitor the optional `HIBP_API_KEY` and `SMTP_*`. Vercel needs `BACKEND_URL`, `SITE_URL` and `NEXT_TELEMETRY_DISABLED=1`. Without `SITE_URL`, `config.py` refuses a `DATABASE_URL` that isn't localhost; with it, a hosted one must use TLS. Commit `.env.example`, never `.env`.
- **State:** each account's current scan in memory; accounts, saved scans, aliases and the footprint in Postgres; companies added to the picker in `backend/local/companies.json` on a laptop (Postgres on the public site); the threat monitor in `backend/local/monitor.json` (laptop only).

## Don't build

Third-party auth or sign-in providers (Dossier's own accounts in `auth.py`, stored in its Postgres, are the only kind), real Gmail/IMAP integration, vector databases, agent frameworks (LangChain, CrewAI, etc.), multiple agents, an ORM or a second database, any hosted database or store besides the public site's one Postgres, a second LLM provider, analytics or telemetry of any kind (Vercel Web Analytics and Speed Insights included), extra frontend frameworks or UI component libraries on top of Next.js. If a task seems to need one of these, stop and ask.

## Layout (target; create files here as you build)

```
backend/
  app/
    main.py          FastAPI routes (JSON API only; Next.js serves the frontend)
    config.py        loads .env; SITE_URL = public mode; DATABASE_URL local, or TLS when public
    outbound.py      logged HTTP client + minimal-query check
    models.py        pydantic models = the API contract with the frontend
    prompts.py       Gemini prompts (strict JSON)
    db.py            PostgreSQL: accounts and sessions, saved scans, aliases, footprint, usage
    auth.py          local accounts: scrypt password hashes, hashed session tokens, roles,
                     login throttling, admin-issued password reset codes
    site_policy.py   browser extension: privacy check for the site you're visiting
    clients/         exa.py, tavily.py, wayback.py, gemini.py, hibp.py,
                     website.py (reads a policy straight from a site)
    stages/          s1_exposures.py ... s7_aliases.py
    monitor/         threat monitor (/api/monitor/*): HIBP matching, severity rules,
                     checklists, Gemini explanations, scheduler; docs/THREAT_MONITOR.md
    data/            checked-in reference data: brokers.json, companies.json,
                     breach_sources.json, mock_inbox.json, mock_aliases.json,
                     breach_data_classes.json (threat monitor)
  local/             gitignored: aliases, reports, monitor.json
  scripts/           one-off tests, e.g. test_extract.py
  tests/             pytest, offline
  requirements.txt
frontend/
  app/               Next.js pages and components (/app scanner, /app/monitor threat monitor)
  lib/api.ts         typed API client; mirrors models.py
  lib/display.ts     wording rules (tier labels, date sources) and safe links
  next.config.ts     /api proxy to the backend (BACKEND_URL); a Vercel build without it stops
  proxy.ts           sends /app to /login without a session cookie, and /login and /signup to /app with one
extension/           Chrome/Edge extension (Manifest V3, plain JS, no build step)
docker-compose.yml   local Postgres
render.yaml          the backend on Render (public site)
docs/DEPLOY.md       deploying the public site: Vercel + Render + Neon
```

## Pipeline and owners

| Stage | Module | Owner |
|---|---|---|
| 1. Find exposures | `stages/s1_exposures.py` | Search & extract |
| 2. Date them (Wayback) | `stages/s2_dating.py` | Evidence |
| 3. Breach timelines | `stages/s3_breaches.py` | Evidence |
| 4. Policy check | `stages/s4_policy.py` | Evidence |
| 5. Rank likely sources | `stages/s5_ranking.py` | LLM & ranking |
| 6. Resolve (opt-outs, re-scan) | `stages/s6_resolve.py` | Search & extract |
| 7. Aliases + inbox check | `stages/s7_aliases.py` | LLM & ranking |
| Prompts | `prompts.py` | LLM & ranking |
| Cards, outbound log, pitch | `frontend/` | UI & demo |

Details for each stage are in `backend/app/stages/CLAUDE.md`.

**Shared files:** `models.py`, `db.py`, `outbound.py`, the API routes in `main.py`, and `frontend/lib/api.ts` (which mirrors `models.py`) affect everyone. Keep changes to them additive, and call them out in the commit message. Every stage starts as a stub that raises `NotImplementedError`, and its route already exists, so you can usually fill in your stage without touching the shared files.

## Browser extension

`extension/` checks every site you visit (`POST /api/site-policy`, `app/site_policy.py`). It shows what the privacy policy says the company collects and sells or shares, and what the page itself does: known trackers (`data/trackers.json`), the kinds of personal data its forms ask for, whether it's a people-search site, and its `ads.txt` ad sellers. It keeps the same rules:
- The extension talks only to the backend on localhost (and to the app on localhost:3000 for the "private email for this site" alias, with the user's own session). From the page it sends only hostnames and fixed field-kind words, never what's typed or a full tracker URL.
- The automatic check on each visit contacts no site. When the popup opens, only the visited site is contacted, for its policy and its `ads.txt`. The backend fetches both straight from the site through `outbound.py`, and doesn't follow links or redirects to other sites. No search API is used.
- Policies are checked by fixed rules in the backend. When the popup opens, the policy's selling and sharing sentences and the site's name also go to Gemini (logged as service `gemini`).
- Results stay in memory, because the sites you visit are browsing history.
- It works with the Dossier app running on the user's own computer. The public site switches its route off.

Details and install steps are in `extension/README.md`.

## Build order

1. **First hour:** `backend/scripts/test_extract.py` runs Tavily Extract on Spokeo, Whitepages and similar sites with a teammate's name. The result decides whether Stage 1 relies on extracted text or on search snippets.
2. **MVP:** Stages 1, 4 and 6 plus the outbound log. That is a complete demo on its own.
3. **Then:** Wayback dates (2), breach timelines (3), evidence-tier ranking (5).
4. **Last:** a mocked inbox showing one alias match (7).

Finish the current tier before starting the next.

## Commands

```bash
docker compose up -d              # local Postgres (from the repo root)
# .env: add GEMINI_API_KEY (https://aistudio.google.com/apikey) next to the Exa and Tavily keys

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

The public site (Vercel + Render + Neon) is deployed from `main`: follow `docs/DEPLOY.md`.

## Demo script (about 3 minutes)

1. Scan a consenting teammate live and show the exposure cards with sources.
2. Open one card: its fields, the Wayback date, and the likely source with its evidence tier.
3. Show a policy flag: "this wasn't a hack, they sold it."
4. Click to draft an opt-out request.
5. Show the mocked alias match as Proven.
6. End on the outbound log: "Here's every request Dossier sent, including exactly what Gemini read."

When choosing what to build next, favor whatever makes this script work end to end.

## Git

Commit to short-lived branches and merge to `main` often. Four people share this repo for one weekend, so keep commits small and don't reformat files you don't own.
