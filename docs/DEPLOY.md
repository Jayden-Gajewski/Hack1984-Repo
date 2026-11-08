# Deploying Dossier as a public site

The frontend runs on Vercel. The backend runs on Render as one always-on process, with a hosted
Postgres (Neon). Vercel forwards `/api/*` to the backend, so browsers only ever talk to your site.

Setting `SITE_URL` on the backend is what makes it a public server: each account's data is its
own, a hosted Postgres is allowed (TLS only), daily search limits apply, and the session cookie is
https-only. Without `SITE_URL` the backend behaves exactly like the local app.

## You need

- This repo on GitHub, and accounts on Vercel, Render and Neon (all have free plans).
- API keys: Gemini, Exa, Tavily. Use a paid Gemini key once real people's data goes through it:
  on the free tier Google may use what it's sent to improve its products.

## Steps

1. **Pick the site's address.** Choose the Vercel project name now, for example `dossier-yourname`.
   The site will be `https://dossier-yourname.vercel.app`. That is your `SITE_URL`.
2. **Database.** In Neon, create a project and copy its connection string. It looks like
   `postgresql://user:password@...neon.tech/neondb?sslmode=require`. The backend creates its
   tables on first start.
3. **Backend.** In Render, choose New > Blueprint and pick this repo. It reads `render.yaml`. Fill
   in `SITE_URL`, `DATABASE_URL`, `GEMINI_API_KEY`, `EXA_API_KEY` and `TAVILY_API_KEY`, then
   deploy. Check `https://<your-service>.onrender.com/api/status`: it should show
   `"database": true` and `"public": true`.
4. **Frontend.** In Vercel, choose Add New > Project and import this repo. Set Root Directory to
   `frontend` (Vercel then finds Next.js and its build settings on its own), and add three
   environment variables:
   - `BACKEND_URL` = `https://<your-service>.onrender.com`. The build stops if it's missing.
   - `SITE_URL` = the address from step 1
   - `NEXT_TELEMETRY_DISABLED` = `1`, so Next.js doesn't report the build to Vercel's telemetry.

   Deploy. If you change `BACKEND_URL` later, redeploy: Next.js reads it at build time. Leave
   Vercel's Web Analytics and Speed Insights off: Dossier has no analytics, and the outbound log
   can't show what they send.
5. **Sign up first.** The first account on a new database becomes the admin (Account page:
   accounts, roles, reset codes). Create yours before you share the link.

## On the public site

- **Per account:** saved scans, the current scan, the outbound log, aliases, footprint records and
  added companies. Nobody sees another account's data.
- **Daily limits:** scans, re-scans, policy checks and company look-ups spend Exa, Tavily and
  Gemini credits. Each account gets `SEARCHES_PER_DAY` (default 20) a day, and everyone together
  `SEARCHES_PER_DAY_TOTAL` (default 500). Set either on Render to change them. Loading a saved scan
  is free.
- **Browser extension:** the zip on `/extension` (signed in) is set up for the public site: it
  calls `SITE_URL` with the user's session, so people need no repo or backend of their own. Each
  account has its own results (in memory) and log entries, and the AI pass is capped at 100 a day
  per account and 2,000 for everyone. Its "check every site I visit" starts off, because it would
  send every site the user visits to the server. The zip is built from the repo's `extension/`
  folder on each download, so `render.yaml` deploys from the repo root (Render hides files outside
  a service's root directory). A service set up before this change: in Render, clear the
  service's Root Directory (Settings > Build & Deploy) or sync the Blueprint, then redeploy.
- **Not there yet:** the Threat Monitor (it still keeps one person's data). It keeps working in the
  local app.
- **Sign-up is open.** Anyone can create an account and scan any name, which is the misuse risk
  people-search sites carry too. There's no consent checkbox; the daily limits cap the cost. Keep an
  eye on the admin page's account list.

## Good to know

- Render's free plan sleeps after 15 idle minutes; the first request after that takes up to a
  minute. A paid instance stays awake.
- Run one instance only. Each account's current scan lives in that process's memory (after a
  restart the app loads the saved scan again).
- **Vercel waits 2 minutes for the backend**, for any request, and that can't be raised. A scan
  that takes longer shows "The server didn't answer in time", but it keeps running on the backend
  and is saved: scanning the same person again joins it, or loads it once it's done, without
  spending another search. A sleeping free Render instance can use up most of those 2 minutes
  waking, so open the site (or `/api/status`) a minute before a demo.
- Logins work on the `SITE_URL` address only. Vercel preview deployments have other addresses, so
  the backend refuses their changes.
- This changes some of the project rules in `CLAUDE.md` (hosted database and accounts, a hosted
  LLM). Update them with your team so everyone's Claude sessions know.
