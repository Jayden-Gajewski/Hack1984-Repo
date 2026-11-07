"""FastAPI routes: each one calls one or two pipeline stages (table in backend/CLAUDE.md).

Shared file: keep changes additive and call them out in the commit message.

The browser reaches these through the Next.js proxy (http://localhost:3000/api/*).
Personal data (name, city) goes in POST bodies, never in URLs or query strings.
Run from backend/:  uvicorn app.main:app --reload
"""

import asyncio
import inspect
import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app import db, outbound
from app.clients import ollama
from app.config import get_settings
from app.data import load_json
from app.models import (
    AccountsRequest,
    AccountsResponse,
    Alias,
    AliasHit,
    AliasRequest,
    BreachEvent,
    Draft,
    Exposure,
    LeadsResponse,
    OptOutRequest,
    PolicyResult,
    RescanResponse,
    ScanRequest,
    ScanResponse,
    StatusResponse,
)
from app.outbound import OutboundEntry
from app.stages import (
    s1_exposures,
    s2_dating,
    s3_breaches,
    s4_policy,
    s5_ranking,
    s6_resolve,
    s7_aliases,
)

log = logging.getLogger("hack1984")
DB_DOWN = "Postgres isn't reachable. Start it with `docker compose up -d`."


@dataclass
class Session:
    """The current scan, in memory. Single user on one laptop."""

    person: ScanRequest | None = None
    exposures: list[Exposure] = field(default_factory=list)
    breaches: list[BreachEvent] = field(default_factory=list)
    policies: list[PolicyResult] = field(default_factory=list)
    alias_hits: list[AliasHit] = field(default_factory=list)


session = Session()


