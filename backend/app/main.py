"""FastAPI routes: each one calls one or two pipeline stages (table in backend/CLAUDE.md).

Shared file: keep changes additive and call them out in the commit message.

The browser reaches these through the Next.js proxy (http://localhost:3000/api/*).
Personal data (name, city) goes in POST bodies, never in URLs or query strings.
Run from backend/:  uvicorn app.main:app --reload
"""

import asyncio
import inspect
import logging
import socket
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import psycopg
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app import auth, db, explain, extension_package, footprint, outbound, site_policy
from app.clients import ollama
from app.companies import add_company, all_companies
from app.config import LOCAL_HOSTS, get_settings
from app.data import load_json
from app.models import (
    AccountsRequest,
    AccountsResponse,
    Alias,
    AliasHit,
    AliasInvestigation,
    AliasMessage,
    AliasRequest,
    AliasUpdate,
    BreachEvent,
    CompanyRequest,
    Credentials,
    Draft,
    Exposure,
    LeadsResponse,
    OptOutRequest,
    PasswordChange,
    PasswordReset,
    PolicyResult,
    RequestCreate,
    RequestTextUpdate,
    RequestUpdate,
    RescanResponse,
    ResetCode,
    RoleUpdate,
    ScanRequest,
    ScanResponse,
    SitePolicyRequest,
    SitePolicyResponse,
    StatusResponse,
    TrackedCompany,
    TrackedCompanyInput,
    User,
)
from app.monitor import routes as monitor_routes
from app.monitor import scheduler as monitor_scheduler
from app.monitor import service as monitor_service
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
    return {c["id"] for c in all_companies()}


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
    # Threat monitor's scheduled checks: a loop in this process, so only while the backend runs.
    scheduled = asyncio.create_task(monitor_scheduler.run())
    yield
    scheduled.cancel()
    await monitor_service.stop()
    await outbound.close()


app = FastAPI(title="Hack1984 API", lifespan=lifespan)
# Only answer requests addressed to this machine, which blocks DNS-rebinding pages from
# reading saved scans or the outbound log through the browser.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
# Threat monitor (/api/monitor/*, app/monitor/). It reads the loaded scan to show which
# listings share data with a breach.
app.include_router(monitor_routes.router)
app.state.current_exposures = lambda: session.exposures

# Routes anyone on this laptop may call. Everything else under /api/ holds or acts on personal
# data (scans, saved scans, the outbound log, aliases, the footprint), so it needs a signed-in
# local account, whoever is asking: the browser, a script, or another program on this machine.
OPEN_ROUTES = {
    "/api/status", "/api/brokers",
    "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/reset",
}
# The browser extension (extension/) calls only this route. It has no session cookie (it talks to
# 127.0.0.1:8000, not the app) and sends a chrome-extension:// Origin. The route doesn't read or
# change anything stored here, and it checks the Origin itself: it refuses any web page.
EXTENSION_ROUTES = {"/api/site-policy"}
# The extension's "private email for this site" lists and makes aliases through the app
# (localhost:3000), with the user's own session cookie. A chrome-extension:// Origin may make
# changes on these exact routes and methods only; a signed-in session is still required, and
# every other change still has to come from a page on this laptop.
EXTENSION_SESSION_ROUTES = {("GET", "/api/aliases"), ("POST", "/api/aliases")}


def _extension_may_call(request: Request, origin: str | None) -> bool:
    return bool(origin and origin.startswith("chrome-extension://")) and (
        request.method, request.url.path
    ) in EXTENSION_SESSION_ROUTES


