---
name: add-stage-endpoint
description: The pattern for wiring a pipeline stage module (server/stages/N-*.js) to an Express route under /api and calling it from the React UI in web/src. Use when implementing or exposing a stage (exposures, dates, breaches, policy, rank, resolve, alias), adding a new API endpoint, or hooking a UI button or card up to backend data.
---

# add-stage-endpoint

Stages: `1-exposures`, `2-dates`, `3-breaches`, `4-policy`, `5-rank`, `6-resolve`, `7-alias` in `server/stages/`. (Check the actual filenames; only 1 and 7 are fixed.)
MVP order: Stages 1, 4, 6 + the outbound log. Then 2, 3, 5. Stage 7 last.

## 1. Stage module: pure-ish, one export

```js
// server/stages/4-policy.js
import { extract } from '../services/tavily.js';      // services wrap outboundFetch
import { askJSON } from '../lib/ollama.js';
import * as P from '../prompts/policy.js';

export async function run({ companies }) {
  return Promise.all(companies.map(async (c) => {
    try { /* service calls -> askJSON -> P.validate */ }
    catch (err) { return { company: c.name, error: String(err.message), source: 'unavailable' }; }
  }));
}
```
Rules:
- External calls only through `server/services/*` (which use `outboundFetch`). Never `fetch` directly.
- Search queries use name + city only. Let `assertMinimalQuery` throw, then catch it and return an error, don't strip the data silently.
- Per-item try/catch: one blocked broker or company must not fail the whole stage.
- Every date or claim carries its `source` label (e.g. `"wayback"`, `"published"`, `"unknown"`).
- Read the service files for real function names before importing. Don't assume `extract`/`search` exist with those names.

## 2. Express route

Find where the app registers routes (the server entry, e.g. `server/index.js`, or a routes file). Follow the existing style:

```js
import * as policy from './stages/4-policy.js';
app.post('/api/policy', async (req, res) => {
  try { res.json(await policy.run(req.body)); }
  catch (err) { res.status(500).json({ error: err.message }); }
});
```
- Use `POST` with a JSON body for anything carrying personal data (name, city). Keep it out of URLs and query strings.
- Make sure `express.json()` is applied.
- Don't touch `GET /api/outbound`. It's the log.

## 3. UI call (web/src)

Vite proxies `/api` to :3001, so use relative URLs only:

```js
const res = await fetch('/api/policy', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ companies }),
});
const data = await res.json();
```
- Put loading and error states on the card. Show "unknown" or "unavailable" rather than blank.
- After any stage call, refresh `OutboundLog.jsx` (or let it poll `/api/outbound`) so the demo shows the new requests.
- Render evidence tiers as Proven, Likely or Possible, with the text "likely source".

## 4. Verify

1. `npm run dev`, then `curl -X POST localhost:3001/api/<stage> -H "Content-Type: application/json" -d '{...}'`.
2. Check that `GET /api/outbound` shows the new calls with the right `service` names.
3. Click through in the UI at :5173.
4. Run the `privacy-audit` skill if the stage adds a new service call.
