---
name: privacy-audit
description: Audit the codebase for privacy-track violations. Checks that every external HTTP call goes through outboundFetch, that search queries never contain an email or phone number, and that extracted page text and personal data are only ever sent to the local Ollama, never to Exa, Tavily or any other cloud API. Use before merging, before the demo, after adding a service or stage, or when someone asks "are we still privacy-safe?"
---

# privacy-audit

These are the Privacy-First track's claims, so each one has to be true in the code:
1. Every outbound request is logged (it goes through `outboundFetch` in `server/lib/outbound.js`).
2. Queries use name + city only, never email or phone (`assertMinimalQuery`).
3. Page text and analysis never leave the machine (only Ollama sees them).

Report each finding as `file:line`, the rule it breaks, and a one-line fix. Don't auto-fix unless asked.

## Check 1: no bypassing outboundFetch

Search `server/` and `scripts/` for raw network calls:
- `fetch(`, `axios`, `got(`, `node-fetch`, `undici`, `http.request`, `https.request`, `https.get`, `XMLHttpRequest`
- Hardcoded hosts: `api.exa.ai`, `api.tavily.com`, `archive.org`

Allowed:
- The real `fetch` inside `server/lib/outbound.js` itself.
- `server/lib/ollama.js` calling `http://localhost:11434` (or `OLLAMA_URL`). It's local, so flag it only if `OLLAMA_URL` could point off-machine. Note it as a warning, not a violation.

Also check `web/src/`: the browser should only call `/api/...` (proxied by Vite). Any absolute `https://` call from the frontend is a violation.

## Check 2: minimal queries

- Every Exa/Tavily **search query** string must pass through `assertMinimalQuery(text)` before `outboundFetch`. Trace each call in `server/services/exa.js` and `tavily.js` and check that the assertion is on the path (in the service or in outboundFetch itself).
- Look for queries built from user profile fields: grep for `email`, `phone`, `tel`, `dob`, `ssn` near query construction in `server/stages/`.
- Quick runtime test if the server is up: call `assertMinimalQuery` with `"Jane Doe jane@x.com"` and with `"Jane Doe 512-555-0100"`. Both must throw.

## Check 3: personal data only goes to Ollama

- Find every place extracted text (Tavily Extract `raw_content`, Exa `/contents` text, privacy policy text, mock inbox bodies) flows.
  It may go to: `askJSON` in `server/lib/ollama.js`, the UI via our own API, or local memory.
  It must NOT go into: the body of any Exa/Tavily/Wayback request, logs shipped elsewhere, or any other cloud SDK.
- Grep for cloud LLM SDKs or keys that shouldn't exist: `openai`, `anthropic`, `@google/generative-ai`, `OPENAI_API_KEY`, `cohere`, `groq`. Any hit is a violation.
- Check `package.json` dependencies for the same.
- Stage 7 (alias) must check the mock inbox locally. No search call there.

## Check 4: the outbound log is honest

- `GET /api/outbound` returns entries with service, URL, sanitized body and time.
- "Sanitized" must still show what query was sent (that's the point), but it must strip API keys (`x-api-key`, `Authorization`). Grep that headers aren't logged verbatim.
- `.env` is gitignored, and no key literals appear in the source (grep for `tvly-` and long hex strings).

## Output

```
PRIVACY AUDIT: PASS | FAIL
Violations: <n>   Warnings: <n>
- [FAIL] server/stages/3-breaches.js:42  raw fetch to api.tavily.com bypasses outboundFetch -> use tavily.js
- [WARN] server/lib/ollama.js:5  OLLAMA_URL from env, ensure it's localhost for demo
```
End with the pitch line you can now honestly say, or the one you can't yet.
