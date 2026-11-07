# The pitch

One line: "Find out where your personal data is exposed, which company most likely leaked it, and get it taken down, without handing your data to yet another company."

Tracks: Surge (Exa and Tavily run the core), Most Startup-able (people already pay for data removal), and the main Privacy-First track (analysis runs locally and every outbound request is logged).

## How it works

1. **Find exposures.** The user scans themselves only. Exa runs semantic searches and find-similar to discover broker listings, and Tavily runs domain-restricted searches on known brokers. Tavily Extract pulls each page's text, and a local LLM lists which fields are exposed (address, phone, relatives, email). If a broker blocks extraction, fall back to search snippets.
2. **Date them.** Use the Wayback Machine's earliest snapshot as the "public by" date. If you have time, check a few snapshots to see when each field first appears. Fall back to the API's published date, and label every date with its source. If there's no data, show "unknown."
3. **Breach timelines.** The user picks their accounts from a list. Tavily news search and date-filtered Exa searches find breaches for each company, including state attorney general notification pages, which list the date and data types.
4. **Policy check.** Tavily Extract pulls each company's privacy policy, and the local LLM flags clauses about selling or sharing data. This is the source of "this wasn't a hack, they sold it."
5. **Rank likely sources.** Every lead gets an evidence tier:
   - **Proven:** an alias match.
   - **Likely:** timing and breach scope both line up.
   - **Possible:** the policy allows sharing.

   Always say "likely source," never "who leaked it."
6. **Resolve.** Search for each broker's opt-out page and each company's privacy contact, then draft the requests. Re-scanning later confirms what came down, which is the subscription hook.
7. **Prove it going forward.** Generate a unique alias for each new signup. When mail arrives at an alias from someone other than that company, flag it as Proven. This check runs locally on the inbox, not through search.

## Privacy features (main track)

- Local LLM through Ollama: page text and analysis never leave the machine.
- Outbound log panel: shows every request to Exa, Tavily and the Wayback Machine, with exactly what was sent.
- Minimal queries: search with name and city only, never with phone numbers or email addresses, and say so in the pitch.

## Build order

- **First hour:** test Tavily Extract on Spokeo, Whitepages and similar sites using a teammate's name. This decides how Stage 1 works.
- **MVP:** Stages 1, 4 and 6 plus the outbound log. That's a complete demo on its own.
- **Then add:** Wayback dates, breach timelines and evidence-tier ranking.
- **Last:** a mocked inbox showing one alias match.

**Skip:** user accounts, a real Gmail integration, vector databases, agent frameworks, and multiple agents.

## Team split (4 people)

- **Search and extract:** Stages 1 and 6.
- **Evidence:** Wayback, breaches and policies (Stages 2 to 4).
- **Local LLM and ranking:** the prompts, Stage 5 and the alias logic.
- **UI and demo:** the cards, outbound log and pitch.

## Demo (about 3 minutes)

1. Scan a consenting teammate live and show the exposure cards with sources.
2. Open one card to show its fields, the Wayback date, and the likely source with its evidence tier.
3. Show a policy flag: "this wasn't a hack, they sold it."
4. Click to draft an opt-out request.
5. Show the mocked alias match as Proven.
6. Finish on the outbound log: "Here's everything that left this laptop."
