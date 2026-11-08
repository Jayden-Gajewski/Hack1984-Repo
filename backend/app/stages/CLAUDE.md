# Pipeline stages

One module per stage. Each exposes async functions that take and return `models.py` types, plus a list of error strings when something partially fails. Stages call `clients/` and never make HTTP calls directly. Stage 5 and the matching logic in Stage 7 make no network calls at all.

## Stage 1: Find exposures (`s1_exposures.py`, Search & extract)

1. **Discover candidates:**
   - Tavily search on `"{name} {city} {state}"` restricted to the known broker domains in `data/brokers.json`.
   - A separate Tavily search, same query, restricted to the public-profile sites in `data/public_profiles.json` (sports results pages like Athletic.net that show a name with a school or team). These become cards with `source_kind: "public_profile"`, and the LLM is asked for `prompts.PROFILE_FIELDS` (name, school, age, employer) instead of the broker fields.
   - Exa semantic search for the same person plus "people search profile".
   - Exa search for sites like a known broker (company-only query, e.g. "people search sites like spokeo.com"; `/findSimilar` is deprecated). Collect the new domains it returns, then run a Tavily search restricted to them.
2. **Pre-filter cheaply:** drop candidates whose URL, title and snippet don't contain the last name.
3. **Extract:** Tavily Extract on all candidates. When a broker blocks extraction, fall back to the search snippet, and record `text_source: "snippet"` so the UI can say so.
4. **Analyze locally:** the LLM decides whether the page is this person and which `FIELD_TYPES` it shows, with a short quote per field. Keep matches with confidence ≥ 0.5.
5. Attach `broker`, `source_kind` and `opt_out_url` from `brokers.json` or `public_profiles.json` when the domain is known.

The first-hour test (`scripts/test_extract.py`) decides how much Stage 1 can rely on extracted text versus snippets. Record the result in this file once it's known.

**Built.** Choices worth knowing, all in `s1_exposures.py`:
- The Tavily query quotes only the name: `"Jane Doe" Springfield IL`.
- Before any search, it checks for a search key and a running Ollama with the model pulled, so a scan never spends credits on pages it can't analyze.
- The last-name filter looks at the URL path, title and snippet, never the domain.
- At most 20 candidates per scan (known brokers first), since each one is a local LLM call.
- Extracted text under 500 chars, or without the last name, counts as blocked and falls back to the snippet.
- Pages on domains in neither `brokers.json` nor `public_profiles.json` must also have `is_people_search_site: true` from the LLM, so news stories and social profiles don't become cards.
- Every field quote must appear in the page text; fields are limited to `prompts.LISTING_FIELDS`.
- Tests: `tests/test_s1_exposures.py` runs the whole stage against a fake internet.

## Stage 2: Date them (`s2_dating.py`, Evidence)

- **"Public by"** is the date of the earliest Wayback snapshot, with `source: "wayback"` and the snapshot link as evidence.
- If there's no snapshot, use the Exa/Tavily published date with `source: "published_date"`.
- If there's neither, use `date: null, source: "unknown"`. Never guess.
- **Stretch:** fetch a few monthly snapshots, run the Stage 1 field prompt on each (locally), and record when each field first appears.

**Built** (`s2_dating.py`), except the stretch goal:
- One CDX lookup per listing, at most 4 at once with a 10 s timeout. `www.`, `http` and trailing-slash variants of a URL match the same snapshot.
- If archive.org errors or times out, that listing falls back to `published_date` or "unknown" like a missing snapshot, and the scan's errors say how many lookups failed.
- A CDX timestamp that isn't 14 digits is ignored rather than turned into a date.
- Tests: `tests/test_s2_dating.py` covers every fallback; `tests/test_s1_exposures.py` checks dates end to end through `/api/scan`.

## Stage 3: Breach timelines (`s3_breaches.py`, Evidence)

- Runs for each company the user picks from `data/companies.json`. Queries contain the company name only.
- **Sources:**
  - Tavily news search.
  - Tavily search restricted to the state attorney general domains in `data/breach_sources.json` (these pages list the date and data types).
  - Exa search with `startPublishedDate`.
- The local LLM merges the snippets into breach events: `date`, `date_kind` (occurred, disclosed or unknown), `data_types`, `source_url` and `summary`.
- Normalize `data_types` to `FIELD_TYPES` (watch out: "email addresses" means `email`, not `address`). Label each date's source, and prefer AG notices.

**Built** (`s3_breaches.py`). Tested on Ticketmaster; these choices came from real results:
- Tavily news needs `days` (3650 here): it only looks back 7 days by default. Its dates come as RFC 2822 strings.
- News and web results must name the company in their title or URL; AG notices may name it in the text only. Passing mentions were most of the noise.
- The LLM cites sources by number, never URL. A date is kept only if its year appears in that source, and a data type only if that source mentions it (the model copied the whole type list otherwise).
- Events merge per company and year: AG notice first, then an "occurred" date, then the most precise. Undated events show only for a company with no dated ones.

## Stage 4: Policy check (`s4_policy.py`, Evidence)