async def _stage(
    label: str, fallback: Any, fn: Callable[..., Any], *args: Any
) -> tuple[Any, list[str]]:
    """Run a stage that returns (result, errors). If it isn't built yet or it crashes, return
    `fallback` plus an error string instead: one stage must never fail the whole request."""
    try:
        result = fn(*args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except NotImplementedError:
        return fallback, [f"{label} is not implemented yet."]
    except Exception as exc:
        log.exception("%s failed", label)
        return fallback, [f"{label} failed: {exc}"]


async def _call(label: str, fn: Callable[..., Any], *args: Any) -> Any:
    """Run a stage for a route that has no errors list. Not built yet: HTTP 501.
    A stage raises LookupError for something unknown (404) and RuntimeError when a service
    it needs, like Postgres or a missing API key, isn't available (503)."""
    try:
        result = fn(*args)
        return await result if inspect.isawaitable(result) else result
    except NotImplementedError:
        raise HTTPException(501, f"{label} is not implemented yet.") from None
    except LookupError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from None
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None


def _rank(exposures: list[Exposure]) -> tuple[list[Exposure], list[str]]:
    ranked = s5_ranking.rank_sources(
        exposures, session.breaches, session.policies, session.alias_hits
    )
    return ranked, []


def _company_ids() -> set[str]:
    return {c["id"] for c in load_json("companies.json")}


def _require_scan() -> ScanRequest:
    if session.person is None:
        raise HTTPException(409, "Run a scan (or load the last one) first.")
    return session.person


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()  # refuses to start if OLLAMA_URL isn't localhost
    try:
        await asyncio.to_thread(db.init_schema)
    except Exception as exc:  # the app still runs without Postgres; scans just aren't saved
        log.warning("%s Scans won't be saved until it is. (%s)", DB_DOWN, exc)
    yield
    await outbound.close()


app = FastAPI(title="Hack1984 API", lifespan=lifespan)
# Only answer requests addressed to this machine, which blocks DNS-rebinding pages from
# reading saved scans or the outbound log through the browser.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


@app.get("/api/status", response_model=StatusResponse)
async def status():
    settings = get_settings()
    (running, pulled), database = await asyncio.gather(
        ollama.status(), asyncio.to_thread(db.ping)
    )
    return StatusResponse(
        keys={"exa": bool(settings.exa_api_key), "tavily": bool(settings.tavily_api_key)},
        ollama_running=running,
        ollama_model=settings.ollama_model,
        model_pulled=pulled,
        database=database,
    )


@app.get("/api/brokers")
async def brokers():
    return load_json("brokers.json")


@app.get("/api/companies")
async def companies():
    return load_json("companies.json")


@app.post("/api/scan", response_model=ScanResponse)
async def scan(req: ScanRequest):
    """Stages 1 and 2. A person scanned before gets their newest saved scan back instead,
    unless req.refresh is set."""
    if not req.consent:
        raise HTTPException(400, "A scan needs consent: you can only scan yourself.")

    if not req.refresh:
        saved = await _saved_scan(req)
        if saved is not None:
            session.person, session.exposures = req, saved.exposures
            return saved

    exposures, errors = await _stage(
        "Stage 1 (find exposures)", [], s1_exposures.find_exposures, req
    )
    if exposures:
        exposures, more = await _stage(
            "Stage 2 (public-by dates)", exposures, s2_dating.date_exposures, exposures
        )
        errors += more
    session.person, session.exposures = req, exposures

    response = ScanResponse(scan_id=str(uuid.uuid4()), exposures=exposures, errors=errors)
    try:
        await asyncio.to_thread(
            db.save_scan,
            response.scan_id,
            req.model_dump(exclude={"consent", "refresh"}),
            response.model_dump(),
        )
    except Exception as exc:
        log.warning("Scan not saved: %s", exc)
        response.errors.append(f"Scan not saved. {DB_DOWN}")
    return response


async def _saved_scan(req: ScanRequest) -> ScanResponse | None:
    """The newest saved scan of this person from local Postgres, or None. If Postgres is down
    or the saved row doesn't fit the current models, the caller just runs a fresh scan."""
    try:
        row = await asyncio.to_thread(db.find_scan, req.name, req.city, req.state)
        if row is None:
            return None
        saved_at, saved_response = row
        response = ScanResponse.model_validate(saved_response)
    except Exception as exc:
        log.warning("Couldn't check for a saved scan, so running a fresh one: %s", exc)
        return None
    response.saved_at = saved_at
    return response


@app.get("/api/scans/latest", response_model=ScanResponse)
async def latest_scan():
    """The "load last scan" fallback, for when the venue Wi-Fi fails. Reads local Postgres."""
    try:
        row = await asyncio.to_thread(db.latest_scan)
    except Exception as exc:
        log.warning("Couldn't load the last scan: %s", exc)
        raise HTTPException(503, DB_DOWN) from None
    if row is None:
        raise HTTPException(404, "No saved scans yet.")
    saved_request, saved_response = row
    response = ScanResponse.model_validate(saved_response)
    session.person = ScanRequest(**saved_request, consent=True)  # it was consented when it ran
    session.exposures = response.exposures
    return response


@app.post("/api/accounts", response_model=AccountsResponse)
async def accounts(req: AccountsRequest):
    """Stages 3 and 4, run together."""
    unknown = sorted(set(req.companies) - _company_ids())
    if unknown:
        raise HTTPException(400, f"Unknown company ids: {', '.join(unknown)}")
    (breaches, breach_errors), (policies, policy_errors) = await asyncio.gather(
        _stage("Stage 3 (breach timelines)", [], s3_breaches.breach_timelines, req.companies),
        _stage("Stage 4 (policy check)", [], s4_policy.check_policies, req.companies),
    )
    session.breaches, session.policies = breaches, policies
    return AccountsResponse(
        breaches=breaches, policies=policies, errors=breach_errors + policy_errors
    )


@app.get("/api/leads", response_model=LeadsResponse)
async def leads():
    """Stage 5, over everything gathered so far."""
    exposures, errors = await _stage(
        "Stage 5 (likely sources)", session.exposures, _rank, session.exposures
    )
    session.exposures = exposures
    return LeadsResponse(exposures=exposures, errors=errors)


@app.post("/api/optout", response_model=Draft)
async def optout(req: OptOutRequest):
    """Stage 6: draft a removal request for one listing or one company."""
    person = _require_scan()
    if req.exposure_id is not None:
        exposure = next((e for e in session.exposures if e.id == req.exposure_id), None)
        if exposure is None:
            raise HTTPException(404, "No exposure with that id in the current scan.")
        return await _call(
            "Stage 6 (opt-out drafts)", s6_resolve.draft_broker_opt_out, exposure, person
        )
    if req.company not in _company_ids():
        raise HTTPException(404, "Unknown company id.")
    return await _call(
        "Stage 6 (opt-out drafts)", s6_resolve.draft_company_request, req.company, person
    )


@app.post("/api/rescan", response_model=RescanResponse)
async def rescan():
    """Stage 6: check which listings came down. This is the subscription hook."""
    person = _require_scan()
    results, errors = await _stage(
        "Stage 6 (re-scan)", [], s6_resolve.rescan, session.exposures, person
    )
    return RescanResponse(results=results, errors=errors)


@app.get("/api/aliases", response_model=list[Alias])
async def aliases():
    return await _call("Stage 7 (aliases)", s7_aliases.list_aliases)


@app.post("/api/aliases", response_model=Alias)
async def new_alias(req: AliasRequest):
    return await _call("Stage 7 (aliases)", s7_aliases.create_alias, req.company)


@app.get("/api/inbox/check", response_model=list[AliasHit])
async def inbox_check():
    """Stage 7: runs locally on the mock inbox, no search."""
    session.alias_hits = await _call("Stage 7 (inbox check)", s7_aliases.check_inbox)
    return session.alias_hits


@app.get("/api/outbound-log", response_model=list[OutboundEntry])
async def outbound_log(include_local: bool = Query(default=True)):
    return outbound.get_log(include_local=include_local)


@app.delete("/api/outbound-log")
async def clear_outbound_log():
    outbound.clear_log()
    return {"cleared": True}
