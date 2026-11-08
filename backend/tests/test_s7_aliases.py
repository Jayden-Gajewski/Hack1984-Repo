"""Stage 7 tests: the mock inbox match (pure), alias creation, and the routes. Offline:
Postgres is stubbed (see conftest.py)."""

import asyncio
import re

import pytest

from app import db
from app.models import Alias, normalize_site
from app.stages import s7_aliases as s7


def test_mock_inbox_has_one_proven_hit_and_skips_the_real_shopco_email():
    hits = s7.match_inbox(s7.load_mock_aliases(), s7.load_mock_inbox())
    assert [(h.company, h.from_domain, h.tier) for h in hits] == [("ShopCo", "leadgen-partners.example", "proven")]


def test_subdomains_of_the_company_are_legitimate():
    alias = Alias(alias="shopco.abc123@alias.local", company="ShopCo", company_domains=["shopco.example"], created_at="2026-01-01")
    messages = [
        {"to": "shopco.abc123@alias.local", "from": "news@mail.shopco.example", "subject": "Sale"},
        {"to": "SHOPCO.ABC123@alias.local", "from": "x@notshopco.example", "subject": "Hi"},
        {"to": "someone-else@alias.local", "from": "x@spam.example", "subject": "Hi"},
    ]
    assert [h.from_domain for h in s7.match_inbox([alias], messages)] == ["notshopco.example"]


def test_create_alias_uses_the_documented_format(monkeypatch):
    saved = {}
    monkeypatch.setattr(db, "save_alias", lambda alias, company, domains, site, label: saved.update(alias=alias) or "2026-11-07")
    alias = asyncio.run(s7.create_alias("linkedin"))
    assert re.fullmatch(r"linkedin\.[0-9a-f]{6}@alias\.local", alias.alias)
    assert alias.company_domains == ["linkedin.com"] and saved["alias"] == alias.alias


def test_unknown_company_and_database_down(monkeypatch):
    with pytest.raises(LookupError):
        s7.resolve_company("Nonexistent Corp")

    def down(*args):
        raise ConnectionError("refused")

    monkeypatch.setattr(db, "save_alias", down)
    with pytest.raises(RuntimeError, match="Postgres"):
        asyncio.run(s7.create_alias("ShopCo"))
    monkeypatch.setattr(db, "list_aliases", down)
    assert [a.company for a in asyncio.run(s7.list_aliases())] == ["ShopCo", "FitApp"]  # demo ones still work


def test_alias_routes(client):
    assert client.get("/api/inbox/check").json()[0]["tier"] == "proven"
    created = client.post("/api/aliases", json={"company": "ShopCo"})
    assert created.status_code == 200 and created.json()["alias"].startswith("shopco.")
    assert client.post("/api/aliases", json={"company": "Nonexistent Corp"}).status_code == 404
    assert len(client.get("/api/aliases").json()) == 2  # demo aliases (saved ones are stubbed out)


# ---------- identity manager ----------


def test_site_aliases_get_their_own_address_and_expected_senders(monkeypatch):
    saved = []
    monkeypatch.setattr(db, "save_alias", lambda *args: saved.append(args) or "2026-11-07")
    a = asyncio.run(s7.create_alias(site="shop.example", label="newsletter"))
    b = asyncio.run(s7.create_alias(site="shop.example"))
    assert re.fullmatch(r"shop\.[0-9a-f]{6}@alias\.local", a.alias) and a.alias != b.alias
    assert (a.company, a.company_domains, a.site, a.label) == ("shop.example", ["shop.example"], "shop.example", "newsletter")
    assert saved[0][3:] == ("shop.example", "newsletter")
    # A site owned by a listed company gets that company's domains.
    assert s7.resolve_site("www.linkedin.com".removeprefix("www.")) == ("LinkedIn", ["linkedin.com"])


def test_site_word():
    assert s7.site_word("shop.example") == "shop"
    assert s7.site_word("mail.shop.co.uk") == "shop"


def test_normalize_site_keeps_only_the_hostname():
    assert normalize_site("https://www.Shop.example/signup?email=a@b.co") == "shop.example"
    assert normalize_site("shop.example") == "shop.example"
    for bad in ("localhost", "not a site", "127.0.0.1", ""):
        with pytest.raises(ValueError):
            normalize_site(bad)


def test_alias_messages_marks_expected_unexpected_and_blocked():
    shopco = next(a for a in s7.load_mock_aliases() if a.company == "ShopCo")
    msgs = s7.alias_messages(shopco, s7.load_mock_inbox())
    assert [(m.from_domain, m.expected, m.blocked) for m in msgs] == [
        ("leadgen-partners.example", False, False),  # newest first
        ("shopco.example", True, False),
    ]
    disabled = shopco.model_copy(update={"status": "disabled", "disabled_at": "2026-08-01"})
    assert [m.blocked for m in s7.alias_messages(disabled, s7.load_mock_inbox())] == [True, False]
    counted = s7.with_inbox_counts(shopco, s7.load_mock_inbox())
    assert (counted.message_count, counted.unexpected_count, counted.last_message_at) == (2, 1, "2026-08-21")


