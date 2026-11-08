# Frontend (UI & demo)

Next.js (App Router) with React and TypeScript, at `http://localhost:3000` on a laptop and on Vercel for the public site (`docs/DEPLOY.md`). Call the backend through the `api` object in `lib/api.ts`, which uses relative `/api/...` URLs; `next.config.ts` proxies them to FastAPI (`BACKEND_URL`: `:8000` locally, the Render backend's https address on Vercel) (routes are listed in `backend/CLAUDE.md`). The types in `lib/api.ts` mirror `backend/app/models.py`, so change them together. No other UI frameworks or component libraries.

## Nothing leaves without a log entry

The outbound log claims to show every request Dossier sent, so it has to be true, on a laptop and on Vercel.

- **No external calls from Next.js.** Route handlers, server components and server actions only call the FastAPI backend. Don't add Next.js API routes that call Exa, Tavily, Gemini or any other service.
- **No web fonts from third parties.** Use a system font stack, or `next/font/local` with files checked into the repo. Never use `next/font/google`, a Google Fonts `<link>` or `@import`, even if a design skill suggests it.
- **No third-party CDNs, analytics or telemetry.** No `@vercel/analytics` or Speed Insights, no tracking scripts. Run `npx next telemetry disable` once per laptop, and set `NEXT_TELEMETRY_DISABLED=1` on Vercel.
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
- **Accounts:** a type-to-search company picker and a "Check breaches & policies" button. It suggests from `/api/companies` and can add any other company through `POST /api/companies`, which matches a name to its website with one logged search, or uses a typed website. Added companies show their website on the tag.
  - Show breach timelines and policy flags.
  - A sell/share flag shows its verbatim quote under the line "This wasn't a hack, they sold it."
- **Draft modal:** where to send it (link or email), the subject, the body, and a copy button.
- **Aliases:** a "new alias for…" button, the alias list, and a "Check inbox (mock)" button. Show hits as Proven.
- **Footprint** (`FootprintPanel.tsx`, styles in `app/footprint.css`): companies the user tracks and their requests for a copy of their data or for deletion.
  - Drafts are local templates with a copy button. Dossier never sends them: "Draft" and "Ready to send" read "Not sent" and wear a dashed outline; sent statuses are solid.
  - The update form only offers the backend's `next_statuses`. Dates the user entered read "(you recorded)", dates Dossier set read "(saved)", and a missing one reads "unknown".
  - A named privacy law is optional and comes with "isn't legal advice". Privacy settings are the user's own record: the app can't see or change them.
  - Name suggestions come from `GET /api/companies` only. Never wire this form to `POST /api/companies`, which searches.
- **Outbound log panel:** always visible as a sidebar, polling `/api/outbound-log` every 1 to 2 seconds.
  - Each row: service, purpose, method + URL, status and time. Expand a row to see the exact body sent (keys are already redacted by the backend).
  - Show counts per service. Gemini calls are outbound like the rest (service `gemini`), with the page text they carried. The "stayed on this machine" toggle only appears if the backend ever logs a `local` call again; nothing does since the switch from Ollama.

- **Threat monitor (`/app/monitor`):** a separate section, linked from the app bar.
  - A monitor panel up top: a radar scope (one dot per open threat, coloured by severity), one plain sentence about what's going on, and a live scan feed while it scans.
  - Tabs: Threats (compact rows that open into boxes), What we watch (companies, emails, setup) and History (schedule, history).
  - Each card shows severity and involvement side by side in one split pill. They're separate answers: a critical breach can be "Not confirmed for you".
  - Steps are checkboxes. Copy never says an account is secure because steps are checked.
  - Missing keys or settings show as "off" in the setup line, never as fake results.
  - Company tiles are local initials, never remote logos.
  - The page includes the outbound-log drawer.

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

The demo is the 3-minute script in the root `CLAUDE.md`. It ends on the outbound log, so that panel should look good full-screen. Make sure each step works without a page reload, and have loading states (a scan searches, then sends each page to Gemini, so it takes a while; on Vercel a request is cut off after 2 minutes, but the scan keeps going and scanning again loads it). Keep a fallback in case the venue Wi-Fi fails: the Scan tab opens on the account's last saved scan from Postgres (`GET /api/scans/latest`), labeled "Nothing was searched", with no click needed. Cards are sorted most urgent first (risk, then evidence tier).
