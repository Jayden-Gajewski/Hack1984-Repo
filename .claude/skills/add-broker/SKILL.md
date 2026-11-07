---
name: add-broker
description: Add a new data broker (people-search site) to server/data/brokers.json with its domain and opt-out URL, then verify that Tavily Extract or the search-snippet fallback actually finds a profile on it. Use when someone says "add <site> as a broker", "we should also scan <site>", or wants to expand Stage 1 / Stage 6 coverage.
---

# add-broker

## 1. Read the current shape first

Open `server/data/brokers.json` and copy the exact shape of an existing entry. Don't invent new keys.
At minimum each entry has the broker's **domain** and **opt-out URL**. Match the existing key names and casing exactly.
If the file has extra fields (e.g. a display name or a `method` flag), fill them in the same style.

## 2. Gather the facts

- **Domain:** the bare domain the broker serves profiles from, e.g. `example-people.com` (no scheme, no `www.` unless the others include it).
- **Opt-out URL:** find it with a Tavily search restricted to that domain via `outboundFetch`, or ask the user.
  Verify it's the broker's own opt-out/suppression page, not a third-party removal service's guide.
- Don't guess an opt-out URL. If you can't confirm it, set it to whatever the existing entries use for "unknown" (or `null`) and tell the user.

## 3. Add the entry

- Insert it alphabetically if the list is sorted, otherwise append.
- Keep valid JSON: no trailing commas. Check with `node -e "JSON.parse(require('fs').readFileSync('server/data/brokers.json','utf8'))"`.
- No duplicates. Grep the domain first.

## 4. Verify extraction works

Use a **consenting teammate's** name and city only (never phone or email).

1. Run the first-hour experiment against just this broker if the script supports filtering. Otherwise run it normally and read this broker's row:
   `node scripts/test-extract.js "<Name>" "<City, ST>"`
2. Classify the result (see the `test-extract` skill): **Extract OK**, **Extract thin**, or **Blocked**.
3. If blocked, confirm the fallback works: a Tavily search (`POST https://api.tavily.com/search` with `include_domains: ["<domain>"]`) or an Exa search (`POST https://api.exa.ai/search` with `includeDomains`) returns a snippet mentioning the teammate.
4. If neither extract nor snippets find anything, tell the user. The broker may still be worth keeping for opt-out drafting (Stage 6), but it won't produce exposure cards.

## 5. Report back

One or two lines: broker added, domain, opt-out URL (confirmed or not), extraction bucket, and whether Stage 1 will use extract or snippet fallback for it.

## Don'ts

- Don't call the broker site directly with `fetch`. Everything external goes through `outboundFetch`.
- Don't paste extracted page text into any cloud API. Only Ollama sees it.
- Don't commit test output containing a teammate's personal data.
