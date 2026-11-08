# The pitch

**One line:** "Dossier checks every site you visit before you hand it your data and gives each one its own email address. When your data turns up somewhere it shouldn't, Dossier shows which company is the likely source and gets it taken down. Every request Dossier makes for you is shown in full."

**On a slide:** "A privacy check on every site you visit, with the evidence when one of them passes your data on."

Tracks: Privacy-First (the main one), Most Startup-able, and Surge.

## Extension first, website second

The browser extension is the part people live with. It runs on every page, and it acts before you type your email into a form, which is when it matters most. The website is where you go next: scan yourself across people-search sites, see the likely source of each listing, and send the opt-outs.

The two hand off to each other:

- **Extension to website:** on a people-search site, the extension shows a banner with "Scan yourself with Dossier". The private email it gives each site is what later lets the website rank a source as **Proven**.
- **Website to extension:** the extension is downloaded from the website by signed-in users.

## The extension: Dossier Privacy Check

**On every site, without contacting it** (it reads only what your browser already loaded):

- **Badge:** `!!` for high risk, `!` for some risk, `?` when the policy couldn't be read. There's no green "OK", because finding nothing isn't proof a site is safe.
- **Who's watching:** the known trackers the page loaded (session recorders, data brokers, ad and social trackers), and the other sites you opened where each one showed up too. "Loading this page told 5 companies you were here."
- **What a form asks for:** the kinds of personal data it asks for (card number, SSN, password) and whether they'd be sent without https. It goes by each field's label and never reads what you type.
- **People-search sites:** a banner with the site's opt-out page and "Scan yourself with Dossier".

**When you open the popup:**

- **What the policy allows:** what the site says it collects, and whether it sells or shares it, each shown with the exact sentence. Fixed rules read the policy. Google's Gemini also reads its selling and sharing sentences and the site's name, and can only pick sentences. The popup shows fixed wording, never the model's own words.
- **Promises that don't add up:** when the policy says it doesn't sell your data but the page loads ad trackers or data brokers, the extension shows both side by side. This doesn't claim the policy lies. California law calls passing data on for targeted ads "sharing", which a promise not to sell doesn't cover.
- **Opt out:** a button to the site's own "Do Not Sell or Share" page, when it has one.
- **Private email for this site:** when the page asks for an email address, the extension offers an alias just for that site (`shop.1a2b3c@…`). It fills the field in only when you click. If mail to that address ever comes from a different company, that's Proven evidence of the likely source.
- **Who sells its ads:** how many ad companies the site's `ads.txt` lists, and the bid request an ad auction can send them. The bid request is built from your own browser and sent nowhere.

## The website: scan yourself

Sign in and search with your name and city or state only:

1. **Find exposures.** Exa and Tavily find people-search listings, and Gemini lists what each one exposes (address, phone, relatives, email). When a site blocks extraction, the scan falls back to search snippets.
2. **Date them.** The Wayback Machine's earliest snapshot is the "public by" date. Every date shows its source, and a missing date is "unknown".
3. **Breach timelines.** For the companies you pick, news, date-filtered Exa searches and state attorney general notices.
4. **Policy check.** The same selling and sharing check the extension runs, applied to the companies you use.
5. **Rank likely sources.** Each lead gets an evidence tier:
   - **Proven:** mail to a per-site alias came from someone else.
   - **Likely:** the timing and the breach's scope both line up.
   - **Possible:** the policy allows selling or sharing.
6. **Resolve.** It finds each site's opt-out page and each company's privacy contact, drafts the requests, and re-scans later to confirm what came down.
7. **Aliases and inbox check.** These are the private emails the extension hands out. The demo's inbox is mocked.

On a laptop there's also the threat monitor, which tracks breaches at the companies you use and at email addresses you've proven you own. HIBP gets only the first 6 characters of the address's SHA-1 hash.

## Where each part runs (say this plainly)

- **The extension** works while Dossier runs on your own computer. It talks only to the backend there, and to the app there for private emails. It's a free beta, installed with "Load unpacked" in Chrome or Edge.
- **The public site** runs the scan, with accounts and daily search limits. Its extension route is switched off: the sites you visit are your browsing history, and Dossier's servers shouldn't hold it.
- On a laptop, the app's outbound log lists the extension's requests next to the scan's.

