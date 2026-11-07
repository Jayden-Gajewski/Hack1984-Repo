# Frontend (UI & demo)

Plain HTML/CSS/JS (`index.html`, `app.js`, `styles.css`), served by FastAPI at `http://localhost:8000`. No frameworks, no bundler, no npm. Call the backend with `fetch` on `/api/...` (routes are listed in `backend/CLAUDE.md`). Load nothing from third-party CDNs: no fonts, analytics or scripts. The outbound log claims to show everything that left the laptop, so it has to be true.

## Security

Everything shown on screen (page titles, field quotes, policy quotes, email subjects) comes from scraped web pages. **Always escape it.** Use `textContent`, or a single `escapeHtml()` helper, before any `innerHTML`. A broker page must not be able to inject script into our demo.

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

- Use "Likely source", never "who leaked it".
- Tier badges:
  - **Proven**: an alias match.
  - **Likely**: timing and breach scope line up.
  - **Possible**: the policy allows sharing.
- Explain each tier on hover.
- Every date shows its source. A missing date reads "unknown".

## Demo

The demo is the 3-minute script in the root `CLAUDE.md`. It ends on the outbound log, so that panel should look good full-screen. Make sure each step works without a page reload, and have loading states (scans take a while with a local LLM). Keep a fallback: a "load last scan" option that reads a saved result, in case the venue Wi-Fi fails.