- Find the privacy policy URL: use `privacy_url` from `companies.json` if set, or else a Tavily search restricted to the company's domain.
- Run Tavily Extract with `advanced` depth, chunk the text (about 10k chars, at most 6 chunks), and have the LLM flag clauses by chunk.
- Each clause gets a `category` (sale, sharing, advertising, affiliates or data_broker), the exact `quote` and a one-line plain-English `explanation`.
- Sharing with service providers, or sharing that's only legally required, does not count.
- This stage is the source of the demo line "this wasn't a hack, they sold it", so the quote must be verbatim.

**Built** (`s4_policy.py`). llama3.1:8b mislabeled many sentences, so the design changed:
- The code pulls out sentences that mention selling, sharing, third parties, affiliates, advertising or brokers, numbers them, and the LLM only picks numbers. Quotes are verbatim by construction.
- Every pick must pass checks in code: no denials ("we do not sell"), merger boilerplate, legal definitions, statements of the user's rights, headings or table rows; it must be in the company's voice; service providers alone don't count.
- A strict pattern also flags plain "we share/sell ... with third parties/partners" sentences, because the model's picks vary between runs.
- Blocked policies fall back to search snippets from the company's own domains (AT&T needs this).

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

**Built** (`s5_ranking.py`), pure. "Name" never counts as a shared field; a listing's age matches a breach's birthdate. A breach dated only "2024" can't be Likely for a listing public by mid-2024 (it might be after). `tests/test_pipeline_routes.py` runs scan, accounts, inbox and leads through the routes.

## Stage 6: Resolve (`s6_resolve.py`, Search & extract)

- **Broker opt-out URL:** `brokers.json`, or else a Tavily search restricted to the broker's domain for "opt out remove my information".
- **Public profiles** get a removal request (remove or hide the profile, keep it out of search engines) instead of an opt-out, with `Draft.kind = "public_profile"`. Removal page: `public_profiles.json`, or else a Tavily search on the site's domain for "remove my profile privacy request".
- **Company privacy contact:** a Tavily search restricted to the company's domain. Prefer a `privacy@` style email on that domain, and fall back to the request page URL.
- **Drafts:** fixed templates filled in locally (deterministic for the demo).
  - Broker: delete the listing, opt out of sale and sharing, say where you got my data.
  - Company: list the third parties you sold or shared my data with, opt me out, delete my data.
  - Name and city only, never more.
- **Re-scan:** re-extract old listing URLs. `removed` means the page loaded and no longer names the user, `still_listed` means it does, and `unconfirmed` means the page was blocked or failed. This is the subscription hook.

**Built** (`s6_resolve.py`). A page under 500 characters counts as blocked (`unconfirmed`), not removed; "still listed" needs both first and last name. Tested live: Ticketmaster's contact search found privacy@ticketmaster.com.

## Stage 7: Aliases (`s7_aliases.py`, Local LLM & ranking)

- Format: `{company-slug}.{6 random hex}@{ALIAS_DOMAIN}`. Save aliases to the `aliases` table in Postgres.
- **Inbox check (local only, no search):** for each message sent to a known alias, if the sender's domain isn't the assigned company's domain or one of its subdomains, it's an `AliasHit` with tier Proven.
- The demo uses `data/mock_inbox.json` and `data/mock_aliases.json`. Use a fictional company and `.example` domains, never a real company accused on fake data. Include one legitimate email from the company itself, to show it isn't flagged.

**Built** (`s7_aliases.py`, plus the `aliases` table in `db.py`). `match_inbox()` is the pure core. Aliases can be made for companies in `companies.json` or the demo companies; anything else is a 404. If Postgres is down, the demo aliases still list and the inbox check still works.

**Identity manager, Phase 1** (one alias per signup):
- `POST /api/aliases {site}` makes an alias for a website. Only the hostname is kept (`models.normalize_site`), never a pasted URL's path or query. The expected senders are the domains of the company in `companies.json` that owns the site, or else the site itself. No lookup is made.
- Aliases belong to the signed-in account (`aliases.user_id`). Aliases from before accounts go to the first admin.
- Status and note live in `alias_states`, per account and per address, so the demo aliases can be disabled too.
- Messages per alias come from the mock inbox (`alias_messages()`, pure). `blocked` means the message arrived on or after the day the alias was disabled. It's a label: nothing receives real mail. Don't word it as if mail was rejected.
- A disabled alias's unexpected mail is still a Proven hit: the evidence doesn't go away.

**Phase 2, investigate:** `investigation_facts()` (pure) writes the facts, each date with its source, names senders found in `brokers.json`/`companies.json`, and sets Proven. The local LLM (`prompts.alias_prompt`) sees the company, the sender domains, the dates and the subjects (truncated). It never sees the alias or a full sender address. It only picks a category and explains. `clean_explanation()` drops sentences with "leaked by", a sale or leak stated without a hedge, or a 2+ digit number missing from the facts. The model can't pick `legit` when the rules found unexpected mail.

**Phase 3–4:** the Aliases tab (`frontend/app/components/AliasPanel.tsx`) and the extension's "private email for this site" (`extension/popup.js`).
