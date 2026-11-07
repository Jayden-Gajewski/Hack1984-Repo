# Pipeline stages

One module per stage. Each exposes async functions that take and return `models.py` types, plus a list of error strings when something partially fails. Stages call `clients/` and never make HTTP calls directly. Stage 5 and the matching logic in Stage 7 make no network calls at all.

## Stage 1: Find exposures (`s1_exposures.py`, Search & extract)

1. **Discover candidates:**
   - Tavily search on `"{name} {city} {state}"` restricted to the known broker domains in `data/brokers.json`.
   - Exa semantic search for the same person plus "people search profile".
   - Exa search for sites like a known broker (company-only query, e.g. "people search sites like spokeo.com"; `/findSimilar` is deprecated). Collect the new domains it returns, then run a Tavily search restricted to them.
2. **Pre-filter cheaply:** drop candidates whose URL, title and snippet don't contain the last name.
3. **Extract:** Tavily Extract on all candidates. When a broker blocks extraction, fall back to the search snippet, and record `text_source: "snippet"` so the UI can say so.
4. **Analyze locally:** the LLM decides whether the page is this person and which `FIELD_TYPES` it shows, with a short quote per field. Keep matches with confidence ≥ 0.5.
5. Attach `broker` and `opt_out_url` from `brokers.json` when the domain is known.

The first-hour test (`scripts/test_extract.py`) decides how much Stage 1 can rely on extracted text versus snippets. Record the result in this file once it's known.

**Built.** Choices worth knowing, all in `s1_exposures.py`:
- The Tavily query quotes only the name: `"Jane Doe" Springfield IL`.
- Before any search, it checks for a search key and a running Ollama with the model pulled, so a scan never spends credits on pages it can't analyze.
- The last-name filter looks at the URL path, title and snippet, never the domain.
- At most 20 candidates per scan (known brokers first), since each one is a local LLM call.
- Extracted text under 500 chars, or without the last name, counts as blocked and falls back to the snippet.
- Pages on domains not in `brokers.json` must also have `is_people_search_site: true` from the LLM, so news stories and social profiles don't become cards.
- Every field quote must appear in the page text; fields are limited to `prompts.LISTING_FIELDS`.
- Tests: `tests/test_s1_exposures.py` runs the whole stage against a fake internet.

## Stage 2: Date them (`s2_dating.py`, Evidence)

- **"Public by"** is the date of the earliest Wayback snapshot, with `source: "wayback"` and the snapshot link as evidence.
- If there's no snapshot, use the Exa/Tavily published date with `source: "published_date"`.
- If there's neither, use `date: null, source: "unknown"`. Never guess.
- **Stretch:** fetch a few monthly snapshots, run the Stage 1 field prompt on each (locally), and record when each field first appears.

## Stage 3: Breach timelines (`s3_breaches.py`, Evidence)

- Runs for each company the user picks from `data/companies.json`. Queries contain the company name only.
- **Sources:**
  - Tavily news search.
  - Tavily search restricted to the state attorney general domains in `data/breach_sources.json` (these pages list the date and data types).
  - Exa search with `startPublishedDate`.
- The local LLM merges the snippets into breach events: `date`, `date_kind` (occurred, disclosed or unknown), `data_types`, `source_url` and `summary`.
- Normalize `data_types` to `FIELD_TYPES` (watch out: "email addresses" means `email`, not `address`). Label each date's source, and prefer AG notices.

## Stage 4: Policy check (`s4_policy.py`, Evidence)

- Find the privacy policy URL: use `privacy_url` from `companies.json` if set, or else a Tavily search restricted to the company's domain.
- Run Tavily Extract with `advanced` depth, chunk the text (about 10k chars, at most 6 chunks), and have the LLM flag clauses by chunk.
- Each clause gets a `category` (sale, sharing, advertising, affiliates or data_broker), the exact `quote` and a one-line plain-English `explanation`.
- Sharing with service providers, or sharing that's only legally required, does not count.
- This stage is the source of the demo line "this wasn't a hack, they sold it", so the quote must be verbatim.

## Stage 5: Rank likely sources (`s5_ranking.py`, Local LLM & ranking)

Pure function: `(exposures, breaches, policies, alias_hits) -> exposures with leads`.

| Tier | Rule |
|---|---|
| **Proven** | An alias given only to company X received mail from someone else. Attach it to an exposure when the sender's domain is that broker. |
| **Likely** | A breach at X falls 0 to 3 years before the listing's "public by" date, **and** the breach exposed at least one field the listing shows. |
| **Possible** | X's privacy policy allows selling or sharing data. |

- Keep one lead per company at its strongest tier, with all the reasons.
- Every reason is a human-readable sentence that cites dates and their sources.
- Sort leads Proven, then Likely, then Possible.
- Never use the words "leaked by" or "who leaked it".

## Stage 6: Resolve (`s6_resolve.py`, Search & extract)

- **Broker opt-out URL:** `brokers.json`, or else a Tavily search restricted to the broker's domain for "opt out remove my information".
- **Company privacy contact:** a Tavily search restricted to the company's domain. Prefer a `privacy@` style email on that domain, and fall back to the request page URL.
- **Drafts:** fixed templates filled in locally (deterministic for the demo).
  - Broker: delete the listing, opt out of sale and sharing, say where you got my data.
  - Company: list the third parties you sold or shared my data with, opt me out, delete my data.
  - Name and city only, never more.
- **Re-scan:** re-extract old listing URLs. `removed` means the page loaded and no longer names the user, `still_listed` means it does, and `unconfirmed` means the page was blocked or failed. This is the subscription hook.

## Stage 7: Aliases (`s7_aliases.py`, Local LLM & ranking)

- Format: `{company-slug}.{6 random hex}@{ALIAS_DOMAIN}`. Save aliases to the `aliases` table in Postgres.
- **Inbox check (local only, no search):** for each message sent to a known alias, if the sender's domain isn't the assigned company's domain or one of its subdomains, it's an `AliasHit` with tier Proven.
- The demo uses `data/mock_inbox.json` and `data/mock_aliases.json`. Use a fictional company and `.example` domains, never a real company accused on fake data. Include one legitimate email from the company itself, to show it isn't flagged.
