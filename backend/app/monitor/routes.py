"""Threat monitor routes, /api/monitor/*. Included by main.py.

Errors: an unknown id is 404, a request that can't be done as asked is 400 (with a message
for the UI), a missing service or setting (SMTP, Gemini) is 503, and a second refresh
while one runs is 409. Personal data (email addresses, codes) goes in POST bodies only.
"""

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.companies import add_company as add_any_company
from app.models import (
    ActionUpdate,
    CompanyRequest,
    EmailRequest,
    Exposure,
    Incident,
    MonitorDashboard,
    MonitoredCompany,
    MonitoredEmail,
    MonitorSchedule,
    RefreshRequest,
    RefreshStatus,
    SeenRequest,
    VerifyCodeRequest,
)
from app.monitor import emails, service

router = APIRouter(prefix="/api/monitor", tags=["threat monitor"])


def _exposures(request: Request) -> list[Exposure]:
    """The exposure scan currently loaded in main.py's session (for related listings)."""
    getter = getattr(request.app.state, "current_exposures", None)
    return list(getter()) if getter else []


async def _run(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except LookupError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from None
    except service.RefreshBusy as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("", response_model=MonitorDashboard)
async def dashboard(request: Request):
    return await service.dashboard(_exposures(request))


@router.get("/refresh", response_model=RefreshStatus)
async def refresh_status():
    """Cheap to poll while a check runs."""
    return service.refresh_status()


@router.post("/refresh", response_model=RefreshStatus, status_code=202)
async def refresh(req: RefreshRequest):
    try:
        return service.start_refresh(company_id=req.company_id, include_news=req.include_news)
    except service.RefreshBusy as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/companies", response_model=MonitoredCompany)
async def add_company(req: CompanyRequest):
    """Any company: a listed one, a typed website, or a name matched to its website with one
    logged Exa search (company name only), exactly as in the account picker."""
    company = await _run(add_any_company(req.name))
    return await _run(service.add_company(company))


@router.delete("/companies/{company_id}")
async def remove_company(company_id: str):
    await _run(service.remove_company(company_id))
    return {"removed": True}


@router.post("/emails", response_model=MonitoredEmail)
async def add_email(req: EmailRequest):
    return await _run(emails.add(req.address))


@router.post("/emails/{email_id}/code", response_model=MonitoredEmail)
async def send_code(email_id: str):
    return await _run(emails.send_code(email_id))


@router.post("/emails/{email_id}/verify", response_model=MonitoredEmail)
async def verify_email(email_id: str, req: VerifyCodeRequest):
    return await _run(emails.verify(email_id, req.code))


@router.delete("/emails/{email_id}")
async def remove_email(email_id: str):
    await _run(emails.remove(email_id))
    return {"removed": True}


@router.post("/incidents/{incident_id}/actions/{action_id}", response_model=Incident)
async def set_action(incident_id: str, action_id: str, req: ActionUpdate, request: Request):
    await _run(service.set_action(incident_id, action_id, req.done))
    return service.incident_view(incident_id, _exposures(request))


@router.post("/incidents/{incident_id}/analyze", response_model=Incident)
async def analyze(incident_id: str, request: Request):
    return await _run(service.analyze(incident_id, _exposures(request)))


@router.post("/seen")
async def mark_seen(req: SeenRequest):
    return {"marked": await service.mark_seen(req.incident_ids)}


@router.post("/schedule", response_model=MonitorSchedule)
async def set_schedule(req: MonitorSchedule):
    return await service.set_schedule(req)
