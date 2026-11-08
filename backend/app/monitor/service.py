"""Threat monitor service: refresh, dashboard, steps, alerts and schedule.

A refresh, in order (each part can fail without stopping the rest):
1. Download HIBP's whole breach list (cached 30 minutes) and match each monitored company
   on this laptop. HIBP learns nothing about which companies are monitored.
2. Optionally (include_news), run Stage 3 for each company: Tavily and Exa searches with the
   company name only, read by Gemini. News incidents that describe an HIBP breach are
   folded into it.
3. Check each verified email with HIBP's hashed search (first 6 hash characters only).
4. Save: new incidents and newly confirmed ones become alerts, once. Known incidents keep their
   first-seen time, steps and explanation.

Severity, confidence, involvement and steps are derived when an incident is shown, never
stored, so a rule change applies everywhere at once.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients import gemini, hibp
from app.config import get_settings
from app.models import (
    SEVERITIES,
    BreachEvent,
    Exposure,
    Incident,
    IncidentDate,
    IncidentSource,
    MonitorConfig,
    MonitorDashboard,
    MonitoredCompany,
    MonitorEvent,
    MonitorSchedule,
    MonitorSummary,
    RefreshStatus,
    RelatedListing,
    ThreatAnalysis,
)
from app.monitor import analysis, breach_data, checklist, emails, incidents, severity, store
from app.stages import s3_breaches, s5_ranking

log = logging.getLogger(__name__)

CATALOG_TTL = 30 * 60  # seconds
MAX_ERROR_EVENTS = 5

_catalog: tuple[float, list[dict[str, Any]]] | None = None
_status = RefreshStatus()
_task: asyncio.Task | None = None


class RefreshBusy(Exception):
    pass


# ---------- refresh ----------


async def catalog() -> list[dict[str, Any]]:
    global _catalog
    if _catalog and time.monotonic() - _catalog[0] < CATALOG_TTL:
        return _catalog[1]
    data = await hibp.breaches()
    _catalog = (time.monotonic(), data)
    return data


def refresh_status() -> RefreshStatus:
    return _status.model_copy(deep=True)


def is_running() -> bool:
    return _task is not None and not _task.done()


def start_refresh(*, company_id: str | None = None, include_news: bool = False, trigger: str = "manual") -> RefreshStatus:
    """Start a refresh in the background and return its status; poll refresh_status()."""
    global _task, _status
    if is_running():
        raise RefreshBusy("A check is already running.")
    _status = RefreshStatus(running=True, trigger=trigger, started_at=store.now(), include_news=include_news, step="Starting")
    _task = asyncio.create_task(_run_logged(company_id, include_news, trigger))
    return refresh_status()


async def _run_logged(company_id: str | None, include_news: bool, trigger: str) -> None:
    try:
        await run_refresh(company_id=company_id, include_news=include_news, trigger=trigger)
    except Exception as exc:
        log.exception("Threat monitor refresh failed")
        _status.errors.append(f"The check failed: {exc}")
    finally:
        _status.running = False
        _status.finished_at = store.now()
        _status.step = "Finished"


async def stop() -> None:
    """Cancel a running refresh (app shutdown)."""
    if is_running() and _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass


def _step(text: str) -> None:
    _status.step = text


def _company(record: dict[str, Any]) -> dict[str, Any]:
    return {"id": record["id"], "name": record["name"], "domains": record.get("domains", [])}


async def _news_ready() -> str | None:
    """Why the news search can't run, or None. Checked first so a refresh never spends search
    credits on results Gemini can't read."""
    settings = get_settings()
    if not (settings.tavily_api_key or settings.exa_api_key):
        return "News and official-notice search needs TAVILY_API_KEY or EXA_API_KEY in .env."
    if not gemini.ready():
        return "News and official-notice search needs the AI API key in .env."
    return None


