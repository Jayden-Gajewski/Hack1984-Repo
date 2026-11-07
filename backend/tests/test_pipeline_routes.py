"""The demo flow through the real routes: scan -> accounts -> inbox check -> leads. Stages 1-4
are replaced with fixtures here (they have their own tests); Stages 5 and 7 run for real."""

from app import main
from app.models import BreachEvent, Exposure, FieldFinding, PolicyClause, PolicyResult

PERSON = {"name": "Jane Example", "city": "Springfield", "state": "IL", "consent": True}
SHOPCO = {"id": "shopco", "name": "ShopCo", "domains": ["shopco.example"], "privacy_url": None}
# A listing on the site that mailed the ShopCo-only alias in data/mock_inbox.json.
LISTING = Exposure(
    id="e1", broker="LeadGen Partners", url="https://leadgen-partners.example/people/jane-example",
    fields=[FieldFinding(field="email", quote="j***@example.com")],
    public_by="2026-09-01", public_by_source="wayback",
)


def test_demo_flow_ranks_shopco_as_proven(client, monkeypatch):
    async def find(req):
        return [LISTING], []

    async def date(exposures):
        return exposures, []

    async def breaches(ids):
        return [BreachEvent(company_id="shopco", company="ShopCo", date="2026-03", date_kind="disclosed",
                            data_types=["email"], source_url="https://news.example/shopco", source_kind="news")], []

    async def policies(ids):
        return [PolicyResult(company_id="shopco", company="ShopCo", policy_url="https://shopco.example/privacy",
                             clauses=[PolicyClause(category="sale", quote="We sell it.", explanation="x")])], []

    monkeypatch.setattr(main.s1_exposures, "find_exposures", find)
    monkeypatch.setattr(main.s2_dating, "date_exposures", date)
    monkeypatch.setattr(main.s3_breaches, "breach_timelines", breaches)
    monkeypatch.setattr(main.s4_policy, "check_policies", policies)
    monkeypatch.setattr(main, "all_companies", lambda: [SHOPCO])

    assert client.post("/api/scan", json=PERSON).status_code == 200
    accounts = client.post("/api/accounts", json={"companies": ["shopco"]}).json()
    assert accounts["errors"] == [] and accounts["policies"][0]["clauses"][0]["category"] == "sale"
    [hit] = client.get("/api/inbox/check").json()
    assert hit["from_domain"] == "leadgen-partners.example"

    leads = client.get("/api/leads").json()
    assert leads["errors"] == []
    [lead] = leads["exposures"][0]["leads"]
    assert (lead["company"], lead["tier"]) == ("ShopCo", "proven")
    assert len(lead["reasons"]) == 3  # proven, plus the likely and possible reasons behind it