## Tracks

**Privacy-First (main track)**

- The check on each visit contacts no site and calls no LLM, so browsing doesn't tell anyone where you've been.
- It never reads what you type. It keeps only tracker hostnames, and it records form fields only as fixed words (`email`, `card`).
- Opening the popup sends one GET to the site's own policy and one to its `ads.txt`. Gemini gets the site's name and the policy's selling and sharing sentences. Every request is logged with its exact contents.
- Results stay in memory. "Forget the sites I've visited" clears them and says what can't be recalled.
- The scan searches with name and city or state only. `outbound.py` refuses queries with phone numbers, emails, SSNs or birthdates. Every request goes out through that one module and is logged, including exactly what Gemini read.

**Most Startup-able**

People already pay for data removal, and those services start by asking for your name, address and birthdate. Dossier's extension is free and on screen every day. Its people-search banner leads into the scan, which is the step people pay for. Automated removal plans are coming. No prices or dates are set, so don't name any.

**Surge**

Exa and Tavily run the website's scan: finding listings, breach news and opt-out pages. The extension uses no search API on purpose.

## Demo (about 3 minutes)

**Before you present:**

- Pick a real shopping site with a signup form and a real people-search site from `backend/app/data/brokers.json`, and rehearse on both.
- Make sure the backend and the app are running on the demo laptop (the extension needs them) and `GEMINI_API_KEY` is set.
- Start the consenting teammate's scan just before you begin, so it finishes while you show the extension.
- Clear the outbound log, or press "Forget the sites I've visited", so only the demo's requests show.

**The script:**

1. **Browse (0:00–0:30).** Open the shopping site. The badge appears, and no site was contacted for it. Open the popup to show the verdict and the policy sentence behind it: "This might not have been a hack. Their own policy says they can sell your data."
2. **Who's watching (0:30–0:50).** Open the trackers tile: "Loading this page told N companies you were here," and where else you've seen them. If the site promises not to sell, show "Promises that don't add up".
3. **Sign up (0:50–1:15).** Go to the signup form. Under "Private email for this site", click "Fill in": "If this address ever gets mail from anyone else, we'll know where it came from."
4. **People-search site (1:15–1:35).** Open the people-search site and show the banner. Click "Scan yourself with Dossier". Say that the teammate's scan was started a minute ago.
5. **The scan (1:35–2:20).** Show the exposure cards and their sources. Open one card: its fields, the Wayback date and its source, and the likely source with its evidence tier. Show the alias match as Proven: the alias for ShopCo got mail from a lead-generation company. Say that the inbox is mocked and that ShopCo is fictional. Then draft an opt-out.
6. **The log (2:20–3:00).** "Here's every request Dossier sent, including exactly what Gemini read." Point out the extension's two GETs to the site and its one Gemini call, then the scan's searches, which contain only a name and a city.

## Wording

- Say "likely source", never "who leaked it" or "leaked by".
- Never call a site "safe". The badge has no green light.
- The analysis is done by Google's Gemini. Never say it runs on this laptop.
- Every date shows its source. A missing date is "unknown".
- ShopCo, Jane Example and every `.example` domain are fictional. We have no customer counts, testimonials or prices, so don't make any up.

## Likely judge questions

- **"Why doesn't the extension use your public site?"** The sites you visit are your browsing history. Keeping the extension on your own computer means Dossier's servers never see that history, so the public site switches the extension's route off.
- **"Does Google see where I browse?"** Only for the popups you open. Google gets the site's name and the policy's selling and sharing sentences, and the log shows it. The check on each visit never calls Gemini. On Gemini's free tier, Google may use what it's sent, which is why the public site needs a paid key.
- **"Can a privacy policy trick the LLM?"** The model only picks sentence numbers. Its picks must pass the same checks as the fixed rules, and the popup shows fixed wording, never the model's text.
- **"How is this different from a tracker blocker?"** A blocker hides trackers. Dossier doesn't block anything. It tells you what the policy allows, what the form asks for and which companies the page told, then gives you a private email and the opt-out.
- **"Why a new email address for every site?"** It's the only evidence that reaches Proven. If mail to the address you gave one company comes from another, the first company is the likely source.
- **"What does it cost?"** The extension is a free beta. Automated removal plans are coming.