async def run_refresh(*, company_id: str | None = None, include_news: bool = False, trigger: str = "manual") -> RefreshStatus:
    data = store.load()
    companies = [c for c in data["companies"] if company_id is None or c["id"] == company_id]
    if company_id is not None and not companies:
        raise LookupError("That company isn't monitored.")
    verified = [e for e in data["emails"] if e.get("verified_at")] if company_id is None else []
    _status.total = 1 + (len(companies) if include_news else 0) + (1 if verified else 0)
    _status.done = 0
    errors: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    messages: dict[str, list[str]] = {c["id"]: [] for c in companies}

    # 1. HIBP's breach list, matched here.
    _step("Matching your companies against Have I Been Pwned's breach list")
    breaches: list[dict[str, Any]] | None = None
    try:
        breaches = await catalog()
    except Exception as exc:
        errors.append(f"Couldn't download Have I Been Pwned's breach list: {exc}")
    hibp_checked: set[str] = set()
    if breaches is not None:
        for record in companies:
            company = _company(record)
            for breach in breaches:
                if breach.get("IsSpamList") or not incidents.matches_company(breach, company):
                    continue
                facts = incidents.hibp_facts(breach, company, "hibp_catalog")
                if facts:
                    found[facts["id"]] = facts
            hibp_checked.add(record["id"])
    _status.done += 1

    # 2. News and official notices (Stage 3, unchanged).
    news_checked: set[str] = set()
    if include_news and companies:
        problem = await _news_ready()
        if problem:
            errors.append(problem)
        for record in companies if not problem else []:
            _step(f"Searching news and official notices for {record['name']} (about a minute)")
            try:
                events, stage_errors = await s3_breaches.breach_timelines([record["id"]])
            except Exception as exc:
                events, stage_errors = [], [f"{record['name']}: news search failed: {exc}"]
            errors += stage_errors
            messages[record["id"]] += stage_errors
            company = _company(record)
            news = [incidents.news_facts(e, company) for e in events]
            mine = [f for f in found.values() if f["company_id"] == record["id"]]
            for facts in incidents.merge_news(mine, news):
                found[facts["id"]] = facts
            news_checked.add(record["id"])
            _status.done += 1

    # 3. Verified emails, hashed.
    checks: dict[str, dict[str, Any]] = {}
    if verified:
        _step("Checking your verified emails with Have I Been Pwned (hashed)")
        checks = await emails.check(verified)
        by_name = {b.get("Name"): b for b in breaches or []}
        for result in checks.values():
            for name in result["breaches"] if result["status"] == "ok" else []:
                fid = incidents.hibp_id(name)
                if fid in found:
                    continue
                breach = by_name.get(name)
                owner = next((c for c in data["companies"] if breach and incidents.matches_company(breach, _company(c))), None)
                facts = (
                    incidents.hibp_facts(breach, _company(owner) if owner else None, "hibp_email")
                    if breach
                    else incidents.minimal_hibp_facts(name)
                )
                if facts:
                    found[facts["id"]] = facts
        _status.done += 1

    # 4. Save, alerting once per new incident or new confirmation.
    _step("Saving")
    async with store.edit() as current:
        new = _save(current, found, checks, hibp_checked, news_checked, messages, errors, trigger, include_news, full=company_id is None)
    _status.new_incidents = new
    _status.errors = errors
    return refresh_status()


