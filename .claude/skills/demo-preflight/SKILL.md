---
name: demo-preflight
description: Pre-demo checklist for the 3-minute pitch. Verifies Ollama is running with the model pulled, API keys are set, Postgres is up, the FastAPI backend and the Next.js production build both start, the mock inbox has an alias match, and the outbound log renders, then walks through the 6-step demo script and flags anything that would break live. Use before judging, before a rehearsal, or when someone asks "are we demo-ready?"
---

# demo-preflight

Run the checks in order and report a PASS/FAIL line for each. Stop and fix blockers before the walkthrough. Never print key values.

## Environment

1. **Keys:** `.env` at the repo root has non-empty `EXA_API_KEY`, `TAVILY_API_KEY`, `OLLAMA_MODEL` and `OLLAMA_URL`. Check presence only (`GET /api/status` reports it as booleans).
2. **Ollama up:** `curl -s http://localhost:11434/api/tags` returns JSON. If it fails, run `ollama serve` (or start the Ollama app).
3. **Model pulled:** `OLLAMA_MODEL` appears in the `/api/tags` model list. If it's missing, run `ollama pull <model>`. Do this on venue Wi-Fi early because it's slow.
4. **Model warm:** send one tiny local call, e.g. `curl -s localhost:11434/api/generate -d '{"model":"<model>","prompt":"hi","stream":false}'`, so the first live call isn't a cold-start pause. Note the latency.
5. **OLLAMA_URL is localhost.** The privacy claim depends on it. (`config.py` refuses anything else, so the backend won't start if it's wrong.)
6. **Postgres up:** `docker compose up -d`, and `GET /api/status` shows `"database": true`. Run one good scan before the demo so "Load last scan" has something to load.
7. **Next.js telemetry off** on the demo laptop: `cd frontend && npx next telemetry status` says it's disabled.

## App

8. `cd backend && pytest` passes, and `uvicorn app.main:app` starts on :8000 without errors.
9. `cd frontend && npm run demo` builds and serves on :3000. (Use the production build for the demo: it skips the dev server's version check against npm.)
10. `curl -s localhost:3000/api/outbound-log` returns a JSON array, which proves the proxy works.
11. Open http://localhost:3000. The status line shows the local LLM ready, Postgres up and both keys set, and the browser console has no errors.

## Data

12. `backend/app/data/*.json` all parse and have the expected keys (`cd backend && pytest tests/test_data.py`).
13. **Alias match exists:** `mock_inbox.json` has at least one message sent to an alias in `mock_aliases.json` from a sender that is *not* that alias's company. Stage 7 must flag it as **Proven**. (`tests/test_data.py` checks the fixture.)
14. `companies.json` has the demo company whose privacy policy contains a sell/share clause (for "this wasn't a hack, they sold it").

## Walk the 6-step demo script

Do a full dry run against the consenting teammate. Time it (target about 3 minutes):

1. **Scan live.** Enter name + city, then run Stage 1. Exposure cards show with source URLs. *Risk: slow or blocked brokers. Have a known-good broker list and the snippet fallback ready.*
2. **Open a card.** It shows fields, the "public by" date with its source label (or "unknown"), and the likely source with its evidence tier.
3. **Policy flag.** The Stage 4 clause quote is visible with "this wasn't a hack, they sold it".
4. **Draft opt-out.** Click it, and Stage 6 produces a request with the broker's opt-out URL from `backend/app/data/brokers.json`.
5. **Alias match.** Stage 7 shows the mock inbox hit as **Proven**.
6. **Outbound log.** The outbound log panel lists every Exa, Tavily and Wayback request with what was sent. Confirm that **no email or phone appears in any logged query** and that no request goes to anything other than Exa, Tavily, the Wayback Machine or localhost. Closing line: "Here's everything that left this laptop."

Wording check on screen: it always says "likely source", never "who leaked it".

## Backup plan

- If the network is flaky: does the UI handle a failed stage gracefully (cards show "unavailable" and the app doesn't crash)? "Load last scan" reads the last saved scan from local Postgres. Suggest recording a screen capture of a good run as a fallback too.
- If quota is low: check the Exa and Tavily usage dashboards and avoid repeated full scans during rehearsals.

## Report

```
PREFLIGHT: READY | NOT READY
[PASS] Ollama up, model <name> pulled, warm call 1.8s
[FAIL] mock_inbox.json: no alias match -> add one message to alias X from sender Y
Dry run: 3m10s, slowest step: 1 (Stage 1, 42s)
```
Run the `privacy-audit` skill too if code changed since the last audit.
