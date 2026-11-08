"""Refresh behavior, alerts without duplicates, confirmation, steps, schedule and the link to
the exposure scanner (app/monitor/service.py, scheduler.py). Everything external is faked."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.clients import hibp
from app.models import BreachEvent, Exposure, FieldFinding
from app.monitor import emails, scheduler, service, store
from tests.monitor_fixtures import CATALOG, EMAIL, SHOPCO, use_settings


@pytest.fixture
def world(monkeypatch):
    """HIBP's breach list, an optional email range answer, Stage 3 and Ollama, all fake."""
    use_settings(monkeypatch, hibp_api_key="k", tavily_api_key="t")
    state = {"catalog": CATALOG, "catalog_error": None, "range": [], "news": [], "catalog_calls": 0}

    async def breaches():
        state["catalog_calls"] += 1
        if state["catalog_error"]:
            raise state["catalog_error"]
        return state["catalog"]

    async def range_search(prefix):
        return state["range"]

    async def timelines(ids):
        return [e for e in state["news"] if e.company_id in ids], []

    async def status():
        return True, True

    monkeypatch.setattr(hibp, "breaches", breaches)
    monkeypatch.setattr(hibp, "range_search", range_search)
    monkeypatch.setattr(service.s3_breaches, "breach_timelines", timelines)
    monkeypatch.setattr(service.ollama, "status", status)
    return state


def refresh(**kwargs):
    service._catalog = None  # every refresh in these tests re-reads the fake list
    return asyncio.run(service.run_refresh(**kwargs))


def add(company=SHOPCO):
    asyncio.run(service.add_company(company))


def views(exposures=()):
    return {v.id: v for v in service.incident_views(store.load(), list(exposures))}


def events(kind):
    return [e for e in store.load()["events"] if e["kind"] == kind]


def news(date, kind="occurred", url="https://news.example/shopco"):
    return BreachEvent(company_id="shopco", company="ShopCo", date=date, date_kind=kind, data_types=["email", "password"],
                       source_url=url, source_kind="news", summary="ShopCo reported a breach.")


def test_refresh_matches_companies_and_alerts_once(world):
    add()
    status = refresh()
    assert status.new_incidents == 2 and status.errors == []
    assert set(views()) == {"hibp-shopco", "hibp-shopco2023"}  # spam lists aren't company breaches
    assert len(events("new_incident")) == 2
    first_seen = store.load()["incidents"]["hibp-shopco"]["first_seen"]

    assert refresh().new_incidents == 0  # same breaches: no second alert
    assert len(events("new_incident")) == 2
    assert store.load()["incidents"]["hibp-shopco"]["first_seen"] == first_seen
    company = store.load()["companies"][0]
    assert company["last_checked"] and company["last_news_check"] is None


def test_company_breaches_are_not_user_confirmations(world):
    add()
    refresh()
    incident = views()["hibp-shopco"]
    assert incident.involvement == "unconfirmed" and incident.severity == "high"
    assert "doesn't mean your account was in it" in incident.involvement_reason


def test_news_folds_into_hibp_and_unrelated_news_is_its_own_incident(world):
    add()
    world["news"] = [news("2021-03"), news("2015", url="https://news.example/old")]
    status = refresh(include_news=True)
    shown = views()
    assert set(shown) == {"hibp-shopco", "hibp-shopco2023", "news-shopco-2015"}
    assert "https://news.example/shopco" in [s.url for s in shown["hibp-shopco"].sources]
    assert shown["news-shopco-2015"].involvement == "unconfirmed"
    assert "Not in HIBP" in shown["news-shopco-2015"].flags
    assert status.new_incidents == 3
    assert store.load()["companies"][0]["last_news_check"]


def test_a_breach_first_seen_in_the_news_is_not_alerted_again_when_hibp_adds_it(world):
    add()
    world["catalog_error"] = hibp.HibpError("HIBP is unavailable right now.", 503)
    world["news"] = [news("2021-03")]
    status = refresh(include_news=True)
    assert status.new_incidents == 1 and "HIBP is unavailable" in status.errors[0]
    first_seen = store.load()["incidents"]["news-shopco-2021"]["first_seen"]
    asyncio.run(service.set_action("news-shopco-2021", "change_password", True))

    world["catalog_error"] = None
    status = refresh()  # HIBP now has it; no news search this time
    assert status.new_incidents == 1  # only ShopCo (2023) is new
    shown = views()
    assert "news-shopco-2021" not in shown
    merged = shown["hibp-shopco"]
    assert merged.first_seen == first_seen  # state carried over from the news incident
    assert next(a for a in merged.actions if a.id == "change_password").done  # the step carried over
    assert "https://news.example/shopco" in [s.url for s in merged.sources]
    assert len(events("new_incident")) == 2