def _union_facts(previous: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Fresh facts, plus anything only the previous check found (e.g. news sources from a
    check that included news, when this one didn't)."""
    merged = incidents.absorb(fresh, {**previous, "id": previous["id"]})
    merged["aliases"] = [a for a in merged["aliases"] if a != fresh["id"]]
    return merged


def _previous_id(data: dict[str, Any], facts: dict[str, Any]) -> str | None:
    """The stored incident these facts describe: same id or alias, or, for an HIBP breach, a
    news-only incident it matches (same company, compatible year). None means it's new."""
    for candidate in [facts["id"], *facts.get("aliases", [])]:
        fid = store.find_incident_id(data, candidate)
        if fid:
            return fid
    if facts.get("hibp_name"):
        matches = [
            (dist, fid)
            for fid, other in data["incidents"].items()
            if not other.get("hibp_name")
            and other.get("company_id") == facts.get("company_id")
            and (dist := incidents.distance(facts, other)) is not None
        ]
        if matches:
            return min(matches)[1]
    return None


def _known_hibp_match(data: dict[str, Any], news: dict[str, Any]) -> str | None:
    """A stored HIBP incident that a news-only incident describes, if any."""
    if store.find_incident_id(data, news["id"]) and not data["incidents"].get(news["id"], {}).get("hibp_name"):
        return None  # already stored on its own; update it in place
    matches = [
        (dist, fid)
        for fid, other in data["incidents"].items()
        if other.get("hibp_name")
        and other.get("company_id") == news.get("company_id")
        and (dist := incidents.distance(other, news)) is not None
    ]
    return min(matches)[1] if matches else None


def _save(
    data: dict[str, Any],
    found: dict[str, dict[str, Any]],
    checks: dict[str, dict[str, Any]],
    hibp_checked: set[str],
    news_checked: set[str],
    messages: dict[str, list[str]],
    errors: list[str],
    trigger: str,
    include_news: bool,
    *,
    full: bool,
) -> int:
    now = store.now()
    emails.prune_unverified(data)
    known: dict[str, dict[str, Any]] = data["incidents"]
    monitored = {c["id"] for c in data["companies"]}
    new = 0
    for fid, facts in found.items():
        if facts.get("company_id") and facts["company_id"] not in monitored:
            continue  # removed while the check ran
        host_id = None if facts.get("hibp_name") else _known_hibp_match(data, facts)
        if host_id:
            # A news report of a breach already known from HIBP: add its sources, no alert.
            known[host_id] = {**incidents.absorb(known[host_id], facts), "last_seen": now}
            continue
        previous_id = _previous_id(data, facts)
        if previous_id:
            previous = known.pop(previous_id)
            state = {k: previous.get(k) for k in ("first_seen", "seen", "analysis")}
            facts = _union_facts(previous, facts)
            if previous_id != fid:
                facts["aliases"] = list(dict.fromkeys([*facts["aliases"], previous_id]))
                moved = data["actions"].pop(previous_id, {})
                data["actions"][fid] = {**moved, **data["actions"].get(fid, {})}
        else:
            state = {"first_seen": now, "seen": False, "analysis": None}
            new += 1
            where = f" ({facts['company']})" if facts["company"] != facts["title"] else ""
            store.add_event(data, "new_incident", f"New: {facts['title']}{where}.", fid)
        known[fid] = {**facts, **state, "last_seen": now}

    for record in data["emails"]:
        result = checks.get(record["id"])
        if not result:
            continue
        before = set((record.get("check") or {}).get("breaches") or [])
        record["check"] = result
        if result["status"] != "ok":
            continue
        for name in result["breaches"]:
            if name in before:
                continue
            fid = store.find_incident_id(data, incidents.hibp_id(name)) or incidents.hibp_id(name)
            if fid in known:
                known[fid]["seen"] = False
            title = known.get(fid, {}).get("title", name)
            store.add_event(data, "confirmed", f"{record['display']} is listed in {title} (Have I Been Pwned).", fid)

    for company in data["companies"]:
        if company["id"] in hibp_checked:
            company["last_checked"] = now
        if company["id"] in news_checked:
            company["last_news_check"] = now
        if company["id"] in messages:
            company["messages"] = messages[company["id"]][:5]

    who = "Scheduled" if trigger == "scheduled" else "Manual"
    parts = [f"{len(hibp_checked)} compan{'y' if len(hibp_checked) == 1 else 'ies'}"]
    if checks:
        parts.append(f"{len(checks)} email{'' if len(checks) == 1 else 's'}")
    news = ", with news and official notices" if include_news and news_checked else ""
    store.add_event(data, "refresh", f"{who} check of {' and '.join(parts)}{news}: {new} new incident{'' if new == 1 else 's'}.")
    for error in errors[:MAX_ERROR_EVENTS]:
        store.add_event(data, "error", error)
    if full:
        data["schedule"]["last_run"] = now
    return new


# ---------- views ----------


def categories(facts: dict[str, Any]) -> list[str]:
    """An incident's data categories, always derived from its data class names (HIBP's, or
    Stage 3's labels), so a change to data/breach_data_classes.json applies to saved incidents."""
    return breach_data.categories_for_classes(facts.get("data_classes", []))


def _best_date(facts: dict[str, Any]) -> tuple[str | None, str]:
    for kind in ("occurred", "disclosed"):
        for d in facts.get("dates", []):
            if d["kind"] == kind:
                return d["date"], kind
    return None, "unknown"


def related_listings(facts: dict[str, Any], exposures: list[Exposure]) -> list[RelatedListing]:
    """Listings from the current scan that show data this breach reportedly exposed. Stage 5's
    own rule decides whether the company counts as a likely source; overlap alone never does."""
    types = set(breach_data.field_types_for(categories(facts))) - {"name"}
    if not types or not exposures:
        return []
    when, kind = _best_date(facts)
    source = next((s for s in facts.get("sources", []) if s["kind"] != "hibp"), None)
    ranked = exposures
    if when:
        event = BreachEvent(
            company_id=facts.get("company_id") or facts["id"],
            company=facts["company"],
            date=when,
            date_kind=kind,
            data_types=sorted(types),
            source_url=(source or facts["sources"][0])["url"] if facts.get("sources") else "",
            source_kind="ag_notice" if source and source["kind"] == "ag_notice" else ("news" if source and source["kind"] == "news" else "web"),
        )
        ranked = s5_ranking.rank_sources(exposures, [event], [], [])
    out = []
    for exposure in ranked:
        fields = {f.field for f in exposure.fields}
        shared = fields & types
        if "age" in fields and "birthdate" in types:
            shared.add("age")
        if not shared:
            continue
        lead = next((lead for lead in exposure.leads if lead.company == facts["company"]), None)
        ordered = [f for f in s5_ranking.FIELD_ORDER if f in shared]
        reason = f"{exposure.broker} shows your {', '.join(ordered)}, the same kinds of data this breach reportedly exposed. "
        reason += (
            lead.reasons[0]
            if lead
            else "That overlap alone doesn't show this breach is where the listing got its data."
        )
        out.append(
            RelatedListing(
                exposure_id=exposure.id,
                site=exposure.broker,
                url=exposure.url,
                shared_fields=ordered,
                lead_tier=lead.tier if lead else None,
                reason=reason,
            )
        )
    return out


def build_incident(
    facts: dict[str, Any], email_records: list[dict[str, Any]], progress: dict[str, str], exposures: list[Exposure]
) -> Incident:
    status, status_reason = severity.involvement(facts, email_records)
    conf, conf_reason = severity.confidence(facts)
    kinds = categories(facts)
    level, reasons = severity.severity(kinds, involvement=status, confidence=conf, hibp=facts.get("hibp"))
    official = next((s["url"] for s in facts.get("sources", []) if s.get("official") and s["kind"] != "hibp"), None)
    steps = checklist.steps(kinds, facts["company"], progress, official)
    saved = facts.get("analysis")
    explained = None
    if saved:
        explained = ThreatAnalysis(
            **{k: v for k, v in saved.items() if k != "input_hash"},
            stale=saved.get("input_hash") != analysis.input_hash(facts, level, status),
        )
    return Incident(
        id=facts["id"],
        company_id=facts.get("company_id"),
        company=facts["company"],
        title=facts["title"],
        domain=facts.get("domain"),
        description=facts.get("description", ""),
        data_classes=facts.get("data_classes", []),
        data_types=breach_data.field_types_for(kinds),
        pwn_count=facts.get("pwn_count"),
        dates=[IncidentDate(**d) for d in facts.get("dates", [])],
        sources=[IncidentSource(**s) for s in facts.get("sources", [])],
        threat=checklist.threat_label(kinds),
        risks=checklist.risks(kinds),
        severity=level,
        severity_reasons=reasons,
        confidence=conf,
        confidence_reason=conf_reason,
        involvement=status,
        involvement_reason=status_reason,
        flags=severity.flags(facts),
        actions=steps,
        analysis=explained,
        related_listings=related_listings(facts, exposures),
        first_seen=facts.get("first_seen") or store.now(),
        new=not facts.get("seen", False),
        steps_done=bool(steps) and all(s.done for s in steps),
    )


def _visible(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Incidents at monitored companies, plus any a verified email is confirmed in."""
    monitored = {c["id"] for c in data["companies"]}
    out = []
    for facts in data["incidents"].values():
        if facts.get("company_id") in monitored or severity.involvement(facts, data["emails"])[0] == "confirmed":
            out.append(facts)
    return out


def _sort_key(incident: Incident) -> tuple[Any, ...]:
    """Open before done, then most severe, confirmed first, newest first."""
    newest = max((d.date for d in incident.dates if d.kind != "added_to_hibp"), default="")
    as_number = int(newest.replace("-", "").ljust(8, "0")) if newest else 0
    return (
        incident.steps_done,
        SEVERITIES.index(incident.severity),
        incident.involvement != "confirmed",
        -as_number,
    )


def incident_views(data: dict[str, Any], exposures: list[Exposure]) -> list[Incident]:
    views = [build_incident(f, data["emails"], data["actions"].get(f["id"], {}), exposures) for f in _visible(data)]
    return sorted(views, key=_sort_key)


async def _local_llm_ready() -> bool:
    return gemini.ready()


def schedule_view(data: dict[str, Any]) -> MonitorSchedule:
    s = data["schedule"]
    next_run = None
    if s.get("enabled"):
        last = s.get("last_run")
        try:
            next_run = (
                (datetime.fromisoformat(last) + timedelta(hours=s["interval_hours"])).isoformat(timespec="seconds")
                if last
                else store.now()
            )
        except ValueError:
            next_run = store.now()
    return MonitorSchedule(
        enabled=bool(s.get("enabled")),
        interval_hours=s.get("interval_hours", 24),
        include_news=bool(s.get("include_news")),
        last_run=s.get("last_run"),
        next_run=next_run,
    )


async def dashboard(exposures: list[Exposure]) -> MonitorDashboard:
    data = store.load()
    settings = get_settings()
    views = incident_views(data, exposures)
    counts: dict[str, int] = {}
    for v in views:
        if v.company_id:
            counts[v.company_id] = counts.get(v.company_id, 0) + 1
    companies = [
        MonitoredCompany(
            id=c["id"],
            name=c["name"],
            domains=c.get("domains", []),
            added_at=c["added_at"],
            last_checked=c.get("last_checked"),
            last_news_check=c.get("last_news_check"),
            incidents=counts.get(c["id"], 0),
            messages=c.get("messages", []),
        )
        for c in data["companies"]
    ]
    checked = [c.last_checked for c in companies if c.last_checked] + [
        e["check"]["checked_at"] for e in data["emails"] if (e.get("check") or {}).get("checked_at")
    ]
    all_steps = [a for v in views for a in v.actions]
    summary = MonitorSummary(
        monitored_companies=len(companies),
        verified_emails=sum(1 for e in data["emails"] if e.get("verified_at")),
        email_breaches=sum(1 for v in views if v.involvement == "confirmed"),
        company_breaches=sum(1 for v in views if v.company_id),
        open_alerts=sum(1 for v in views if not v.steps_done),
        new_alerts=sum(1 for v in views if v.new),
        actions_done=sum(1 for a in all_steps if a.done),
        actions_total=len(all_steps),
        last_check=max(checked) if checked else None,
    )
    return MonitorDashboard(
        summary=summary,
        companies=companies,
        emails=[emails.view(e) for e in data["emails"]],
        incidents=views,
        events=[MonitorEvent(**e) for e in data["events"][:60]],
        schedule=schedule_view(data),
        refresh=refresh_status(),
        config=MonitorConfig(
            hibp_email_key=bool(settings.hibp_api_key),
            smtp=settings.smtp_configured,
            news_search=bool(settings.tavily_api_key or settings.exa_api_key),
            local_llm=await _local_llm_ready(),
            local_llm_model=settings.gemini_model,
        ),
        scan_loaded=bool(exposures),
    )


def incident_view(incident_id: str, exposures: list[Exposure]) -> Incident:
    data = store.load()
    fid = store.find_incident_id(data, incident_id)
    if fid is None:
        raise LookupError("No incident with that id.")
    facts = data["incidents"][fid]
    return build_incident(facts, data["emails"], data["actions"].get(fid, {}), exposures)


# ---------- user actions ----------


async def add_company(company: dict[str, Any]) -> MonitoredCompany:
    async with store.edit() as data:
        existing = next((c for c in data["companies"] if c["id"] == company["id"]), None)
        if existing is None:
            existing = {
                "id": company["id"],
                "name": company["name"],
                "domains": list(company.get("domains", [])),
                "added_at": store.now(),
                "last_checked": None,
                "last_news_check": None,
                "messages": [],
            }
            data["companies"].append(existing)
            store.add_event(data, "company", f"Started monitoring {company['name']}.")
    return MonitoredCompany(**{k: v for k, v in existing.items()})


async def remove_company(company_id: str) -> None:
    """Stop monitoring a company. Its incidents are kept (hidden), so adding it back later
    doesn't raise the same alerts again."""
    async with store.edit() as data:
        record = next((c for c in data["companies"] if c["id"] == company_id), None)
        if record is None:
            raise LookupError("That company isn't monitored.")
        data["companies"].remove(record)
        store.add_event(data, "company", f"Stopped monitoring {record['name']}.")


async def set_action(incident_id: str, action_id: str, done: bool) -> None:
    async with store.edit() as data:
        fid = store.find_incident_id(data, incident_id)
        if fid is None:
            raise LookupError("No incident with that id.")
        facts = data["incidents"][fid]
        official = next((s["url"] for s in facts.get("sources", []) if s.get("official") and s["kind"] != "hibp"), None)
        valid = {s.id for s in checklist.steps(categories(facts), facts["company"], {}, official)}
        if action_id not in valid:
            raise LookupError("That step isn't on this incident's checklist.")
        progress = data["actions"].setdefault(fid, {})
        if done:
            progress.setdefault(action_id, store.now())
        else:
            progress.pop(action_id, None)


async def mark_seen(incident_ids: list[str] | None) -> int:
    async with store.edit() as data:
        ids = (
            list(data["incidents"])
            if incident_ids is None
            else [fid for i in incident_ids if (fid := store.find_incident_id(data, i))]
        )
        for fid in ids:
            data["incidents"][fid]["seen"] = True
    return len(ids)


async def set_schedule(schedule: MonitorSchedule) -> MonitorSchedule:
    async with store.edit() as data:
        before = dict(data["schedule"])
        data["schedule"].update(
            enabled=schedule.enabled, interval_hours=schedule.interval_hours, include_news=schedule.include_news
        )
        if before.get("enabled") != schedule.enabled or before.get("interval_hours") != schedule.interval_hours:
            every = {6: "6 hours", 12: "12 hours", 24: "day", 168: "week"}[schedule.interval_hours]
            store.add_event(
                data,
                "schedule",
                f"Scheduled checks on, every {every}." if schedule.enabled else "Scheduled checks off.",
            )
        return schedule_view(data)


async def analyze(incident_id: str, exposures: list[Exposure]) -> Incident:
    """Explain one incident with Gemini, check the answer, and save it."""
    data = store.load()
    fid = store.find_incident_id(data, incident_id)
    if fid is None:
        raise LookupError("No incident with that id.")
    facts = data["incidents"][fid]
    view = build_incident(facts, data["emails"], {}, [])
    if not gemini.ready():
        raise RuntimeError("The AI model isn't set up. Add its API key to .env.")
    result = await analysis.explain(
        facts,
        level=view.severity,
        level_reasons=view.severity_reasons,
        involvement=view.involvement,
        involvement_reason=view.involvement_reason,
    )
    result["input_hash"] = analysis.input_hash(facts, view.severity, view.involvement)
    async with store.edit() as current:
        if fid in current["incidents"]:
            current["incidents"][fid]["analysis"] = result
    return incident_view(fid, exposures)