def test_identity_manager_routes(client):
    listed = client.get("/api/aliases").json()
    shopco = next(a for a in listed if a["company"] == "ShopCo")
    assert shopco["demo"] and shopco["status"] == "active" and shopco["unexpected_count"] == 1
    address = shopco["alias"]

    off = client.patch(f"/api/aliases/{address}", json={"status": "disabled", "note": "spam from a lead seller"})
    assert off.status_code == 200
    assert (off.json()["status"], off.json()["disabled_at"], off.json()["note"]) == (
        "disabled", "2026-11-07", "spam from a lead seller",
    )
    assert next(a for a in client.get("/api/aliases").json() if a["alias"] == address)["status"] == "disabled"
    # Disabling doesn't erase the evidence: the hit is still Proven.
    assert client.get("/api/inbox/check").json()[0]["alias"] == address

    on = client.patch(f"/api/aliases/{address}", json={"status": "active"}).json()
    assert (on["status"], on["disabled_at"], on["note"]) == ("active", None, "spam from a lead seller")

    msgs = client.get(f"/api/aliases/{address}/messages").json()
    assert [m["expected"] for m in msgs] == [False, True]

    assert client.patch("/api/aliases/nobody.000000@alias.local", json={"status": "disabled"}).status_code == 404
    assert client.get("/api/aliases/nobody.000000@alias.local/messages").status_code == 404
    assert client.patch(f"/api/aliases/{address}", json={"status": "deleted"}).status_code == 422


def test_create_alias_route_validation(client):
    made = client.post("/api/aliases", json={"site": "https://www.shop.example/join", "label": "signup"})
    assert made.status_code == 200
    assert made.json()["site"] == "shop.example" and made.json()["alias"].startswith("shop.")
    assert client.post("/api/aliases", json={}).status_code == 422
    assert client.post("/api/aliases", json={"site": "localhost"}).status_code == 422


def test_saved_aliases_are_scoped_to_the_signed_in_account():
    """db.list_aliases and db.alias_states filter by the signed-in account (no Postgres here:
    check the SQL they run)."""
    import inspect

    assert "user_id is not distinct from %s" in inspect.getsource(db.list_aliases)
    assert "where user_id = %s" in inspect.getsource(db.alias_states)


def test_alias_routes_accept_a_url_encoded_address(client):
    """The frontend encodes the @ (encodeURIComponent)."""
    assert client.get("/api/aliases/shopco.3f9a1c%40alias.local/messages").status_code == 200


# ---------- investigate (Phase 2) ----------

from app import prompts  # noqa: E402
from app.clients import gemini  # noqa: E402


def _shopco():
    return next(a for a in s7.load_mock_aliases() if a.company == "ShopCo")


def test_investigation_facts_for_the_demo_alias():
    shopco = _shopco()
    result = s7.investigation_facts(shopco, s7.alias_messages(shopco, s7.load_mock_inbox()))
    assert result.tier == "proven"
    assert [(s.domain, s.kind, s.count, s.first_seen) for s in result.senders] == [
        ("leadgen-partners.example", "unknown", 1, "2026-08-21"),
    ]
    assert result.days_to_first_unexpected == 172  # 2026-03-02 -> 2026-08-21
    assert any("first on 2026-08-21 (date on the message)" in f for f in result.facts)
    assert all("leaked" not in f.lower() for f in result.facts)