def test_news_about_a_known_hibp_breach_adds_sources_without_an_alert(world):
    add()
    refresh()
    world["catalog_error"] = hibp.HibpError("HIBP is unavailable right now.", 503)
    world["news"] = [news("2022-01", kind="disclosed", url="https://ag.example/notice")]
    assert refresh(include_news=True).new_incidents == 0
    assert "https://ag.example/notice" in [s.url for s in views()["hibp-shopco"].sources]


def test_news_search_is_skipped_without_keys_or_the_local_llm(world, monkeypatch):
    add()
    use_settings(monkeypatch, hibp_api_key="k")  # no Tavily or Exa key
    status = refresh(include_news=True)
    assert any("TAVILY_API_KEY or EXA_API_KEY" in e for e in status.errors)

    use_settings(monkeypatch, hibp_api_key="k", exa_api_key="e")

    async def down():
        return False, False

    monkeypatch.setattr(service.ollama, "status", down)
    status = refresh(include_news=True)
    assert any("local LLM" in e for e in status.errors)


def _verified(monkeypatch):
    data = store.load()
    data["emails"].append({"id": "em-1", "address": None, "sha1": emails.sha1_hex(EMAIL), "display": emails.mask(EMAIL),
                           "added_at": store.now(), "verified_at": store.now(), "code": None,
                           "check": {"status": "never", "message": "", "checked_at": None, "breaches": []}})
    store.save(data)


def test_a_verified_email_match_confirms_and_raises_severity(world, monkeypatch):
    add()
    _verified(monkeypatch)
    world["range"] = [{"hashSuffix": emails.sha1_hex(EMAIL)[6:], "websites": ["ShopCo", "OtherSite"]}]
    refresh()
    shown = views()
    assert shown["hibp-shopco"].involvement == "confirmed"
    assert shown["hibp-shopco"].severity == "critical"  # high, raised one level
    # OtherSite isn't a monitored company, but the user's address is in it, so it shows.
    assert shown["hibp-othersite"].involvement == "confirmed" and shown["hibp-othersite"].company_id is None
    assert shown["hibp-shopco2023"].involvement == "not_found"
    assert len(events("confirmed")) == 2

    refresh()  # same result: no new confirmation alerts
    assert len(events("confirmed")) == 2


def test_without_a_key_emails_show_a_configuration_state_not_results(world, monkeypatch):
    add()
    _verified(monkeypatch)
    use_settings(monkeypatch)  # no HIBP key
    refresh()
    record = store.load()["emails"][0]
    assert record["check"]["status"] == "not_configured" and record["check"]["breaches"] == []
    incident = views()["hibp-shopco"]
    assert incident.involvement == "unconfirmed" and "HIBP_API_KEY" in incident.involvement_reason


def test_steps_persist_and_done_never_means_secure(world):
    add()
    refresh()
    incident = views()["hibp-shopco"]
    for step in incident.actions:
        asyncio.run(service.set_action("hibp-shopco", step.id, True))
    raw = store.STORE_PATH.read_text()
    assert '"change_password"' in raw  # saved to disk
    done = views()["hibp-shopco"]
    assert done.steps_done and all(a.done and a.done_at for a in done.actions)
    assert done.involvement == "unconfirmed" and done.severity == "high"  # unchanged by the checklist

    asyncio.run(service.set_action("hibp-shopco", "change_password", False))
    assert not views()["hibp-shopco"].steps_done
    with pytest.raises(LookupError):
        asyncio.run(service.set_action("hibp-shopco", "not-a-step", True))
    with pytest.raises(LookupError):
        asyncio.run(service.set_action("nope", "change_password", True))


def test_removing_a_company_hides_its_incidents_and_re_adding_does_not_re_alert(world):
    add()
    refresh()
    asyncio.run(service.remove_company("shopco"))
    assert views() == {}
    add()
    assert refresh().new_incidents == 0 and set(views()) == {"hibp-shopco", "hibp-shopco2023"}
    with pytest.raises(LookupError):
        asyncio.run(service.remove_company("never-added"))


def test_mark_seen(world):
    add()
    refresh()
    assert all(v.new for v in views().values())
    asyncio.run(service.mark_seen(["hibp-shopco"]))
    assert not views()["hibp-shopco"].new and views()["hibp-shopco2023"].new
    asyncio.run(service.mark_seen(None))
    assert not any(v.new for v in views().values())


