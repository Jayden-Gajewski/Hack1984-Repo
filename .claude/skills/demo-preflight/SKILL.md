---
name: demo-preflight
description: Pre-demo checklist for the 3-minute pitch. Verifies Ollama is running with the model pulled, API keys are set, npm run dev starts both servers, the mock inbox has an alias match, and the outbound log renders, then walks through the 6-step demo script and flags anything that would break live. Use before judging, before a rehearsal, or when someone asks "are we demo-ready?"
---

# demo-preflight

Run the checks in order and report a PASS/FAIL line for each. Stop and fix blockers before the walkthrough. Never print key values.

## Environment

1. **Keys:** `.env` has non-empty `EXA_API_KEY`, `TAVILY_API_KEY`, `OLLAMA_MODEL` and `OLLAMA_URL`. Check presence only.
2. **Ollama up:** `curl -s http://localhost:11434/api/tags` returns JSON. If it fails, run `ollama serve` (or start the Ollama app).
3. **Model pulled:** `OLLAMA_MODEL` appears in the `/api/tags` model list. If it's missing, run `ollama pull <model>`. Do this on venue Wi-Fi early because it's slow.
4. **Model warm:** send one tiny `askJSON` call so the first live call isn't a cold-start pause. Note the latency.
5. **OLLAMA_URL is localhost.** The privacy claim depends on it.

## App

6. `npm run dev`: Express on :3001 and Vite on :5173 both start without errors.
7. `curl -s localhost:3001/api/outbound` returns JSON (an array or log object).
8. Open :5173. The page loads, the proxy works (no CORS or 404 on `/api/*`), and there are no console errors.

## Data

9. `server/data/brokers.json`, `companies.json` and `mock-inbox.json` all parse as JSON.
10. **Alias match exists:** `mock-inbox.json` has at least one message sent to a generated alias from a sender that is *not* the company the alias was made for. Stage 7 must flag it as **Proven**.
11. `companies.json` has the demo company whose privacy policy contains a sell/share clause (for "this wasn't a hack, they sold it").

## Walk the 6-step demo script

Do a full dry run against the consenting teammate. Time it (target about 3 minutes):

1. **Scan live.** Enter name + city, then run Stage 1. Exposure cards show with source URLs. *Risk: slow or blocked brokers. Have a known-good broker list and the snippet fallback ready.*
2. **Open a card.** It shows fields, the Wayback "public by" date with its source label (or "unknown"), and the likely source with its evidence tier.
3. **Policy flag.** The Stage 4 clause quote is visible with "this wasn't a hack, they sold it".
4. **Draft opt-out.** Click it, and Stage 6 produces a request with the broker's opt-out URL from `brokers.json`.
5. **Alias match.** Stage 7 shows the mock inbox hit as **Proven**.
6. **Outbound log.** The `OutboundLog` panel lists every Exa, Tavily and Wayback request with what was sent. Confirm that **no email or phone appears in any logged query** and that no request goes to anything other than Exa, Tavily, the Wayback Machine or localhost. Closing line: "Here's everything that left this laptop."

Wording check on screen: it always says "likely source", never "who leaked it".

## Backup plan

- If the network is flaky: does the UI handle a failed stage gracefully (cards show "unavailable" and the app doesn't crash)? Suggest recording a screen capture of a good run as a fallback.
- If quota is low: check the Exa and Tavily usage dashboards and avoid repeated full scans during rehearsals.

## Report

```
PREFLIGHT: READY | NOT READY
[PASS] Ollama up, model <name> pulled, warm call 1.8s
[FAIL] mock-inbox.json: no alias match -> add one message to alias X from sender Y
Dry run: 3m10s, slowest step: 1 (Stage 1, 42s)
```
Run the `privacy-audit` skill too if code changed since the last audit.
