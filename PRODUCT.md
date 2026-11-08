# Product

<!-- impeccable:product-schema 1 -->

Sources: "confirmed" facts come from the owner's answers on 2026-11-07. The rest is from the root CLAUDE.md and docs/PITCH.md.

## Platform

web

## Users

- **Everyday privacy-conscious people** who want to know where their personal data is exposed, which company is the likely source, and how to get it removed. The website and the extension are written for them first (confirmed).
- **Hackathon judges** watching a 3-minute live demo on a projector (CLAUDE.md, "Demo script").

## Product Purpose

Dossier finds a person on people-search sites, shows what each listing reveals and when it went public, ranks the likely source with an evidence tier (Proven, Likely, Possible), and drafts the opt-out. Its browser extension, Dossier Privacy Check, brings a privacy check to every site the user visits: what the policy says is collected, sold or shared, which trackers load, what forms ask for, and whether the site is a people-search site.

## Positioning

The analysis runs on the user's own computer, and every request that leaves it is logged with its exact contents ("Here's everything that left this laptop"). Paid removal services make you hand your name, address and birthdate to one more company; Dossier doesn't.

## Operating Context

- The web app runs locally: Next.js on localhost:3000, FastAPI on :8000, Ollama for the LLM, and a local Postgres. Accounts are local.
- The extension is a beta: it needs the Dossier backend running on the same computer, isn't in the Chrome Web Store, and installs with "Load unpacked" in Chrome or Edge.
- The extension download is for signed-in users (confirmed).

## Capabilities and Constraints

- The privacy rules in the root CLAUDE.md are non-negotiable: local analysis, one door out (outbound.py), minimal queries, user data stays on the laptop.
- Wording: "likely source", never "who leaked it"; every date shows its source; a missing date is "unknown".
- Frontend: no third-party fonts, CDNs, analytics or remote images; no UI libraries beyond Next.js.
- Pricing: automated removal plans are coming. No prices, tiers or dates are decided; say only that plans are coming (confirmed).

## Brand Commitments

- Name: Dossier (the repository is Hack1984). Mark: a file folder with a keyhole (frontend/app/components/Logo.tsx).
- Voice: plain, factual and evidence-first. It hedges when the evidence is partial and never accuses.

## Evidence on Hand

- Sample data is fictional (Jane Example, .example domains, ShopCo). There are no testimonials, customer counts, metrics or press: don't invent any.
- Screenshots of the extension popup on the fictional ShopCo site exist from automated browser tests.

## Product Principles

1. Evidence over claims: every statement links to where it came from.
2. Nothing leaves without a receipt.
3. Say less than the evidence could support, never more.
4. The user's data stays the user's.
