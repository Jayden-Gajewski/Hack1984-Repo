---
name: test-extract
description: Run and interpret the first-hour Tavily Extract experiment (backend/scripts/test_extract.py) against data broker pages for a name and city, then decide how Stage 1 should work (extract vs. search-snippet fallback) per broker. Use when someone asks to "run the extract test", check whether a broker can be extracted, debug empty or blocked extraction results, or decide Stage 1's strategy.
---

# test-extract

The first-hour experiment decides how Stage 1 works. It answers one question per broker:
**does Tavily Extract return usable page text containing the subject's data, or do we fall back to search snippets?**

## Preconditions

1. `.env` at the repo root has `TAVILY_API_KEY` (the script exits with a clear message without it). Do not print the key.
2. A **consenting teammate's** name and city. Never test on someone who has not agreed. Name and city only, no phone or email (`assert_minimal_query` rejects them before anything is sent).
3. The backend venv is set up (`cd backend && pip install -r requirements.txt`).

## Run it

From `backend/`:

```
python -m scripts.test_extract --name "Jane Doe" --city "Austin" --state "TX"
```

For each broker in `backend/app/data/brokers.json`, it runs one Tavily search restricted to that broker's domain, then Tavily Extract on the top hit. All calls go through `outbound.request` in `backend/app/outbound.py` (service `"tavily"`): `POST https://api.tavily.com/search` and `POST https://api.tavily.com/extract`, with `Authorization: Bearer <key>`. The full report, including the outbound log, is written to `backend/local/extract-report.json` (gitignored).

The script prints one row per broker with a first-pass bucket (`OK`, `thin` or `BLOCKED`). Check the report before trusting it, using the rules below.

## Interpret each broker result

Classify every broker into exactly one bucket and report a table:

| Bucket | Signal | Stage 1 strategy |
|---|---|---|
| **Extract OK** | `results[]` entry with `raw_content` containing the name and at least one of city/age/relatives/address | Extract, then send the text to the local LLM (Ollama) for field listing |
| **Extract thin** | Content returned but it's a search/landing page, captcha text, or "no results" | Try a more specific profile URL (from a Tavily search with `include_domains`) before falling back |
| **Blocked** | URL appears in `failed_results`, empty content, or 403/429 | Fall back to search snippets (Tavily search restricted to the broker domain, or Exa search) |

Rules for interpreting:
- A name match alone is not enough. Look for a second identifier (city, age, relative) before calling it a hit.
- Count characters of `raw_content`. Under ~500 chars is almost always a block page or captcha.
- Note the latency per broker (the `ms` field in the report's `outbound` entries). Anything over ~10s is a demo risk.

## Output to the team

Post a short summary:
1. The table above (broker, bucket, chars returned, latency).
2. Recommendation: which brokers to use with extract, which with snippet fallback.
3. Any broker to drop from `backend/app/data/brokers.json` for the demo (blocked and no useful snippets).
4. Record the decision under Stage 1 in `backend/app/stages/CLAUDE.md`.

## Privacy reminders

- Extracted page text is personal data. Send it **only** to Ollama (`ask_json` in `backend/app/clients/ollama.py`), never to Exa, Tavily, or any other cloud API.
- Don't commit raw output containing the teammate's data. The script writes to `backend/local/`, which is gitignored; keep it there.
- The report's `outbound` section lists every request the script made. If a call is missing from it, something bypassed `outbound.request`, so fix that first.