def test_related_listings_use_stage_5s_rule(world):
    add()
    refresh()
    listing = Exposure(id="e1", broker="PeopleFinder", url="https://people.example/jane",
                       fields=[FieldFinding(field="email", quote="j***@mail.example"), FieldFinding(field="phone", quote="555")],
                       public_by="2022-06-01", public_by_source="wayback")
    unrelated = Exposure(id="e2", broker="Other", url="https://other.example/j",
                         fields=[FieldFinding(field="phone", quote="555")], public_by="2022-06-01", public_by_source="wayback")
    [related] = views([listing, unrelated])["hibp-shopco"].related_listings
    assert related.exposure_id == "e1" and related.shared_fields == ["email"]
    assert related.lead_tier == "likely" and "ShopCo breach" in related.reason
    # Listed before the 2023 breach: overlap, but no likely-source claim.
    [early] = views([listing])["hibp-shopco2023"].related_listings
    assert early.lead_tier is None and "doesn't show this breach is where" in early.reason


def test_dashboard_summary(world, monkeypatch):
    add()
    refresh()

    async def ready():
        return True

    monkeypatch.setattr(service, "_local_llm_ready", ready)
    board = asyncio.run(service.dashboard([]))
    assert board.summary.monitored_companies == 1 and board.summary.company_breaches == 2
    assert board.summary.email_breaches == 0 and board.summary.open_alerts == 2 and board.summary.new_alerts == 2
    assert board.summary.actions_done == 0 and board.summary.actions_total > 0
    assert board.config.hibp_email_key and not board.config.smtp and board.config.news_search
    assert board.incidents[0].severity == "high" and board.scan_loaded is False


def test_schedule_and_scheduled_runs(world):
    add()
    saved = asyncio.run(service.set_schedule(service.MonitorSchedule(enabled=True, interval_hours=6)))
    assert saved.enabled and saved.next_run
    assert events("schedule")[0]["message"] == "Scheduled checks on, every 6 hours."

    now = datetime.now(timezone.utc)
    assert scheduler.due({"enabled": True, "interval_hours": 6, "last_run": None}, now)
    assert not scheduler.due({"enabled": True, "interval_hours": 6, "last_run": now.isoformat()}, now)
    assert scheduler.due({"enabled": True, "interval_hours": 6, "last_run": (now - timedelta(hours=7)).isoformat()}, now)
    assert not scheduler.due({"enabled": False, "interval_hours": 6, "last_run": None}, now)

    async def tick_and_wait():
        started = scheduler.tick()
        await service._task
        return started

    assert asyncio.run(tick_and_wait()) is True
    assert service.refresh_status().trigger == "scheduled" and not service.refresh_status().running
    assert store.load()["schedule"]["last_run"]
    assert events("refresh")[0]["message"].startswith("Scheduled check of 1 company")


def test_one_refresh_at_a_time(world, monkeypatch):
    gate = {}

    async def slow(**kwargs):
        await gate["event"].wait()

    monkeypatch.setattr(service, "run_refresh", slow)

    async def scenario():
        gate["event"] = asyncio.Event()
        service.start_refresh()
        with pytest.raises(service.RefreshBusy):
            service.start_refresh()
        gate["event"].set()
        await service._task
        service.start_refresh()  # free again
        gate["event"].set()
        await service._task

    asyncio.run(scenario())


def test_the_breach_list_is_cached(world):
    add()
    asyncio.run(service.run_refresh())
    asyncio.run(service.run_refresh())
    assert world["catalog_calls"] == 1


def test_saved_incidents_survive_reference_data_changes(world):
    """Categories are derived from data class names when shown, so an old saved category key
    (from an earlier data file) neither crashes the dashboard nor sticks around."""
    add()
    refresh()
    data = store.load()
    data["incidents"]["hibp-shopco"]["categories"] = ["category_that_no_longer_exists"]
    store.save(data)
    incident = views()["hibp-shopco"]
    assert incident.severity == "high" and incident.threat == "Passwords and email addresses exposed"
    assert refresh().new_incidents == 0  # merging with the stale record doesn't crash either


def test_news_labels_map_to_the_same_categories_as_stage_3():
    from app.monitor import breach_data, incidents as inc

    for field, label in inc.FIELD_LABEL.items():
        assert breach_data.categories_for_classes([label]) == breach_data.categories_for_fields([field]), field