def test_investigation_of_an_alias_with_only_expected_mail_needs_no_model(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("no model call when nothing is unexpected")

    monkeypatch.setattr(gemini, "ask_json", boom)
    fitapp = next(a for a in s7.load_mock_aliases() if a.company == "FitApp")
    monkeypatch.setattr(s7, "get_alias", lambda address: asyncio.sleep(0, fitapp))
    result = asyncio.run(s7.investigate(fitapp.alias))
    assert (result.tier, result.category, result.explanation) == (None, "legit", "")
    assert "All 1 messages came from FitApp's own domains." in result.facts


def test_known_senders_are_named_from_the_checked_in_lists():
    alias = Alias(alias="shop.aaaaaa@alias.local", company="Shop", company_domains=["shop.example"], created_at="2026-01-01")
    messages = s7.alias_messages(alias, [
        {"to": alias.alias, "from": "x@mail.spokeo.com", "subject": "Your report", "date": "2026-01-05"},
        {"to": alias.alias, "from": "y@linkedin.com", "subject": "Join", "date": "2026-01-03"},
    ])
    senders = s7.investigation_facts(alias, messages).senders
    assert [(s.domain, s.kind, s.name) for s in senders] == [
        ("linkedin.com", "known_company", "LinkedIn"),
        ("mail.spokeo.com", "data_broker", "Spokeo"),
    ]


def test_clean_explanation_drops_unsupported_sentences():
    facts = ["leadgen-partners.example wrote once, first on 2026-08-21 (date on the message).",
             "The first unexpected message came 172 days after the alias was made."]
    text = (
        "ShopCo is the likely source of this address. "
        "ShopCo sold your address to a lead seller. "            # certain, no hedge
        "This was leaked by ShopCo. "                            # banned wording
        "Over 5000 people got the same mail. "                   # number not in the facts
        "It arrived 172 days after you signed up. "
        "You could turn this alias off."
    )
    assert s7.clean_explanation(text, facts) == (
        "ShopCo is the likely source of this address. It arrived 172 days after you signed up. "
        "You could turn this alias off."
    )
    assert s7.clean_explanation(None, facts) == ""


def test_investigate_asks_gemini_and_checks_its_answer(monkeypatch):
    seen = {}

    async def fake_ask(prompt, *, system, purpose):
        seen.update(prompt=prompt, purpose=purpose)
        return {"category": "data_sharing", "explanation": "ShopCo may have shared your address. It was leaked by ShopCo."}

    monkeypatch.setattr(gemini, "ask_json", fake_ask)
    shopco = _shopco()
    monkeypatch.setattr(s7, "get_alias", lambda address: asyncio.sleep(0, shopco))
    result = asyncio.run(s7.investigate(shopco.alias))
    assert (result.category, result.explanation, result.explained_locally) == (
        "data_sharing", "ShopCo may have shared your address.", True,
    )
    # The model sees sender domains, never the alias or a full sender address.
    assert shopco.alias not in seen["prompt"] and "offers@" not in seen["prompt"]
    assert "leadgen-partners.example" in seen["prompt"] and seen["purpose"].startswith("Ask Gemini")


def test_investigate_rejects_an_unknown_or_legit_category_and_survives_a_silent_model(monkeypatch):
    shopco = _shopco()
    monkeypatch.setattr(s7, "get_alias", lambda address: asyncio.sleep(0, shopco))

    async def odd(prompt, *, system, purpose):
        return {"category": "legit", "explanation": 42}

    monkeypatch.setattr(gemini, "ask_json", odd)
    result = asyncio.run(s7.investigate(shopco.alias))
    assert (result.category, result.explanation, result.tier) == ("unknown", "", "proven")

    async def silent(prompt, *, system, purpose):
        return {}

    monkeypatch.setattr(gemini, "ask_json", silent)
    result = asyncio.run(s7.investigate(shopco.alias))
    assert result.facts and result.errors and result.tier == "proven"


def test_alias_prompt_truncates_subjects():
    prompt = prompts.alias_prompt("ShopCo", ["shopco.example"], ["fact"], [("2026-01-01", "x.example", "A" * 500)])
    assert "A" * prompts.MAX_SUBJECT_CHARS in prompt and "A" * (prompts.MAX_SUBJECT_CHARS + 1) not in prompt


def test_investigate_route(client, monkeypatch):
    async def fake_ask(prompt, *, system, purpose):
        return {"category": "marketing", "explanation": "This looks like marketing from another company."}

    monkeypatch.setattr(gemini, "ask_json", fake_ask)
    res = client.post("/api/aliases/shopco.3f9a1c%40alias.local/investigate")
    assert res.status_code == 200 and res.json()["tier"] == "proven" and res.json()["category"] == "marketing"
    assert client.post("/api/aliases/nobody.000000@alias.local/investigate").status_code == 404


# ---------- browser extension (Phase 4) ----------

EXT = {"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}


def test_extension_may_list_and_make_aliases_with_the_session(client):
    assert client.get("/api/aliases", headers=EXT).status_code == 200
    made = client.post("/api/aliases", json={"site": "shop.example"}, headers=EXT)
    assert made.status_code == 200 and made.json()["site"] == "shop.example"


def test_extension_origin_is_refused_everywhere_else(client):
    address = "shopco.3f9a1c@alias.local"
    assert client.patch(f"/api/aliases/{address}", json={"status": "disabled"}, headers=EXT).status_code == 403
    assert client.post(f"/api/aliases/{address}/investigate", headers=EXT).status_code == 403
    assert client.delete("/api/outbound-log", headers=EXT).status_code == 403
    assert client.post("/api/scan", json={"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True},
                       headers=EXT).status_code == 403
    # A web page's origin still can't make aliases.
    assert client.post("/api/aliases", json={"site": "shop.example"},
                       headers={"Origin": "https://evil.example"}).status_code == 403


def test_extension_still_needs_a_signed_in_session(client):
    client.cookies.clear()
    assert client.post("/api/aliases", json={"site": "shop.example"}, headers=EXT).status_code == 401
