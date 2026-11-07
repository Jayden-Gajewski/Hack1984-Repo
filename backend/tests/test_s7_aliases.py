"""Stage 7 tests: the mock inbox match (pure), alias creation, and the routes. Offline:
Postgres is stubbed (see conftest.py)."""

import asyncio
import re

import pytest

from app import db
from app.models import Alias
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
    monkeypatch.setattr(db, "save_alias", lambda alias, company, domains: saved.update(alias=alias) or "2026-11-07")
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
