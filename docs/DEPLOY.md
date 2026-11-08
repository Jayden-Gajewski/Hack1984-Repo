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
   `frontend`, and add two environment variables:
   - `BACKEND_URL` = `https://<your-service>.onrender.com`
   - `SITE_URL` = the address from step 1

   Deploy. If you change `BACKEND_URL` later, redeploy: Next.js reads it at build time.
5. **Sign up first.** The first account on a new database becomes the admin (Account page:
   accounts, roles, reset codes). Create yours before you share the link.

## On the public site

- **Per account:** saved scans, the current scan, the outbound log, aliases, footprint records and
  added companies. Nobody sees another account's data.
- **Daily limits:** scans, re-scans, policy checks and company look-ups spend Exa, Tavily and
  Gemini credits. Each account gets `SEARCHES_PER_DAY` (default 20) a day, and everyone together
  `SEARCHES_PER_DAY_TOTAL` (default 500). Set either on Render to change them. Loading a saved scan
  is free.
- **Not there yet:** the Threat Monitor (it still keeps one person's data) and the browser
  extension (it talks to the Dossier app on its user's own computer). Both keep working in the
  local app.
- **Sign-up is open.** Anyone can create an account and scan any name, which is the misuse risk
  people-search sites carry too. The consent checkbox stays, and the limits cap the cost. Keep an
  eye on the admin page's account list.

## Good to know

- Render's free plan sleeps after 15 idle minutes; the first request after that takes up to a
  minute. A paid instance stays awake.
- Run one instance only. Each account's current scan lives in that process's memory (after a
  restart the app loads the saved scan again).
- Logins work on the `SITE_URL` address only. Vercel preview deployments have other addresses, so
  the backend refuses their changes.
- This changes some of the project rules in `CLAUDE.md` (hosted database and accounts, a hosted
  LLM). Update them with your team so everyone's Claude sessions know.
