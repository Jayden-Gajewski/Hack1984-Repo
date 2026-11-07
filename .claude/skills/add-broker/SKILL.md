---
name: add-broker
description: Add a new data broker (people-search site) to backend/app/data/brokers.json with its domain and opt-out URL, then verify that Tavily Extract or the search-snippet fallback actually finds a profile on it. Use when someone says "add <site> as a broker", "we should also scan <site>", or wants to expand Stage 1 / Stage 6 coverage.
---

# add-broker

## 1. Read the current shape first

Open `backend/app/data/brokers.json`. Each entry is `{"id", "name", "domain", "opt_out_url"}` in snake_case, with `opt_out_url` set to `null` when it's unknown. `backend/tests/test_data.py` checks these keys, so don't add new ones without updating it.

## 2. Gather the facts

- **Domain:** the bare domain the broker serves profiles from, e.g. `example-people.com` (no scheme, no `www.`).
- **Opt-out URL:** find it with a Tavily search restricted to that domain (`clients.tavily.search(..., include_domains=[domain])`, which goes through `outbound.request`), or ask the user.
  Verify it's the broker's own opt-out or suppression page, not a third-party removal service's guide.
- Don't guess an opt-out URL. If you can't confirm it, set `opt_out_url` to `null` and tell the user.

## 3. Add the entry

- Insert it alphabetically if the list is sorted, otherwise append.
- Keep valid JSON: `cd backend && python -m json.tool app/data/brokers.json > /dev/null && pytest tests/test_data.py`.
- No duplicates. Grep the domain first.

## 4. Verify extraction works

Use a **consenting teammate's** name and city only (never phone or email).

1. Run the first-hour experiment (it checks every broker in the file) and read this broker's row:
   `cd backend && python -m scripts.test_extract --name "<Name>" --city "<City>" --state "<ST>"`
2. Classify the result (see the `test-extract` skill): **Extract OK**, **Extract thin**, or **Blocked**.
3. If blocked, confirm the fallback works: a Tavily search with `include_domains=["<domain>"]` or an Exa search with `include_domains` returns a snippet mentioning the teammate. Use the clients in `backend/app/clients/`, not raw curl with keys pasted in.
4. If neither extract nor snippets find anything, tell the user. The broker may still be worth keeping for opt-out drafting (Stage 6), but it won't produce exposure cards.

## 5. Report back

One or two lines: broker added, domain, opt-out URL (confirmed or not), extraction bucket, and whether Stage 1 will use extract or snippet fallback for it.

## Don'ts

- Don't call the broker site directly with `httpx`. Everything external goes through `outbound.request`.
- Don't paste extracted page text into any cloud API. Only Ollama sees it.
- Don't commit test output containing a teammate's personal data. Keep it in `backend/local/`.
