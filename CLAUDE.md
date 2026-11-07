# Hack1984: personal data exposure finder

**Pitch:** Find out where your personal data is exposed, which company most likely leaked it, and get it taken down, without handing your data to yet another company.

**Tracks:** Surge (Exa and Tavily run the core), Most Startup-able (people already pay for data removal), Privacy-First (analysis runs locally; every outbound request is logged).

## Privacy rules (non-negotiable)

These rules are the product. Do not break them, even temporarily, even to debug.

1. **Analysis runs locally.** Page text, policy text and all LLM analysis go only to Ollama on localhost. Never send page content to Exa, Tavily or a hosted LLM. Never add a hosted LLM API.
2. **One door out.** Every network request goes through `backend/app/outbound.py`. No direct `httpx`/`requests` calls or vendor SDKs anywhere else. That module feeds the outbound log panel.
3. **Minimal queries.** Search with name + city/state only, or a company name. Never send phone numbers, emails, SSNs or birthdates. `outbound.py` rejects queries that contain them. Don't weaken that check.
4. **Self-scan only.** A scan requires a `consent: true` flag. Demos use a consenting teammate.
5. **User data stays out of git.** User data lives in memory or in `backend/local/` (gitignored). Never commit real scan results, names or page text. Fixtures use fictional people and `.example` domains.
6. **Wording.** Say "likely source", never "who leaked it" or "leaked by". Every date shows its source. A missing date is "unknown", never a guess.

## Stack

- **Backend:** Python 3.13, FastAPI, async `httpx`, pydantic v2. Call the Exa and Tavily REST APIs directly (not their SDKs), so the log captures exactly what was sent.
- **Local LLM:** Ollama in JSON mode. The model is set by `OLLAMA_MODEL` (default `llama3.1:8b`).
- **Frontend:** plain HTML/CSS/JS in `frontend/`, served by FastAPI. No build step.
- **Config:** `.env` at the repo root (`EXA_API_KEY`, `TAVILY_API_KEY`, `OLLAMA_URL`, `OLLAMA_MODEL`, `ALIAS_DOMAIN`). Commit `.env.example`, never `.env`.
- **State:** in memory, plus JSON files in `backend/local/`. Single user, runs on one laptop.

## Don't build

User accounts or auth, real Gmail/IMAP integration, vector databases, agent frameworks (LangChain, CrewAI, etc.), multiple agents, a real database, frontend frameworks or bundlers. If a task seems to need one of these, stop and ask.

## Layout (target; create files here as you build)

```
backend/
  app/
    main.py          FastAPI routes; also serves frontend/
    config.py        loads .env; refuses a non-localhost OLLAMA_URL
    outbound.py      logged HTTP client + minimal-query check
    models.py        pydantic models = the API contract with the frontend
    prompts.py       local LLM prompts
    clients/         exa.py, tavily.py, wayback.py, ollama.py
    stages/          s1_exposures.py ... s7_aliases.py
    data/            checked-in reference data: brokers.json, companies.json,
                     breach_sources.json, mock_inbox.json, mock_aliases.json
  local/             gitignored: aliases, saved scans
  scripts/           one-off tests, e.g. test_extract.py
  requirements.txt
frontend/            index.html, app.js, styles.css
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

**Shared files:** `models.py`, `outbound.py` and the API routes in `main.py` affect everyone. Keep changes to them additive, and call them out in the commit message.

## Build order

1. **First hour:** `backend/scripts/test_extract.py` runs Tavily Extract on Spokeo, Whitepages and similar sites with a teammate's name. The result decides whether Stage 1 relies on extracted text or on search snippets.
2. **MVP:** Stages 1, 4 and 6 plus the outbound log. That is a complete demo on its own.
3. **Then:** Wayback dates (2), breach timelines (3), evidence-tier ranking (5).
4. **Last:** a mocked inbox showing one alias match (7).

Finish the current tier before starting the next.

## Commands

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
ollama pull llama3.1:8b
uvicorn app.main:app --reload     # http://localhost:8000
python -m scripts.test_extract --name "Jane Doe" --city "Boston" --state "MA"
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
