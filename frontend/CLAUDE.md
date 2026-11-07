# Frontend (UI & demo)

Next.js (App Router) with React and TypeScript, at `http://localhost:3000`. Call the backend through the `api` object in `lib/api.ts`, which uses relative `/api/...` URLs; `next.config.ts` proxies them to FastAPI on `:8000` (routes are listed in `backend/CLAUDE.md`). The types in `lib/api.ts` mirror `backend/app/models.py`, so change them together. No other UI frameworks or component libraries.

## Nothing leaves the laptop

The outbound log claims to show everything that left the laptop, so it has to be true.

- **No external calls from Next.js.** Route handlers, server components and server actions only call the FastAPI backend. Don't add Next.js API routes that call Exa, Tavily or any other service.
- **No web fonts from third parties.** Use a system font stack, or `next/font/local` with files checked into the repo. Never use `next/font/google`, a Google Fonts `<link>` or `@import`, even if a design skill suggests it.
- **No third-party CDNs, analytics or telemetry.** No `@vercel/analytics`, no tracking scripts, and run `npx next telemetry disable` once per laptop.
- **No remote images.** Don't render broker logos or favicons from external URLs; that leaks the scan to those sites. Use text or local assets.
- **Demo from `npm run demo`.** It's a production build, so it skips the dev server's version check against npm.
- Most interactive UI is client-side. Mark components that poll or hold state with `"use client"`.

## Security

Everything shown on screen (page titles, field quotes, policy quotes, email subjects) comes from scraped web pages. React escapes text you render with `{...}`, so **never use `dangerouslySetInnerHTML`** with this data. Links from scraped data go through `safeHref()` in `lib/display.ts`, which only allows http(s) URLs (a `javascript:` link would run). A broker page must not be able to inject script into our demo.

## Screens and components

- **Scan form:** name, city, state, and a required "I'm scanning myself" consent checkbox. Under the button, show this line: "We search with your name and city only. Never your phone number or email."
- **Exposure cards:** broker name, the fields as chips (address, phone, relatives, email, …), the "public by" date with its source, and the strongest lead tier as a badge. If `text_source` is `snippet`, add a small note: "from search snippet; page blocked extraction".
- **Card detail:**
  - Each field with its quote.
  - The date with its source label ("Wayback Machine, earliest snapshot", "published date", or "unknown"), linked to the snapshot when there is one.
  - The likely sources, each with its tier and reasons.
  - A "Draft opt-out" button.
- **Accounts:** a checkbox list from `/api/companies` and a "Check breaches & policies" button.
  - Show breach timelines and policy flags.
  - A sell/share flag shows its verbatim quote under the line "This wasn't a hack, they sold it."
- **Draft modal:** where to send it (link or email), the subject, the body, and a copy button.
- **Aliases:** a "new alias for…" button, the alias list, and a "Check inbox (mock)" button. Show hits as Proven.
- **Outbound log panel:** always visible as a sidebar, polling `/api/outbound-log` every 1 to 2 seconds.
  - Each row: service, purpose, method + URL, status and time. Expand a row to see the exact body sent (keys are already redacted by the backend).
  - Show counts per service, and include a toggle for local Ollama calls. They're hidden by default and labeled "stayed on this machine".

## Wording

`lib/display.ts` holds the tier labels, the tier hover text and the date-source labels below. Use them rather than writing new strings.

- Use "Likely source", never "who leaked it".
- Tier badges:
  - **Proven**: an alias match.
  - **Likely**: timing and breach scope line up.
  - **Possible**: the policy allows sharing.
- Explain each tier on hover.
- Every date shows its source. A missing date reads "unknown".

## Demo

The demo is the 3-minute script in the root `CLAUDE.md`. It ends on the outbound log, so that panel should look good full-screen. Make sure each step works without a page reload, and have loading states (scans take a while with a local LLM). Keep a fallback: the "Load last scan" button reads the last saved scan from local Postgres (`GET /api/scans/latest`), in case the venue Wi-Fi fails.
