"""Breach data parsing, company matching and duplicate detection (app/monitor/incidents.py)."""

import json

from app.models import BreachEvent
from app.monitor import incidents
from tests.monitor_fixtures import CATALOG, CHATTER, SHOPCO, breach

BY_NAME = {b["Name"]: b for b in CATALOG}


def test_html_descriptions_become_plain_text_and_links():
    markup = BY_NAME["ShopCo"]["Description"]
    text = incidents.plain_text(markup)
    assert "<" not in text and "&amp;" not in text
    assert "ShopCo had 120,000 accounts exposed" in text and "reset their passwords & enable 2FA" in text
    assert incidents.description_links(markup) == ["https://news.example/shopco"]
    assert incidents.description_links('<a href="javascript:alert(1)">x</a>') == []


def test_breaches_match_by_domain_or_by_exact_name():
    assert incidents.matches_company(BY_NAME["ShopCo"], SHOPCO)
    assert incidents.matches_company(BY_NAME["ShopCo2023"], SHOPCO)
    assert not incidents.matches_company(BY_NAME["OtherSite"], SHOPCO)
    # "Chatter.link" is another site: a different domain wins over a similar name.
    assert not incidents.matches_company(BY_NAME["ChatterLink"], CHATTER)
    # No domain: the title has to be the company's name.
    assert incidents.matches_company(BY_NAME["ChatterForum"], CHATTER)
    assert not incidents.matches_company(breach("X", title="Chatter.link"), CHATTER)
    # Short names only match exactly ("AB" must not match "AB Testing").
    short = {"id": "ab", "name": "AB", "domains": ["ab.example"]}
    assert incidents.matches_company(breach("AB1", title="AB"), short)
    assert not incidents.matches_company(breach("AB2", title="AB Testing"), short)
    assert incidents.matches_company(breach("SC", title="ShopCo (South Region)"), SHOPCO)


def test_hibp_facts_keep_sources_dates_and_never_the_remote_logo():
    facts = incidents.hibp_facts(BY_NAME["ShopCo"], SHOPCO, "hibp_catalog")
    assert facts["id"] == "hibp-shopco" and facts["company_id"] == "shopco"
    assert facts["categories"] == ["password", "email"]  # most severe first
    assert [d["kind"] for d in facts["dates"]] == ["occurred", "added_to_hibp"]
    assert facts["dates"][0] == {
        "kind": "occurred",
        "date": "2021-03-04",
        "source": "Have I Been Pwned (breach date)",
        "source_url": "https://haveibeenpwned.com/Breach/ShopCo",
    }
    hibp_source, linked = facts["sources"]
    assert hibp_source["kind"] == "hibp" and hibp_source["official"] is True  # verified in HIBP
    assert linked["url"] == "https://news.example/shopco" and linked["official"] is False
    assert "logos.example" not in json.dumps(facts)  # the UI never loads remote images


def test_retired_breaches_are_skipped_and_bad_dates_are_unknown():
    assert incidents.hibp_facts(breach("Old", retired=True), None, "hibp_catalog") is None
    facts = incidents.hibp_facts(breach("Odd", date="not a date"), None, "hibp_catalog")
    assert [d["kind"] for d in facts["dates"]] == ["added_to_hibp"]


def test_official_disclosure_links_and_government_sites_count_as_official():
    facts = incidents.hibp_facts(breach("ShopCo", domain="shopco.example", disclosure="https://shopco.example/notice"), SHOPCO, "x")
    assert any(s["url"] == "https://shopco.example/notice" and s["official"] for s in facts["sources"])
    assert incidents.is_official_host("https://oag.state.gov/breach/123", [])
    assert not incidents.is_official_host("https://news.example/x", ["shopco.example"])


def _event(date, kind="occurred", source_kind="news", types=("email",), url="https://news.example/a"):
    return BreachEvent(company_id="shopco", company="ShopCo", date=date, date_kind=kind,
                       data_types=list(types), source_url=url, source_kind=source_kind, summary="ShopCo was breached.")


def test_news_facts_have_stable_ids_and_mapped_data_types():
    facts = incidents.news_facts(_event("2021-03", types=("ssn", "email")), SHOPCO)
    assert facts["id"] == "news-shopco-2021"
    assert incidents.news_facts(_event("2021-11"), SHOPCO)["id"] == "news-shopco-2021"
    assert facts["categories"] == ["government_id", "email"]
    assert facts["data_classes"] == ["Social security numbers", "Email addresses"]
    ag = incidents.news_facts(_event("2021", source_kind="ag_notice", url="https://ag.example/n"), SHOPCO)
    assert ag["sources"][0]["official"] and ag["sources"][0]["kind"] == "ag_notice"
    undated = incidents.news_facts(_event(None, kind="unknown"), SHOPCO)
    assert undated["id"].startswith("news-shopco-") and undated["dates"] == []


def test_news_reports_fold_into_the_hibp_breach_they_describe():
    hibp = [incidents.hibp_facts(BY_NAME[n], SHOPCO, "hibp_catalog") for n in ("ShopCo", "ShopCo2023")]
    same_year = incidents.news_facts(_event("2021-03-05", url="https://news.example/2021"), SHOPCO)
    announced_later = incidents.news_facts(_event("2024-02", kind="disclosed", url="https://ag.example/2024", source_kind="ag_notice"), SHOPCO)
    unrelated = incidents.news_facts(_event("2016", url="https://news.example/2016"), SHOPCO)
    merged = {f["id"]: f for f in incidents.merge_news(hibp, [same_year, announced_later, unrelated])}

    assert set(merged) == {"hibp-shopco", "hibp-shopco2023", "news-shopco-2016"}
    assert merged["hibp-shopco"]["aliases"] == ["news-shopco-2021"]
    assert "https://news.example/2021" in [s["url"] for s in merged["hibp-shopco"]["sources"]]
    # Disclosed in 2024: within two years of the 2023 breach, not the 2021 one.
    assert merged["hibp-shopco2023"]["aliases"] == ["news-shopco-2024"]
    assert merged["hibp-shopco2023"]["origin"] == ["hibp_catalog", "news"]


def test_absorb_combines_without_duplicates():
    a = incidents.hibp_facts(BY_NAME["ShopCo"], SHOPCO, "hibp_catalog")
    twice = incidents.absorb(incidents.absorb(a, a | {"id": "other"}), a | {"id": "other"})
    assert len(twice["sources"]) == len(a["sources"]) and twice["aliases"] == ["other"]
