# API clients

Thin async wrappers, one per service. Each one builds a request, sends it through `outbound.request(...)`, and returns plain dicts or lists. No business logic here; that belongs in `stages/`.

Use REST, not vendor SDKs, so the outbound log shows the exact payload. Raise a clear `RuntimeError` when an API key is missing. Check the docs before relying on a parameter; these APIs change.

## Exa (`exa.py`), https://docs.exa.ai

- Auth: `x-api-key` header. Base URL: `https://api.exa.ai`.
- `POST /search`: `query`, `type: "auto"`, `numResults`, `includeDomains`, `excludeDomains`, `startPublishedDate` / `endPublishedDate` (ISO 8601), `category` (e.g. `"news"`), and `contents: {text: {maxCharacters}}` for snippets.
- `POST /findSimilar`: `url`, `numResults`, `excludeSourceDomain: true`. Stage 1 uses it to discover broker domains we don't already list.
- Results contain `url`, `title`, `publishedDate` and `text`.

## Tavily (`tavily.py`), https://docs.tavily.com

- Auth: `Authorization: Bearer <key>`. Base URL: `https://api.tavily.com`.
- `POST /search`: `query`, `topic` (`"general"` or `"news"`), `max_results`, `search_depth`, `include_domains`, `days` (news only).
- `POST /extract`: `urls` (up to 20 per call) and `extract_depth` (`"basic"` or `"advanced"`). Returns `results[{url, raw_content}]` and `failed_results[{url, error}]`. Return both, so callers can fall back to snippets.

## Wayback Machine (`wayback.py`)

- CDX API: `GET https://web.archive.org/cdx/search/cdx?url=<url>&output=json&fl=timestamp,original&filter=statuscode:200&limit=1`. Results come oldest first, and the first row is a header.
- Add `collapse=timestamp:6` to get one snapshot per month, for the per-field first-seen stretch goal.
- Raw archived page: `https://web.archive.org/web/<timestamp>id_/<url>`.
- No key is needed, but the service is slow and flaky. Use short timeouts and limit concurrency to about 4.
- The broker URL (which can include the user's name) goes to archive.org. That's expected, and it appears in the log.

## Ollama (`ollama.py`), local only

- `POST {OLLAMA_URL}/api/generate` with `model`, `prompt`, `system`, `format: "json"`, `stream: false` and `options: {temperature: 0, num_ctx: 8192}`.
- `GET {OLLAMA_URL}/api/tags` tells you whether Ollama is running and the model is pulled.
- Always pass `local=True` to `outbound.request`. `config.py` refuses to start if `OLLAMA_URL` isn't localhost. Don't remove that check.
