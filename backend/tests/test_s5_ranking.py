"""Stage 5 tests: every rule in the tier table. Pure, no network."""

from app.models import AliasHit, BreachEvent, Exposure, FieldFinding, PolicyClause, PolicyResult
from app.stages.s5_ranking import rank_sources

LISTING = Exposure(
    id="e1", broker="PeopleFinder", url="https://www.peoplefinder.example/jane-example",
    fields=[FieldFinding(field="address", quote="12 Elm St"), FieldFinding(field="age", quote="34"),
            FieldFinding(field="name", quote="Jane Example")],
    public_by="2024-01-10", public_by_source="wayback",
)


def _breach(date, types=("address",), company="ShopCo", kind="occurred", source="ag_notice"):
    return BreachEvent(company_id=company.lower(), company=company, date=date, date_kind=kind,
                       data_types=list(types), source_url=f"https://oag.ca.gov/{company}-{date}", source_kind=source)


def _leads(breaches=(), policies=(), hits=(), exposure=LISTING):
    [ranked] = rank_sources([exposure], list(breaches), list(policies), list(hits))
    return ranked.leads


def test_likely_needs_timing_and_a_shared_field():
    assert [lead.tier for lead in _leads([_breach("2023-03-03")])] == ["likely"]
    assert _leads([_breach("2020-12-31")]) == []  # more than 3 years before
    assert _leads([_breach("2024-02-01")]) == []  # after the listing was public
    assert _leads([_breach("2024")]) == []  # might be after the listing: can't tell
    assert _leads([_breach("2023", types=("password",))]) == []  # nothing the listing shows
    assert _leads([_breach("2023", types=("name",))]) == []  # names alone don't count
    assert [lead.tier for lead in _leads([_breach("2023", types=("birthdate",))])] == ["likely"]  # age ~ birthdate


def test_unknown_dates_cant_support_likely():
    assert _leads([_breach(None, kind="unknown")]) == []
    undated_listing = LISTING.model_copy(update={"public_by": None, "public_by_source": "unknown"})
    assert _leads([_breach("2023-03-03")], exposure=undated_listing) == []


def test_reasons_cite_dates_and_sources():
    [lead] = _leads([_breach("2023-03-03")])
    reason = lead.reasons[0]
    assert "2023-03-03" in reason and "state attorney general notice" in reason
    assert "2024-01-10" in reason and "Wayback" in reason
    assert lead.source_urls == ["https://oag.ca.gov/ShopCo-2023-03-03"]


def test_possible_from_a_policy_that_allows_selling():
    policy = PolicyResult(company_id="adco", company="AdCo", policy_url="https://adco.example/privacy",
                          clauses=[PolicyClause(category="sale", quote="We sell it.", explanation="x")])
    [lead] = _leads(policies=[policy])
    assert lead.tier == "possible" and "selling personal information" in lead.reasons[0]
    assert _leads(policies=[policy.model_copy(update={"clauses": []})]) == []


def test_proven_only_when_the_alias_mail_came_from_this_listings_site():
    hit = AliasHit(alias="shopco.3f9a1c@alias.local", company="ShopCo", from_address="offers@peoplefinder.example",
                   from_domain="peoplefinder.example", subject="Hi", date="2026-08-21")
    [lead] = _leads(hits=[hit])
    assert lead.tier == "proven" and "shopco.3f9a1c@alias.local" in lead.reasons[0]
    other_site = hit.model_copy(update={"from_domain": "leadgen.example"})
    assert _leads(hits=[other_site]) == []


def test_one_lead_per_company_at_its_strongest_tier_with_all_reasons():
    hit = AliasHit(alias="a@alias.local", company="ShopCo", from_address="x@peoplefinder.example",
                   from_domain="peoplefinder.example", subject="Hi")
    policy = PolicyResult(company_id="shopco", company="ShopCo",
                          clauses=[PolicyClause(category="sharing", quote="q", explanation="x")])
    other = PolicyResult(company_id="adco", company="AdCo",
                         clauses=[PolicyClause(category="sale", quote="q", explanation="x")])
    leads = _leads([_breach("2023-03-03")], [policy, other], [hit])
    assert [(lead.company, lead.tier, len(lead.reasons)) for lead in leads] == [("ShopCo", "proven", 3), ("AdCo", "possible", 1)]


def test_wording_never_accuses():
    hit = AliasHit(alias="a@alias.local", company="ShopCo", from_address="x@peoplefinder.example",
                   from_domain="peoplefinder.example", subject="Hi")
    policy = PolicyResult(company_id="shopco", company="ShopCo",
                          clauses=[PolicyClause(category="data_broker", quote="q", explanation="x")])
    for lead in _leads([_breach("2023-03-03")], [policy], [hit]):
        assert all("leak" not in reason.lower() for reason in lead.reasons)
