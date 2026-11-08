# API clients

Thin async wrappers, one per service. Each one builds a request, sends it through `outbound.request(...)`, and returns plain dicts or lists. No business logic here; that belongs in `stages/`.

Use REST, not vendor SDKs, so the outbound log shows the exact payload. Raise a clear `RuntimeError` when an API key is missing. Check the docs before relying on a parameter; these APIs change.

## Exa (`exa.py`), https://exa.ai/docs

- Auth: `x-api-key` header. Base URL: `https://api.exa.ai`.
- `POST /search`: the default body is `query`, `type: "auto"` and `contents: {highlights: true}`, nothing else. Add `objective` (the goal this search serves; guarded like the query) when the search is one step of a stage. Only add `numResults`, `includeDomains`, `category` or `startPublishedDate` when the stage needs it (broker allowlist, breach date window). Don't stack `text`/`summary` on top of `highlights`.
- `/findSimilar` is deprecated. To discover brokers we don't list, use `search` with a company-only query (e.g. "people search sites like spokeo.com"), never a page URL or title that contains the user's name.
- Results contain `url`, `title`, `publishedDate` and `highlights` (list of strings). `exa.snippet(result)` joins them for the snippet fallback.

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

- `POST {OLLAMA_URL}/api/generate` with `model`, `prompt`, `system`, `format: "json"`, `stream: false` and `options: {temperature: 0, num_ctx, num_predict}`, with `num_ctx` and `keep_alive` from `.env` (`OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`). Every call sends the same `num_ctx`, warm-up included, or Ollama reloads the model.
- `GET {OLLAMA_URL}/api/tags` tells you whether Ollama is running and the model is pulled.
- Always pass `local=True` to `outbound.request`. `config.py` refuses to start if `OLLAMA_URL` isn't localhost. Don't remove that check.

## Have I Been Pwned (`hibp.py`), https://haveibeenpwned.com/API/v3

- A `user-agent` is required on every request (outbound sets one). Breach data is CC BY 4.0: show "Have I Been Pwned" with a link.
- `GET /api/v3/breaches`: the whole catalog, no key. Match companies locally; don't use `?Domain=`, which would tell HIBP which companies the user has.
- `GET /api/v3/breachedaccount/range/{first 6 hex of SHA-1}`: the k-anonymity email search, with the `hibp-api-key` header, on Pro or High RPM plans only. It returns `[{hashSuffix, websites}]`. Keep the matching suffix and discard the rest immediately (HIBP's terms). `range_search()` refuses anything but a 6-character hex prefix.
- Errors: 401 is a bad key, 403 is a plan without the hashed search, and 429 sends `retry-after` (`HibpError.retry_after`).
- Breach pages: `https://haveibeenpwned.com/Breach/{Name}`. `Description` is HTML: strip it to text and never render it as HTML.