def _from_this_laptop(origin: str) -> bool:
    """localhost, or this laptop's own network address (the app opened from a phone on the same Wi-Fi)."""
    host = urlsplit(origin).hostname
    if host in LOCAL_HOSTS:
        return True
    try:
        return host in {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        return False


@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in EXTENSION_ROUTES:
        return await call_next(request)
    # Changes must come from a page on this laptop, even if some other site's page got a browser
    # to send our cookie along.
    origin = request.headers.get("origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and not _from_this_laptop(origin)
        and not _extension_may_call(request, origin)
    ):
        return JSONResponse({"detail": "Requests must come from this laptop."}, status_code=403)
    if path in OPEN_ROUTES:
        return await call_next(request)
    token = request.cookies.get(auth.COOKIE)
    try:
        user_id = await asyncio.to_thread(db.session_user_id, token) if token else None
    except psycopg.Error:
        return JSONResponse({"detail": DB_DOWN}, status_code=503)
    if not user_id:
        return JSONResponse({"detail": "Log in to continue."}, status_code=401)
    signed_in = auth.CURRENT_USER.set(user_id)  # db.py keeps saved scans per account with it
    try:
        return await call_next(request)
    finally:
        auth.CURRENT_USER.reset(signed_in)


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
    """The checked-in company list, then any companies the user added."""
    return all_companies()


@app.post("/api/companies")
async def add_company_route(req: CompanyRequest):
    """Add any company to the account picker. A typed website is used as is; a name is matched
    to its official website with one Exa company search (company name only, logged)."""
    return await _call("Add company", add_company, req.name)


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
    exposures = [explain.explain(e) for e in exposures]  # summary, risk and per-field details
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
    # Re-run the write-up: older saved scans don't have it, and its wording may have changed.
    response.exposures = [explain.explain(e) for e in response.exposures]
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
    """A new alias for a company or for the website you're signing up on (one per signup)."""
    return await _call("Stage 7 (aliases)", s7_aliases.create_alias, req.company, req.site, req.label)


@app.patch("/api/aliases/{address}", response_model=Alias)
async def update_alias(address: str, req: AliasUpdate):
    """Disable or re-enable one of your aliases, or change its note. 404 if it isn't yours."""
    return await _call("Stage 7 (aliases)", s7_aliases.update_alias, address, req.status, req.note)


@app.get("/api/aliases/{address}/messages", response_model=list[AliasMessage])
async def alias_messages(address: str):
    """One alias's mail from the mock inbox, newest first. Local only, no search."""
    return await _call("Stage 7 (aliases)", s7_aliases.messages_for, address)


@app.post("/api/aliases/{address}/investigate", response_model=AliasInvestigation)
async def investigate_alias(address: str):
    """Who wrote to this alias and what it suggests: rules set the facts and the tier, the
    local LLM only explains them. Nothing leaves the laptop."""
    return await _call("Stage 7 (aliases)", s7_aliases.investigate, address)


@app.get("/api/inbox/check", response_model=list[AliasHit])
async def inbox_check():
    """Stage 7: runs locally on the mock inbox, no search."""
    session.alias_hits = await _call("Stage 7 (inbox check)", s7_aliases.check_inbox)
    return session.alias_hits


@app.get("/api/extension.zip")
async def extension_download():
    """The browser extension, zipped from extension/ for Chrome's "Load unpacked". Signed-in
    accounts only during the beta (require_session covers this route)."""
    data = await asyncio.to_thread(extension_package.zip_extension)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{extension_package.FILENAME}"'},
    )


@app.post("/api/site-policy", response_model=SitePolicyResponse)
async def site_policy_check(req: SitePolicyRequest, origin: str | None = Header(default=None)):
    """The browser extension (extension/): what the privacy policy of the site you're visiting
    says it collects and shares, and the risks. The policy is read straight from the site (or
    sent by the browser) and analyzed on this laptop. Which sites you visit is never saved."""
    # Only the extension calls this route. A web page can't read the answer, but it could still
    # send page text to plant a fake verdict, so refuse anything that says it came from a page.
    if origin and not origin.startswith("chrome-extension://"):
        raise HTTPException(403, "Only the Dossier browser extension can use this route.")
    try:
        return await site_policy.check_site(req)
    except site_policy.CantCheck as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/outbound-log", response_model=list[OutboundEntry])
async def outbound_log(include_local: bool = Query(default=True)):
    return outbound.get_log(include_local=include_local)


@app.delete("/api/outbound-log")
async def clear_outbound_log():
    outbound.clear_log()
    return {"cleared": True}


# ---------- Local accounts ----------
# Users and sessions live in the local Postgres (auth.py, db.py). The session is an httpOnly
# cookie the browser only ever sends to localhost; the database keeps only its hash.

