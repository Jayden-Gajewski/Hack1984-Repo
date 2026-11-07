---
name: add-stage-endpoint
description: The pattern for implementing a pipeline stage (backend/app/stages/sN_*.py), exposing it through a FastAPI route in backend/app/main.py, and calling it from the Next.js UI through frontend/lib/api.ts. Use when implementing or exposing a stage (exposures, dates, breaches, policy, rank, resolve, alias), adding a new API endpoint, or hooking a UI button or card up to backend data.
---

# add-stage-endpoint

Stages live in `backend/app/stages/`: `s1_exposures.py`, `s2_dating.py`, `s3_breaches.py`, `s4_policy.py`, `s5_ranking.py`, `s6_resolve.py` and `s7_aliases.py`. Each one starts as a stub that raises `NotImplementedError`, and the routes for all of them already exist in `main.py` (table in `backend/CLAUDE.md`). Usually you only fill in the stage.
MVP order: Stages 1, 4, 6 + the outbound log. Then 2, 3, 5. Stage 7 last.

## 1. Stage module: keep the signature, fill in the body

```python
# backend/app/stages/s4_policy.py
import asyncio

from app.clients import ollama, tavily          # clients wrap outbound.request
from app.data import load_json
from app.models import PolicyResult


async def check_policies(company_ids: list[str]) -> tuple[list[PolicyResult], list[str]]:
    companies = [c for c in load_json("companies.json") if c["id"] in company_ids]
    results = await asyncio.gather(*(_check_one(c) for c in companies), return_exceptions=True)
    policies, errors = [], []
    for company, result in zip(companies, results):
        if isinstance(result, Exception):
            errors.append(f"{company['name']}: policy check failed ({result})")
        else:
            policies.append(result)
    return policies, errors
```
Rules:
- Keep the function name and signature: `main.py`, the tests and the frontend depend on them. Return `models.py` types plus a list of error strings.
- External calls only through `backend/app/clients/*` (which use `outbound.request`). Never import `httpx` in a stage.
- Search queries use name + city only, or a company name. The clients pass them as `guard=[query]`. If the guard raises, report it as an error string; don't strip the data silently.
- Per-item failures go in the errors list: one blocked broker or company must not fail the whole stage. (`main.py` also turns an uncaught exception into an error string, but don't rely on that.)
- Every date or claim carries its source label (`public_by_source`, `date_kind`, `source_kind`).
- Read the client files for the real function names and parameters before calling them.

## 2. FastAPI route (only if you need a new one)

Check the route table in `backend/CLAUDE.md` first; most routes already exist. If you do add one to `backend/app/main.py`, follow the existing style:

```python
@app.post("/api/policy-only", response_model=AccountsResponse)
async def policy_only(req: AccountsRequest):
    policies, errors = await _stage("Stage 4 (policy check)", [], s4_policy.check_policies, req.companies)
    return AccountsResponse(breaches=[], policies=policies, errors=errors)
```
- Use `POST` with a JSON body for anything carrying personal data (name, city). Keep it out of URLs and query strings.
- Request and response bodies are pydantic models in `models.py`. Add fields, don't rename them, and mirror every change in `frontend/lib/api.ts`.
- `main.py`, `models.py` and `frontend/lib/api.ts` are shared files: keep changes additive and call them out in the commit message.
- Don't touch `GET /api/outbound-log`. It's the log.

## 3. UI call (frontend/)

Add the call to the `api` object in `frontend/lib/api.ts` (relative URL; `next.config.ts` proxies `/api` to `:8000`), then use it from a client component:

```tsx
"use client";
const [data, setData] = useState<AccountsResponse | null>(null);
const [error, setError] = useState<string | null>(null);

async function run() {
  try {
    setData(await api.accounts(selected));
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
  }
}
```
- Put loading and error states on the card. Show "unknown" or "unavailable" rather than blank, and show the response's `errors` too.
- The outbound log panel polls `/api/outbound-log`, so new requests appear on their own.
- Render evidence tiers with `TIER_LABEL` and `TIER_HELP` from `lib/display.ts`, with the text "likely source". Links from scraped data go through `safeHref()`.

## 4. Verify

1. `cd backend && pytest` (offline). Add a fixture-based test for pure logic (Stage 5 ranking, Stage 7 inbox matching).
2. `uvicorn app.main:app --reload`, then `curl -X POST localhost:8000/api/<route> -H "Content-Type: application/json" -d '{...}'`.
3. Check that `GET localhost:8000/api/outbound-log` shows the new calls with the right `service` names and a readable `purpose`.
4. `cd frontend && npm run dev`, then click through at http://localhost:3000.
5. Run the `privacy-audit` skill if the stage adds a new client call.
