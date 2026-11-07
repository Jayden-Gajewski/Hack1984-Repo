# Hack1984

Find out where your personal data is exposed, which company most likely leaked it, and get it taken down, without handing your data to yet another company.

The full pitch, build order and demo script are in [docs/PITCH.md](docs/PITCH.md).

## Setup

1. Install **Node 20 or later** (check with `node -v`). Then install **Ollama** from https://ollama.com and pull a model:
   ```
   ollama pull llama3.1:8b
   ```
2. Install dependencies and create your env file:
   ```
   npm install
   cp .env.example .env    # then paste in your EXA_API_KEY and TAVILY_API_KEY
   ```
3. Check that the local LLM works:
   ```
   npm run check:ollama
   ```
4. Run the app:
   ```
   npm run dev
   ```
   The UI is at http://localhost:5173 and the API is at http://localhost:3001.

## First hour: extraction test

Use a teammate's name, and only with their permission:

```
npm run test:extract -- "First Last" "City" "ST"
```

This shows which brokers Tavily Extract can read and which ones need the search-snippet fallback. The output goes to `scripts/output/`, which is gitignored.

## Layout

```
server/
  index.js            Express routes, one per stage
  lib/outbound.js     outboundFetch(): the ONLY way to call the internet (it's logged)
  lib/ollama.js       askJSON(): calls the local LLM
  services/           exa.js, tavily.js, wayback.js
  stages/             1-exposures … 7-alias, one file per pitch stage
  prompts/index.js    every LLM prompt
  data/               brokers.json, companies.json, mock-inbox.json
web/src/              React UI (cards, policy flags, alias panel, outbound log)
scripts/              test-extract.js, check-ollama.js
.claude/              shared Claude Code skills and agents
```

## Team split

| Role | Files |
|---|---|
| Search & extract (Stages 1, 6) | `server/services/exa.js`, `tavily.js`, `stages/1-exposures.js`, `stages/6-resolve.js`, `data/brokers.json` |
| Evidence (Stages 2–4) | `services/wayback.js`, `stages/2-dates.js`, `3-breaches.js`, `4-policy.js` |
| Local LLM & ranking (Stage 5, alias) | `lib/ollama.js`, `prompts/`, `stages/5-rank.js`, `7-alias.js` |
| UI & demo | `web/`, the outbound log panel, the pitch |

## Privacy rules (don't break these)

- Every external request goes through `outboundFetch`. Never call `fetch()` directly in `server/`.
- Search queries use name and city only. `assertMinimalQuery` blocks emails and phone numbers.
- Page text and analysis go only to local Ollama, never to a cloud LLM.
- Say "likely source", never "who leaked it". Label every date with its source.

## Git workflow

```
git checkout main && git pull
git checkout -b your-feature
# ...work...
git push -u origin your-feature   # then open a PR into main
```

## Claude Code helpers

The skills in `.claude/skills/` are `test-extract`, `add-broker`, `privacy-audit`, `local-llm-prompt`, `add-stage-endpoint` and `demo-preflight`. The agents in `.claude/agents/` are `privacy-reviewer`, `search-integrator`, `evidence-analyst`, `prompt-engineer` and `pitch-coach`.