TOO_MANY = "Too many wrong tries. Wait a few minutes and try again."


async def _accounts_db(fn: Callable[..., Any], *args: Any) -> Any:
    """A db.py account call off the event loop. Postgres down is a 503; ValueError passes through."""
    try:
        return await asyncio.to_thread(fn, *args)
    except psycopg.Error as exc:
        raise HTTPException(503, DB_DOWN) from exc


def _start_session(response: Response, user_id: str) -> None:
    token = auth.new_token()
    db.create_session(user_id, token)
    response.set_cookie(
        auth.COOKIE, token, httponly=True, samesite="lax", max_age=30 * 24 * 3600, path="/"
    )


async def _signed_in_user() -> dict[str, Any]:
    """The signed-in account (require_session checked the cookie) with its email and role."""
    user_id = auth.current_user()
    user = await _accounts_db(db.user_by_id, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Log in to continue.")
    return user


async def _admin() -> dict[str, Any]:
    user = await _signed_in_user()
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do that.")
    return user


@app.post("/api/auth/signup", response_model=User)
async def signup(req: Credentials, response: Response):
    """Create an account and sign in. The first account on this laptop becomes the admin."""
    hashed = await asyncio.to_thread(auth.hash_password, req.password)
    created = await _accounts_db(db.create_user, req.email, hashed)
    if not created:
        raise HTTPException(409, "An account with that email already exists. Log in instead.")
    found = await _accounts_db(db.get_user, req.email)
    await _accounts_db(db.claim_unowned_scans, found[0])  # the laptop's first account only
    await _accounts_db(_start_session, response, found[0])
    return User(**await _accounts_db(db.user_by_id, found[0]))


@app.post("/api/auth/login", response_model=User)
async def login(req: Credentials, response: Response):
    if auth.throttled(req.email):
        raise HTTPException(429, TOO_MANY)
    found = await _accounts_db(db.get_user, req.email)
    # An unknown email is checked against a dummy hash, so it takes as long as a wrong password.
    ok = await asyncio.to_thread(auth.verify_password, req.password, found[1] if found else auth.DUMMY_HASH)
    if not found or not ok:
        auth.record_failure(req.email)
        raise HTTPException(401, "That email and password don't match.")
    auth.clear_failures(req.email)
    await _accounts_db(_start_session, response, found[0])
    return User(**await _accounts_db(db.user_by_id, found[0]))


@app.post("/api/auth/logout")
async def logout(response: Response, h84_session: str | None = Cookie(default=None)):
    if h84_session:
        try:
            await asyncio.to_thread(db.delete_session, h84_session)
        except Exception:
            pass  # the cookie is cleared either way
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me", response_model=User)
async def me(h84_session: str | None = Cookie(default=None)):
    if not h84_session:
        raise HTTPException(401, "Log in to continue.")
    found = await _accounts_db(db.session_user, h84_session)
    if not found:
        raise HTTPException(401, "Your session ended. Log in again.")
    return User(**found)


@app.post("/api/auth/password")
async def change_password(body: PasswordChange, h84_session: str | None = Cookie(default=None)):
    """The signed-in user changes their password. Their other sessions end; this one stays."""
    user = await _signed_in_user()
    email = user["email"]
    if auth.throttled(email):
        raise HTTPException(429, TOO_MANY)
    found = await _accounts_db(db.get_user, email)
    if not found or not await asyncio.to_thread(auth.verify_password, body.current_password, found[1]):
        auth.record_failure(email)
        raise HTTPException(400, "Your current password isn't right.")
    auth.clear_failures(email)
    hashed = await asyncio.to_thread(auth.hash_password, body.new_password)
    await _accounts_db(db.set_password, email, hashed, h84_session)
    return {"changed": True}


@app.post("/api/auth/reset", response_model=User)
async def reset_password(body: PasswordReset, response: Response):
    """A forgotten password: spend the one-time code an admin created, set a new password and
    sign in. The account's other sessions end."""
    if auth.throttled(body.email):
        raise HTTPException(429, TOO_MANY)
    if not await _accounts_db(db.use_reset, auth.normalize_code(body.code), body.email):
        auth.record_failure(body.email)
        raise HTTPException(400, "That code isn't valid for this email, or it has expired. Ask an admin for a new one.")
    auth.clear_failures(body.email)
    hashed = await asyncio.to_thread(auth.hash_password, body.new_password)
    await _accounts_db(db.set_password, body.email, hashed)
    found = await _accounts_db(db.get_user, body.email)
    await _accounts_db(_start_session, response, found[0])
    return User(**await _accounts_db(db.user_by_id, found[0]))


# ---------- Admin: the accounts on this laptop ----------
# Admins only (_admin): list accounts, change roles, remove an account with everything it owns
# here, and create a one-time password reset code to hand over in person. db.py refuses to demote
# or remove the last admin.


@app.get("/api/admin/users", response_model=list[User])
async def admin_users(admin: dict = Depends(_admin)):
    return await _accounts_db(db.list_users)


@app.patch("/api/admin/users/{user_id}", response_model=User)
async def admin_set_role(user_id: str, body: RoleUpdate, admin: dict = Depends(_admin)):
    try:
        user = await _accounts_db(db.set_role, user_id, body.role)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if user is None:
        raise HTTPException(404, "There's no account with that id.")
    return user


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: dict = Depends(_admin)):
    """Remove an account with its sessions, saved scans and footprint."""
    if user_id == admin["id"]:
        raise HTTPException(409, "You can't remove your own account here.")
    try:
        deleted = await _accounts_db(db.delete_user, user_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if not deleted:
        raise HTTPException(404, "There's no account with that id.")
    return {"deleted": True}


@app.post("/api/admin/users/{user_id}/reset-code", response_model=ResetCode)
async def admin_reset_code(user_id: str, admin: dict = Depends(_admin)):
    """A one-time password reset code, shown here once. Making a new one cancels the old one."""
    user = await _accounts_db(db.user_by_id, user_id)
    if user is None:
        raise HTTPException(404, "There's no account with that id.")
    code = auth.new_reset_code()
    expires_at = await _accounts_db(db.create_reset, user["id"], code, auth.RESET_MINUTES)
    return ResetCode(email=user["email"], code=code, expires_at=expires_at)


# ---------- Digital footprint ----------
# The user's own records of companies that hold their data and the requests they've made to
# them, kept in the local Postgres for the signed-in account. Nothing here calls outbound.request:
# drafts are local templates, and Dossier never sends a request or changes a company's settings.

NOT_TRACKED = "That company isn't in your footprint."
NO_REQUEST = "That request isn't in your footprint."


async def _footprint_db(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except psycopg.Error as exc:
        raise HTTPException(503, DB_DOWN) from exc


async def _footprint_user() -> str:
    """The signed-in account (require_session checked the cookie). Footprint records are only
    ever read or changed for it."""
    user_id = auth.current_user()
    if not user_id:
        raise HTTPException(401, "Log in to see your footprint.")
    return user_id


async def _check_new_name(user_id: str, name: str, company_id: str | None = None) -> None:
    rows = await _footprint_db(db.footprint_companies, user_id)
    if any(r["name"].casefold() == name.casefold() and r["id"] != company_id for r in rows):
        raise HTTPException(409, f"You already track {name}.")


def _tracked_company(row: dict[str, Any]) -> TrackedCompany:
    for request in row["requests"]:
        request["next_statuses"] = list(footprint.NEXT[request["status"]])
        request["editable"] = request["status"] in footprint.EDITABLE
    return TrackedCompany(**row)


async def _tracked(user_id: str, company_id: str) -> TrackedCompany:
    rows = await _footprint_db(db.footprint_companies, user_id, company_id)
    if not rows:
        raise HTTPException(404, NOT_TRACKED)
    return _tracked_company(rows[0])


async def _owned_request(user_id: str, request_id: uuid.UUID) -> dict[str, Any]:
    found = await _footprint_db(db.footprint_request, user_id, str(request_id))
    if not found:
        raise HTTPException(404, NO_REQUEST)
    return found


@app.get("/api/footprint", response_model=list[TrackedCompany])
async def footprint_list(user_id: str = Depends(_footprint_user)):
    return [_tracked_company(row) for row in await _footprint_db(db.footprint_companies, user_id)]


@app.post("/api/footprint", response_model=TrackedCompany)
async def footprint_add(req: TrackedCompanyInput, user_id: str = Depends(_footprint_user)):
    await _check_new_name(user_id, req.name)
    company_id = await _footprint_db(db.create_footprint_company, user_id, req.model_dump(mode="json"))
    return await _tracked(user_id, company_id)


@app.put("/api/footprint/{company_id}", response_model=TrackedCompany)
async def footprint_edit(company_id: uuid.UUID, req: TrackedCompanyInput, user_id: str = Depends(_footprint_user)):
    await _check_new_name(user_id, req.name, str(company_id))
    if not await _footprint_db(db.update_footprint_company, user_id, str(company_id), req.model_dump(mode="json")):
        raise HTTPException(404, NOT_TRACKED)
    return await _tracked(user_id, str(company_id))


@app.delete("/api/footprint/{company_id}")
async def footprint_remove(company_id: uuid.UUID, user_id: str = Depends(_footprint_user)):
    if not await _footprint_db(db.delete_footprint_company, user_id, str(company_id)):
        raise HTTPException(404, NOT_TRACKED)
    return {"deleted": True}


@app.post("/api/footprint/{company_id}/requests", response_model=TrackedCompany)
async def footprint_draft(company_id: uuid.UUID, req: RequestCreate, user_id: str = Depends(_footprint_user)):
    company = await _tracked(user_id, str(company_id))
    subject, body = footprint.draft(req.kind, req.law, company.name, company.account_label)
    if not await _footprint_db(db.create_footprint_request, user_id, company.id, req.kind, req.law, subject, body):
        raise HTTPException(404, NOT_TRACKED)
    return await _tracked(user_id, company.id)


@app.patch("/api/footprint/requests/{request_id}", response_model=TrackedCompany)
async def footprint_edit_request(request_id: uuid.UUID, req: RequestTextUpdate, user_id: str = Depends(_footprint_user)):
    current = await _owned_request(user_id, request_id)
    if current["status"] not in footprint.EDITABLE:
        raise HTTPException(409, "You marked this request sent, so its text stays as it was sent.")
    if not await _footprint_db(db.update_footprint_request_text, user_id, str(request_id), req.subject, req.body):
        raise HTTPException(404, NO_REQUEST)
    return await _tracked(user_id, current["company_id"])


@app.post("/api/footprint/requests/{request_id}/updates", response_model=TrackedCompany)
async def footprint_record_update(request_id: uuid.UUID, req: RequestUpdate, user_id: str = Depends(_footprint_user)):
    current = await _owned_request(user_id, request_id)
    happened_on = req.happened_on or date.today()
    try:
        footprint.check_update(current["status"], req.status, req.note, happened_on, current["last_on"])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not await _footprint_db(db.add_footprint_event, user_id, str(request_id), req.status, happened_on, req.note):
        raise HTTPException(404, NO_REQUEST)
    return await _tracked(user_id, current["company_id"])


@app.delete("/api/footprint/requests/{request_id}/updates/last", response_model=TrackedCompany)
async def footprint_undo_update(request_id: uuid.UUID, user_id: str = Depends(_footprint_user)):
    """Undo the last recorded step, e.g. a request marked sent by mistake."""
    undone = await _footprint_db(db.undo_footprint_event, user_id, str(request_id))
    if not undone:
        raise HTTPException(404, NO_REQUEST)
    company_id, removed = undone
    if not removed:
        raise HTTPException(409, "There's no recorded step to undo.")
    return await _tracked(user_id, company_id)


@app.delete("/api/footprint/requests/{request_id}", response_model=TrackedCompany)
async def footprint_remove_request(request_id: uuid.UUID, user_id: str = Depends(_footprint_user)):
    company_id = await _footprint_db(db.delete_footprint_request, user_id, str(request_id))
    if not company_id:
        raise HTTPException(404, NO_REQUEST)
    return await _tracked(user_id, company_id)
