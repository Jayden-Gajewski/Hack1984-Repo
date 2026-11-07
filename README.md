# Hack1984

Find out where your personal data is exposed, which company most likely leaked it, and get it taken down, without handing your data to yet another company.

The pitch, build order and demo script are in [docs/PITCH.md](docs/PITCH.md). The rules everyone (and Claude Code) follows are in [CLAUDE.md](CLAUDE.md).

## Stack

- **Frontend:** Next.js (React, TypeScript) in `frontend/`, on http://localhost:3000. It proxies `/api/*` to the backend.
- **Backend:** Python 3.13, FastAPI, async httpx and pydantic v2 in `backend/`, on http://localhost:8000.
- **Database:** PostgreSQL 16 in Docker, for saved scans.
- **Local LLM:** Ollama on localhost only. Page text never leaves the machine.

## Setup

You need Docker, Python 3.13, Node 20.9 or later, and [Ollama](https://ollama.com).

1. From the repo root:
   ```
   cp .env.example .env          # then paste in EXA_API_KEY and TAVILY_API_KEY
   docker compose up -d          # starts Postgres
   ollama pull llama3.1:8b
   ```
2. Backend, from `backend/`:
   ```
   python3.13 -m venv .venv      # Windows: py -3.13 -m venv .venv
   source .venv/bin/activate     # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
3. Frontend, from `frontend/`, in a second terminal:
   ```
   npm install
   npx next telemetry disable    # once per laptop (see the privacy rules below)
   npm run dev
   ```
4. Open http://localhost:3000. The line under the title shows what's still missing (Ollama, Postgres, API keys).

Stage 1 (find exposures) works. A scan needs at least one search key and Ollama running with the model pulled; if either is missing, it stops before searching and says what to fix. Stage 2 (Wayback dates) works too, so each card shows when the listing was first archived, linked to the snapshot. Stages 3–7 are still stubs, so there are no likely sources yet.

## Tests

```
cd backend && pytest                               # offline, uses no API credits
cd frontend && npm run typecheck && npm run build
```

## First hour: extraction test

Use a teammate's name, and only with their permission. From `backend/`:

```
python -m scripts.test_extract --name "First Last" --city "Boston" --state "MA"
```

It shows which brokers Tavily Extract can read and which need the search-snippet fallback. The full report goes to `backend/local/`, which is gitignored.

## Layout

```
backend/
  app/
    main.py          FastAPI routes, one or two stages each
    config.py        loads .env; refuses a non-localhost OLLAMA_URL or DATABASE_URL
    outbound.py      the one logged HTTP client + minimal-query guard
    models.py        pydantic models = the API contract
    prompts.py       local LLM prompts
    db.py            PostgreSQL: saved scans
    clients/         exa.py, tavily.py, wayback.py, ollama.py
    stages/          s1_exposures.py ... s7_aliases.py (stubs to fill in)
    data/            brokers, companies, AG breach sources, mock inbox and aliases
  scripts/           test_extract.py
  tests/             pytest (offline)
  local/             gitignored: aliases, reports
frontend/
  app/               page.tsx and components/
  lib/api.ts         typed API client (mirrors models.py)
  lib/display.ts     wording rules and safe links
  next.config.ts     /api proxy to the backend
docker-compose.yml   local Postgres
docs/PITCH.md        pitch and demo script
```

## Team split

| Role | Files |
|---|---|
| Search & extract (Stages 1, 6) | `clients/exa.py`, `clients/tavily.py`, `stages/s1_exposures.py`, `stages/s6_resolve.py`, `data/brokers.json` |
| Evidence (Stages 2–4) | `clients/wayback.py`, `stages/s2_dating.py`, `s3_breaches.py`, `s4_policy.py`, `data/breach_sources.json` |
| Local LLM & ranking (Stages 5, 7) | `clients/ollama.py`, `prompts.py`, `stages/s5_ranking.py`, `s7_aliases.py` |
| UI & demo | `frontend/`, the outbound log panel, the pitch |

Each stage file says what to build and points to the earlier JS version in git (for example `git show 2f13f74:server/stages/1-exposures.js`), which has logic worth porting.

## Privacy rules (don't break these)

- Every external request goes through `backend/app/outbound.py`. Don't import httpx or requests anywhere else in `backend/`.
- Search queries use name and city only. `assert_minimal_query` blocks emails, phone numbers, SSNs and birthdates.
- Page text and analysis go only to local Ollama, never to a cloud LLM.
- The browser only calls `/api/...` on localhost. No third-party scripts, fonts or analytics.
- Next.js sends its own telemetry, which our outbound log can't see. Turn it off on every laptop (`npx next telemetry disable`), and demo with `npm run demo` (a production build skips the dev server's version check).
- Say "likely source", never "who leaked it". Label every date with its source.

## Git workflow

```
git checkout main && git pull
git checkout -b your-feature
# ...work...
git push -u origin your-feature   # then open a PR into main
```

`models.py`, `outbound.py`, `main.py` and `frontend/lib/api.ts` are shared, so keep changes there additive and mention them in the commit message.

## Claude Code helpers

The skills in `.claude/skills/` are `test-extract`, `add-broker`, `privacy-audit`, `local-llm-prompt`, `add-stage-endpoint` and `demo-preflight`. The agents in `.claude/agents/` are `privacy-reviewer`, `search-integrator`, `evidence-analyst`, `prompt-engineer` and `pitch-coach`.
