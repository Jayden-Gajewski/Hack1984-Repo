---
name: ui-design-pipeline
description: Runs any UI request for the Next.js frontend through three design skills in a fixed order before code is written - impeccable (UX, structure, critique), then frontend-design (visual direction and tokens), then emil-design-eng (motion, interaction feel, polish) - and only then builds. Use when someone asks to make, build, redesign or restyle UI in frontend/ (scan form, exposure cards, card detail, accounts, draft modal, aliases, outbound log), or types /ui-design-pipeline before a UI prompt.
argument-hint: "[what UI to build or change, e.g. 'redesign the exposure cards']"
---

# ui-design-pipeline

The request in `$ARGUMENTS` (or the user's next message, if that's empty) is a UI task for `frontend/`. Don't write UI code until all three design stages below have run **in order**. Each stage builds on the previous one's output and doesn't start over.

```
request ─▶ 0. Ground ─▶ 1. impeccable ─▶ 2. frontend-design ─▶ 3. emil-design-eng ─▶ checkpoint ─▶ build ─▶ Emil review
```

## Repo rules beat skill advice

The three skills are general-purpose. This repo has hard constraints, and if a skill suggests something below, **the repo rule wins**. Say so in one line when it happens, e.g. "impeccable suggested Inter from Google Fonts; using the system stack instead per frontend/CLAUDE.md."

- **No third-party fonts.** Use a system font stack, or `next/font/local` with font files committed to the repo. Never `next/font/google`, a Google Fonts `<link>`, or an `@import`.
- **No remote images, CDNs, analytics or telemetry.** No external logos or favicons. Use text or local assets.
- **No new UI or animation libraries.** That rules out Framer Motion, Radix, shadcn, Tailwind plugins and similar. Emil's spring and Framer examples get translated to CSS transitions, `@starting-style`, `linear()` easing, or WAAPI. If something truly needs a library, stop and ask (root CLAUDE.md "Don't build").
- **Scraped data is untrusted.** Never use `dangerouslySetInnerHTML`. Links go through `safeHref()` in `frontend/lib/display.ts`.
- **Wording.** Tier labels, tier hover text and date-source labels come from `frontend/lib/display.ts`. Write "Likely source", never "who leaked it". Every date shows its source, and a missing date reads "unknown". Copy rewrites from impeccable `clarify` must follow these rules.
- **Tokens live in `frontend/app/globals.css`.** Colors are `:root` variables with light/dark variants (`--proven`, `--likely`, `--possible`, `--danger`, …). Extend or retune them; don't scatter raw hex values.
- **Required screens and copy** are listed in `frontend/CLAUDE.md` (for example the scan-form privacy line, the snippet note, and "This wasn't a hack, they sold it."). Keep them.
- **Shared files.** Changing `frontend/lib/api.ts` means changing `backend/app/models.py` too. Avoid it in a design task. Don't reformat files outside the task's scope.

## 0. Ground (read before any design stage)

Read these, then write a 4–6 line **brief**: which surface, who is looking at it (a hackathon judge watching a 3-minute live demo on a projector, and a privacy-conscious user scanning themselves), its job, and which demo-script step it serves.

- `frontend/CLAUDE.md` for screens, privacy and security rules
- the "Demo script" section of the root `CLAUDE.md`, plus `docs/PITCH.md` if the surface is in the pitch
- `frontend/app/globals.css`, `frontend/lib/display.ts`, and the components the task touches in `frontend/app/components/`
- the matching types in `frontend/lib/api.ts`, so designs use real field names and real data shapes

## 1. impeccable: structure and UX

Invoke the `impeccable` skill with the brief. Follow its Setup:

- On Windows, run `.claude/skills/impeccable/scripts/impeccable.cmd context --target <file>` (or `scripts/impeccable` where `sh` is available).
- No `PRODUCT.md` exists yet. For a new surface, let impeccable run `init`. For a narrow refinement, go ahead and offer `init` afterward, as impeccable itself says to.
- **Mode is Operate** for every screen in this app, including the outbound log. Judges watch it, but it's still a tool.
- Pick the command that fits: `shape` for new UI, `critique`/`audit` for existing UI, or `distill`/`clarify`/`layout` for targeted fixes.

**Hand off:** information hierarchy, layout and states (empty, loading, slow local LLM, error, snippet-only, no date), accessibility needs, and copy changes. Write no code yet, except PRODUCT.md or DESIGN.md if impeccable's `init`/`document` produced them.

## 2. frontend-design: visual direction

Invoke the `frontend-design` skill and give it stage 1's handoff as the brief. Keep impeccable's structure and add the look on top:

- A token plan of 4–6 named hex colors (mapped onto the existing `globals.css` variables, light and dark), typefaces and their roles (system or local only), a layout sketch in ASCII, and 2–3 principles.
- Run its "review the plan against generic defaults" pass and name what changed. Check especially against the SaaS-card kit and all-caps eyebrow labels, since exposure cards are prone to both.
- Pick the **one memorable thing**. For this product it's usually the outbound log ("here's everything that left this laptop") or the tier badge. Keep the rest quiet.

**Hand off:** the token plan and wireframe. Still no component code.

## 3. emil-design-eng: motion and feel

Invoke the `emil-design-eng` skill, but skip its "Initial Response" greeting because this is a handoff, not a cold start. Give it stages 1–2. Ask it for:

- Which interactions animate and which don't (its "Should this animate at all?" framework). New outbound-log rows, card expand/collapse, the draft modal, the button press state and the copy-button confirmation are the likely candidates. Things that happen hundreds of times should not animate.
- For each interaction: properties (transform/opacity only), duration, easing curve, enter/exit asymmetry, and the `prefers-reduced-motion` fallback.
- Loading feel for the slow parts (scan, Ollama ranking): perceived-performance tactics, without fake progress.

**Hand off:** a short motion spec table (`Element | Trigger | Animate? | Properties | Duration | Easing | Reduced motion`).

## Checkpoint

Show the user a compact combined spec: the brief, impeccable's structure, frontend-design's tokens and wireframe, Emil's motion table, and any repo-rule overrides. **Wait for a go-ahead** before writing code, unless the user said to run straight through.

## Build

- Implement in `frontend/app/` against the combined spec. Token changes go in `globals.css` first, then components.
- Read impeccable's `reference/craft-floor.md` right before editing, as impeccable requires.
- Verify once: `cd frontend && npm run build`. If the app runs, check the page at desktop and mobile widths, and in light and dark mode, in one batch. Fix everything that pass finds, then stop. Don't polish in a loop.

## Emil review (last)

Review the diff in Emil's required **Before | After | Why** table format, apply the fixes, and rebuild once.

## Finish

Report what changed in each file, which repo rules overrode skill advice, and whether the build passed (quote the error if it didn't). Suggest running the `privacy-reviewer` agent if anything touched network calls, links or rendered scraped data. Commits stay small and on a short-lived branch.
