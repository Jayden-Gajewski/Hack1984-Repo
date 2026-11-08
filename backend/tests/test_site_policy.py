"""Browser extension backend (app/site_policy.py and clients/website.py), against a fake site and
a fake Gemini. Nothing here touches the network."""

import asyncio
import json
import re

import httpx
import pytest

from app import outbound, site_policy
from app.clients import gemini, website
from app.companies import registrable
from app.models import AdSellers, BrokerMatch, PolicyClause, SitePolicyRequest
from app.stages import s4_policy as s4

ORIGIN = "https://www.shopco.example"
POLICY_URL = f"{ORIGIN}/legal/privacy"
FILLER = "This notice explains how ShopCo handles personal information. Please read it carefully. " * 12
POLICY_HTML = f"""<!doctype html><html><head><title>Privacy | ShopCo</title>
<script>var note = "We sell your personal information to data brokers.";</script>
<style>.hidden {{ display: none }}</style></head>
<body><nav><a href="/">Home</a> <a href="/cart">Cart</a></nav>
<main>
<h1>ShopCo Privacy Policy</h1>
<p>{FILLER}</p>
<h2>Information we collect</h2>
<p>We collect the following information:</p>
<ul><li>Contact information, such as your name and email address</li>
<li>Precise location from your phone&#39;s GPS</li>
<li>Payment card details</li></ul>
<p>We do not collect biometric data.</p>
<p>We receive information about you from data brokers and advertising partners.</p>
<h2>How we share information</h2>
<p>We sell your personal information to advertising partners for their own marketing.</p>
<p>We may disclose personal information to companies that help us market products.</p>
<p>We share your information with our affiliates to run and improve the Services.</p>
<p>We do not sell your personal information to anyone else for money.</p>
<p>You have the right to opt out of the sale of your personal information at any time.</p>
<h2>Children</h2>
<p>We do not knowingly collect information from children under the age of 13.</p>
</main></body></html>"""


ADS_TXT = """# ShopCo ads.txt
contact=ads@shopco.example
google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0
google.com, pub-1111111111111111, RESELLER, f08c47fec0942fa0
rubiconproject.com, 12345, RESELLER, 0bfd66d529a55807
spotxchange.com, 67890, RESELLER, 7842df1d2fe2db34
pubmatic.com, 156000, RESELLER # a comment
adnetwork.example, 1, DIRECT
this line is not a record
subdomain=shop.shopco.example
"""


def fake_web(request: httpx.Request, *, policy: httpx.Response | None = None) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "shopco.example" and path == "/ads.txt":  # ads.txt lives on the root domain
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, text=ADS_TXT)
    if host == "www.shopco.example":
        if path == "/privacy":
            return httpx.Response(301, headers={"Location": "/legal/privacy"})
        if path == "/legal/privacy":
            return policy or httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text=POLICY_HTML)
        return httpx.Response(404, text="Not found")
    if host == "generativelanguage.googleapis.com" and path.endswith(":generateContent"):  # Gemini
        prompt = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        guess = lambda s: "sale" if "sell" in s else "affiliates" if "affiliat" in s else "sharing"  # noqa: E731
        picks = [
            {"sentence": int(n), "category": guess(s), "explanation": "x"}
            for n, s in re.findall(r"^\[(\d+)\] (.*)$", prompt, re.M)
        ]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"clauses": picks})}]}}]})
    raise AssertionError(f"unexpected request: {request.url}")


def _use(monkeypatch, handler=fake_web):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(outbound, "_client", client)
    monkeypatch.setattr(outbound, "_site_client", client)  # website fetches use their own client
    monkeypatch.setattr(gemini, "_generate_slots", asyncio.Semaphore(1))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    from app.config import get_settings

    get_settings.cache_clear()
    outbound.clear_log()


@pytest.fixture(autouse=True)
def _fresh_cache():
    site_policy.reset()
    website._slots = None  # a semaphore must not outlive the event loop it was used in
    yield
    site_policy.reset()
    website._slots = None


def _req(**kwargs) -> SitePolicyRequest:
    return SitePolicyRequest(origin=ORIGIN, **kwargs)


def _check(**kwargs):
    return asyncio.run(site_policy.check_site(_req(**kwargs)))


# ---------- which links get opened ----------


@pytest.mark.parametrize("url,expected", [
    ("https://www.shopco.example/privacy", "https://www.shopco.example/privacy"),
    ("http://shopco.example/privacy?ref=footer#top", "https://shopco.example/privacy"),  # upgraded, query dropped
    ("https://shopco.example", "https://shopco.example/"),
    ("https://localhost/privacy", None),
    ("https://127.0.0.1/privacy", None),
    ("https://127.1/privacy", None),  # shorthand for 127.0.0.1
    ("https://10.0.0.5/privacy", None),
    ("https://[::1]/privacy", None),
    ("https://router/privacy", None),
    ("https://printer.local/privacy", None),
    ("https://user:pw@shopco.example/privacy", None),
    ("https://shopco.example:8443/privacy", None),
    ("ftp://shopco.example/privacy", None),
    ("javascript:alert(1)", None),
])
def test_public_https(url, expected):
    assert website.public_https(url) == expected


def test_html_to_text_skips_scripts_and_keeps_blocks():
    text = website.html_to_text(POLICY_HTML)
    assert "var note" not in text and "Privacy | ShopCo" not in text and "display: none" not in text
    assert "Precise location from your phone's GPS" in text.splitlines()


# ---------- the quick pass ----------


def test_quick_check_reads_the_policy_straight_from_the_site(monkeypatch):
    _use(monkeypatch)
    res = _check(policy_urls=[f"{ORIGIN}/privacy?ref=footer"], opt_out_url=f"{ORIGIN}/do-not-sell")

    assert (res.site, res.status, res.read_from, res.llm) == ("shopco.example", "ok", "site", "off")
    assert res.policy_url == POLICY_URL  # the redirect was followed
    assert [c.category for c in res.collected] == ["contact", "precise_location", "financial", "from_others"]
    assert [c.category for c in res.clauses] == ["sale", "affiliates"]  # the script's text never counted
    assert res.no_sale_quote.startswith("We do not sell")
    assert res.risk == "high"
    assert [r.title for r in res.risks] == [
        "It may sell your personal information",
        "It collects sensitive data",
        "It gets data about you from other companies",
        "It shows a “Do Not Sell or Share” link",
        "It shares data within its corporate family",
    ]
    assert res.summary.startswith("Main risk: it may sell your personal information.")
    assert "leak" not in res.model_dump_json().lower()

    # Only the site itself was contacted: no search API, no Gemini call in the quick pass, no query string.
    log = outbound.get_log()
    assert {e.service for e in log} == {"website"}
    assert {httpx.URL(e.url).host for e in log} == {"www.shopco.example"}
    assert not any("ref=footer" in e.url for e in log)


def test_deep_pass_runs_gemini_in_the_background(monkeypatch):
    _use(monkeypatch)

    async def run():
        first = await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))
        await site_policy._cache["shopco.example"].task
        return first, await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))

    first, done = asyncio.run(run())
    assert first.llm == "running" and done.llm == "done"
    # The model found a sharing sentence the strict pattern misses; its other picks failed the checks.
    assert [c.category for c in done.clauses] == ["sale", "sharing", "affiliates"]
    assert "It shares your data with other companies" in [r.title for r in done.risks]
    # Its free-text explanations ("x") are replaced by fixed wording, and the policy text is dropped.
    assert all(c.explanation == s4.DEFAULT_EXPLANATION[c.category] for c in done.clauses)
    assert site_policy._cache["shopco.example"].sentences == []
    # Opening the popup also read the site's ads.txt.
    assert first.ad_sellers.status == "running"
    assert (done.ad_sellers.status, done.ad_sellers.count) == ("done", 4)
    log = outbound.get_log()
    assert [e.url for e in log if e.service == "website"] == [POLICY_URL, "https://shopco.example/ads.txt"]
    assert all(e.headers["x-goog-api-key"] == "REDACTED" for e in log if e.service == "gemini")
    for entry in log:
        if entry.service != "gemini":
            assert "data brokers" not in json.dumps(entry.body)  # policy text goes only to Gemini


def test_browser_text_never_leaves_the_laptop(monkeypatch):
    _use(monkeypatch)
    text = website.html_to_text(POLICY_HTML)
    first = _check(page_text=text, policy_urls=[POLICY_URL])
    again = _check(page_text=text, policy_urls=[POLICY_URL])

    assert (first.status, first.read_from, first.policy_url) == ("ok", "browser", POLICY_URL)
    assert first.risk == "high"
    assert again.checked_at == first.checked_at  # the same text is checked once
    assert outbound.get_log() == []


def test_a_page_that_isnt_a_policy_keeps_the_sites_result(monkeypatch):
    _use(monkeypatch)
    good = _check(policy_urls=[POLICY_URL])
    wrong = _check(page_text="Welcome to ShopCo! Shop our new arrivals.", policy_urls=[f"{ORIGIN}/"])
    assert (wrong.status, wrong.read_from) == ("unreadable", None)
    assert "This page doesn't look like a privacy policy." in wrong.errors
    assert _check(policy_urls=[POLICY_URL]).checked_at == good.checked_at


# ---------- when the policy can't be read ----------


def test_redirect_off_the_public_web_is_refused(monkeypatch):
    def handler(request):
        if request.url.host == "www.shopco.example":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/api/scans/latest"})
        raise AssertionError(f"unexpected request: {request.url}")

    _use(monkeypatch, handler)
    res = _check(policy_urls=[POLICY_URL])
    assert (res.status, res.risk) == ("unreadable", None)
    assert any("wasn't followed" in e for e in res.errors)
    assert {httpx.URL(e.url).host for e in outbound.get_log()} == {"www.shopco.example"}


def test_blocked_policy_is_unreadable(monkeypatch):
    _use(monkeypatch, lambda r: fake_web(r, policy=httpx.Response(403, text="Forbidden")))
    res = _check(policy_urls=[POLICY_URL])
    assert (res.status, res.risk, res.policy_url) == ("unreadable", None, POLICY_URL)
    assert "www.shopco.example answered HTTP 403." in res.errors


def test_page_that_needs_javascript_is_unreadable(monkeypatch):
    shell = httpx.Response(200, headers={"Content-Type": "text/html"}, text="<div id=root></div><script>app()</script>")
    _use(monkeypatch, lambda r: fake_web(r, policy=shell))
    res = _check(policy_urls=[POLICY_URL])
    assert res.status == "unreadable"
    assert any("JavaScript" in e for e in res.errors)


def test_no_policy_link_tries_the_usual_paths(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(404, text="Not found"))
    res = _check()
    assert (res.status, res.risk) == ("no_policy", None)
    assert [httpx.URL(e.url).path for e in outbound.get_log()] == ["/privacy-policy", "/privacy"]


def test_a_new_link_retries_a_site_that_had_none(monkeypatch):
    _use(monkeypatch)
    assert _check().status == "ok"  # no link on the page, but /privacy redirects to the policy
    site_policy.reset()
    _use(monkeypatch, lambda r: httpx.Response(404, text="Not found"))
    assert _check().status == "no_policy"
    _use(monkeypatch)
    assert _check(policy_urls=[POLICY_URL]).status == "ok"


# ---------- reading what's collected ----------


def test_collected_data_reads_bullets_and_skips_denials():
    text = "\n".join([
        "Personal Information We Collect",
        "Device information",
        "Your IP address and browser type",
        "Contact information",
        "Your email address",
        "We do not collect the following:",
        "Biometric data such as fingerprints",
        "How We Use Your Information",
        "Some partner sites ask for your date of birth.",  # not the company's voice, outside the section
        "We may collect your health information when you use our fitness features.",
    ])
    found = {c.category: c for c in site_policy.collected_data(text, "shopco")}
    assert list(found) == ["contact", "identifiers", "health"]
    assert found["identifiers"].section == "Personal Information We Collect"
    assert found["health"].section == ""  # a sentence in the company's voice, outside the section


def test_precise_location_is_not_also_plain_location_and_videos_need_to_be_yours():
    text = "Information We Collect\nPrecise Location Data\nA short video about how we process your data"
    assert [c.category for c in site_policy.collected_data(text, "shopco")] == ["precise_location"]


def test_disclosure_the_law_requires_is_not_sharing():
    legal = PolicyClause(
        category="sharing", explanation="x",
        quote="We may share your personal data to comply with a request from courts or other authorized third parties.",
    )
    ads = PolicyClause(
        category="sharing", explanation="x",
        quote="We share personal data with advertising partners and, where required by law, with courts.",
    )
    assert site_policy.not_legal_only([legal, ads]) == [ads]


def test_route_rejects_this_computer_and_bad_origins(client):
    assert client.post("/api/site-policy", json={"origin": "http://localhost:3000"}).status_code == 400
    assert client.post("/api/site-policy", json={"origin": "https://192.168.1.1"}).status_code == 400
    assert client.post("/api/site-policy", json={"origin": "ftp://shopco.example"}).status_code == 422


def test_route_answers_the_extension_but_not_web_pages(client):
    body = {"origin": "http://localhost:3000"}  # refused before any fetch either way
    from_page = client.post("/api/site-policy", json=body, headers={"Origin": "https://evil.example"})
    from_extension = client.post("/api/site-policy", json=body, headers={"Origin": "chrome-extension://abcdef"})
    assert (from_page.status_code, from_extension.status_code) == (403, 400)


# ---------- only the visited site is contacted ----------


def test_policy_links_to_other_sites_are_not_fetched(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(404, text="Not found") if r.url.host == "www.shopco.example" else fake_web(r))
    res = _check(policy_urls=["https://policies.adnetwork.example/privacy"])
    assert (res.status, res.policy_url) == ("unreadable", "https://policies.adnetwork.example/privacy")
    assert any("another site (policies.adnetwork.example)" in e for e in res.errors)
    assert {httpx.URL(e.url).host for e in outbound.get_log()} == {"www.shopco.example"}  # only the usual paths


def test_a_redirect_to_another_site_is_not_followed(monkeypatch):
    def handler(request):
        if request.url.host == "www.shopco.example":
            return httpx.Response(302, headers={"Location": "https://tracker.adnetwork.example/policy"})
        raise AssertionError(f"unexpected request: {request.url}")

    _use(monkeypatch, handler)
    res = _check(policy_urls=[POLICY_URL])
    assert res.status == "unreadable"
    assert "The policy is on another site (tracker.adnetwork.example), so it wasn't opened automatically." in res.errors


def test_a_redirect_to_the_home_page_is_not_a_policy(monkeypatch):
    home = "<p>Welcome to ShopCo.</p>" + "<p>New arrivals every week, with free shipping on orders over $50.</p>" * 40
    home += '<footer><a href="/privacy">Privacy Policy</a></footer>'

    def handler(request):
        if request.url.path == "/privacy":
            return httpx.Response(301, headers={"Location": "/"})
        if request.url.path == "/":
            return httpx.Response(200, headers={"Content-Type": "text/html"}, text=home)
        return httpx.Response(404, text="Not found")

    _use(monkeypatch, handler)
    assert _check().status == "no_policy"
    assert not site_policy.looks_like_policy(website.html_to_text(home))
    assert site_policy.looks_like_policy(website.html_to_text(POLICY_HTML))


def test_only_the_sites_own_opt_out_link_counts_as_evidence(monkeypatch):
    _use(monkeypatch)
    res = _check(policy_urls=[POLICY_URL], opt_out_url="https://evil.example/do-not-sell")
    assert res.opt_out_url is None  # never offered as the opt-out button either
    assert "It shows a “Do Not Sell or Share” link" not in [r.title for r in res.risks]


def test_page_text_must_come_from_the_site_being_checked(monkeypatch):
    _use(monkeypatch)
    with pytest.raises(site_policy.CantCheck):
        _check(page_text=website.html_to_text(POLICY_HTML), policy_urls=["https://evil.example/privacy"])


def test_sites_on_a_shared_host_are_kept_apart(monkeypatch):
    assert registrable("alice.github.io") == "alice.github.io"
    _use(monkeypatch)
    text = website.html_to_text(POLICY_HTML)
    alice = asyncio.run(site_policy.check_site(SitePolicyRequest(
        origin="https://alice.github.io", page_text=text, policy_urls=["https://alice.github.io/privacy"],
    )))
    bob = asyncio.run(site_policy.check_site(SitePolicyRequest(origin="https://bob.github.io")))
    assert (alice.site, alice.status) == ("alice.github.io", "ok")
    assert (bob.site, bob.status) == ("bob.github.io", "no_policy")  # alice's policy isn't bob's


# ---------- what the page itself does ----------


def test_tracker_list_is_well_formed():
    data = site_policy._tracker_data()
    categories = set(site_policy.TRACKER_ORDER)
    ids = [t["id"] for t in data["trackers"]]
    domains = [d for t in data["trackers"] for d in t["domains"]]
    assert len(ids) == len(set(ids)) and len(domains) == len(set(domains))
    for tracker in data["trackers"]:
        assert set(tracker) == {"id", "name", "company", "category", "domains"}
        assert tracker["category"] in categories
        assert all(d == d.lower() and "." in d and "/" not in d for d in tracker["domains"])
    assert {t["company"] for t in data["trackers"]} >= set(data["owners"])  # owners name real tracker companies
    assert all(k == k.lower() for k in data["ad_systems"])


def test_only_bare_hostnames_and_fixed_field_kinds_are_accepted():
    req = SitePolicyRequest(origin=ORIGIN, third_party_hosts=[
        "connect.facebook.net",
        "https://www.facebook.com/tr?id=1&em=jane%40mail.example",  # a URL: its details are dropped with it
        "jane@mail.example",
        "CDN.Example.COM.",
        "two words.example",
        "localhost",
    ])
    assert req.third_party_hosts == ["connect.facebook.net", "cdn.example.com"]
    with pytest.raises(ValueError):
        SitePolicyRequest(origin=ORIGIN, asks_for=["email", "whatever was typed in the field"])


def test_trackers_and_form_fields_are_judged_without_any_request(monkeypatch):
    _use(monkeypatch)
    res = _check(
        page_text=website.html_to_text(POLICY_HTML), policy_urls=[POLICY_URL],
        third_party_hosts=["www.googletagmanager.com", "connect.facebook.net", "static.hotjar.com", "cdn.shopco.example"],
        asks_for=["email", "ssn"],
    )
    assert [(t.name, t.category, t.hosts) for t in res.trackers] == [
        ("Hotjar", "session_recording", ["static.hotjar.com"]),
        ("Meta (Facebook)", "advertising", ["connect.facebook.net"]),
        ("Google Tag Manager", "tag_manager", ["www.googletagmanager.com"]),
    ]  # the site's own cdn.shopco.example isn't a tracker
    risks = {r.title: r for r in res.risks}
    assert risks["It loads a session-recording tool"].evidence == ["static.hotjar.com"]
    assert risks["It loads a session-recording tool"].level == "medium"  # what it can do, not what it did
    assert "It sends your visit to ad companies" in risks
    assert risks["It asks for your Social Security number"].evidence == ["Social Security number field"]
    assert outbound.get_log() == []  # nothing was fetched for any of it


def test_no_policy_is_a_risk_only_when_the_page_collects_something(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(404, text="Not found"))
    quiet = _check()
    assert (quiet.status, quiet.risk, quiet.risks) == ("no_policy", None, [])
    tracked = _check(third_party_hosts=["connect.facebook.net"])
    no_policy = next(r for r in tracked.risks if r.title == "Couldn't find a privacy policy")
    assert no_policy.level == "medium" and "sends your visit to Meta" in no_policy.detail
    assert tracked.summary == "Couldn't find this site's privacy policy. Main risk: it sends your visit to ad companies."
    card = _check(asks_for=["card"])
    assert (card.risk, card.risks[0].title) == ("high", "Couldn't find a privacy policy")


def test_a_policy_that_couldnt_be_read_is_not_called_missing(monkeypatch):
    _use(monkeypatch, lambda r: fake_web(r, policy=httpx.Response(403, text="Forbidden")))
    res = _check(policy_urls=[POLICY_URL], asks_for=["card"])
    assert res.status == "unreadable"
    assert "Couldn't find a privacy policy" not in [r.title for r in res.risks]


def test_sensitive_fields_on_a_page_without_https(monkeypatch):
    _use(monkeypatch)
    res = asyncio.run(site_policy.check_site(SitePolicyRequest(
        origin="http://www.shopco.example", policy_urls=[POLICY_URL], asks_for=["password"], insecure_fields=["password"],
    )))
    insecure = next(r for r in res.risks if r.title == "It asks for your password without encryption")
    assert (insecure.level, insecure.evidence) == ("high", ["password field"])


def test_people_search_sites_come_from_the_checked_in_list():
    assert site_policy.broker_for("spokeo.com").name == "Spokeo"
    assert site_policy.broker_for("shopco.example") is None
    [risk] = site_policy.page_risks("ok", [], [], [], site_policy.broker_for("spokeo.com"), None)
    assert risk.title == "It publishes profiles of people" and "Check whether it lists you" in risk.detail


def test_ads_txt_records_are_counted_by_company():
    assert site_policy.ad_sellers(ADS_TXT) == (4, ["Google", "Magnite", "PubMatic", "adnetwork.example"])
    assert site_policy.ad_sellers("<html>Not found</html>") == (0, [])


def test_ads_txt_is_read_only_when_the_popup_asks(monkeypatch):
    _use(monkeypatch)
    quick = _check(policy_urls=[POLICY_URL])
    assert quick.ad_sellers is None
    assert not any(e.url.endswith("/ads.txt") for e in outbound.get_log())


def test_a_sites_ads_txt_is_read_once(monkeypatch):
    _use(monkeypatch)
    text = website.html_to_text(POLICY_HTML)

    async def run():
        await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))
        await site_policy._cache["shopco.example"].task
        # The policy page itself is opened later: a new result for the same site.
        await site_policy.check_site(_req(page_text=text, policy_urls=[POLICY_URL], deep=True))
        await site_policy._cache["shopco.example"].task
        return await site_policy.check_site(_req(policy_urls=[POLICY_URL]))

    res = asyncio.run(run())
    assert (res.read_from, res.ad_sellers.count) == ("browser", 4)
    assert len([e for e in outbound.get_log() if e.url.endswith("/ads.txt")]) == 1


def test_an_ads_txt_on_another_site_is_not_followed(monkeypatch):
    def handler(request):
        if request.url.path == "/ads.txt":
            return httpx.Response(301, headers={"Location": "https://adstxt.manager.example/shopco"})
        return fake_web(request)

    _use(monkeypatch, handler)

    async def run():
        await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))
        await site_policy._cache["shopco.example"].task
        return await site_policy.check_site(_req(policy_urls=[POLICY_URL]))

    res = asyncio.run(run())
    assert res.ad_sellers.status == "failed"
    assert "adstxt.manager.example" not in {httpx.URL(e.url).host for e in outbound.get_log()}


# ---------- how a page is fetched ----------


def test_site_fetches_send_no_cookies_read_a_capped_body_and_keep_their_own_log(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers.get("cookie"))
        if request.url.path == "/privacy":
            return httpx.Response(301, headers={"Location": "/legal/privacy", "Set-Cookie": "track=1; Path=/"})
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, text="x" * 50_000)

    _use(monkeypatch, handler)
    monkeypatch.setattr(website, "MAX_BYTES", 5_000)
    _, text = asyncio.run(website.read_page(f"{ORIGIN}/privacy", purpose="test"))
    assert seen == [None, None]  # the cookie the site set was never sent back
    assert len(text) == 5_000
    assert len(outbound._site_log) == 2 and not outbound._log


def test_a_fetch_that_runs_out_of_time_is_logged_as_cancelled(monkeypatch):
    async def slow(request):
        await asyncio.sleep(5)

    _use(monkeypatch, slow)
    monkeypatch.setattr(website, "TOTAL_SECONDS", 0.05)
    with pytest.raises(website.PageError, match="took too long"):
        asyncio.run(website.read_page(POLICY_URL, purpose="test"))
    assert outbound.get_log()[0].error == "Cancelled: it took too long."


# ---------- the second privacy review ----------


def test_the_automatic_check_contacts_no_site(monkeypatch):
    _use(monkeypatch)
    first = _check(policy_urls=[POLICY_URL], read_policy=False, third_party_hosts=["connect.facebook.net"])
    assert (first.status, first.risk) == ("not_read", "medium")  # the tracker alone
    assert outbound.get_log() == []
    _check(policy_urls=[POLICY_URL])  # the user opens the popup: now the policy is read
    again = _check(policy_urls=[POLICY_URL], read_policy=False)
    assert (again.status, again.read_from) == ("ok", "site")  # reused, not fetched again
    assert len(outbound.get_log()) == 1


def test_stacked_compression_is_refused_and_one_layer_is_capped(monkeypatch):
    import gzip

    bomb = gzip.compress(b"a" * 20_000_000)  # 20 MB of text in about 20 KB

    async def chunks(data):  # streamed like a real download, so the capped decoder does the work
        for i in range(0, len(data), 4096):
            yield data[i:i + 4096]

    def handler(request):
        encoding = "gzip, gzip" if request.url.path == "/stacked" else "gzip"
        body = gzip.compress(bomb) if request.url.path == "/stacked" else bomb
        return httpx.Response(200, headers={"Content-Type": "text/plain", "Content-Encoding": encoding}, content=chunks(body))

    _use(monkeypatch, handler)
    with pytest.raises(website.PageError):
        asyncio.run(website.read_page(f"{ORIGIN}/stacked", purpose="test"))
    _, text = asyncio.run(website.read_page(f"{ORIGIN}/one", purpose="test"))
    assert len(text) == website.MAX_BYTES


def test_a_page_full_of_brackets_is_read_quickly():
    import time

    started = time.perf_counter()
    s4.candidate_sentences("[" * 200_000 + "\n" + "[a" * 100_000)
    assert time.perf_counter() - started < 2


def test_a_companys_own_site_isnt_tracking_by_that_company():
    assert site_policy.match_trackers(["connect.facebook.net", "static.xx.fbcdn.net"], "facebook.com") == []
    assert [t.name for t in site_policy.match_trackers(["connect.facebook.net"], "shopco.example")] == ["Meta (Facebook)"]


def test_domains_under_country_codes_are_not_cut_too_short():
    assert site_policy.registrable("www.ato.gov.au") == "ato.gov.au"
    assert site_policy.registrable("shop.store.com.cn") == "store.com.cn"
    assert site_policy.registrable("news.bbc.co.uk") == "bbc.co.uk"
    assert site_policy.registrable("www.shopco.example") == "shopco.example"


def test_the_model_can_add_clauses_but_never_weaken_one(monkeypatch):
    def handler(request):
        if request.url.host == "generativelanguage.googleapis.com":  # the model calls every sentence "affiliates"
            numbers = re.findall(r"^\[(\d+)\]", json.loads(request.content)["contents"][0]["parts"][0]["text"], re.M)
            picks = [{"sentence": int(n), "category": "affiliates", "explanation": "x"} for n in numbers]
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"clauses": picks})}]}}]})
        return fake_web(request)

    _use(monkeypatch, handler)

    async def run():
        await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))
        await site_policy._cache["shopco.example"].task
        return await site_policy.check_site(_req(policy_urls=[POLICY_URL]))

    res = asyncio.run(run())
    sale = next(c for c in res.clauses if c.quote.startswith("We sell"))
    assert sale.category == "sale" and res.risks[0].title == "It may sell your personal information"


def test_the_california_law_is_cited_only_for_personal_information(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(404, text="Not found"))
    trackers_only = _check(third_party_hosts=["connect.facebook.net"])
    asks_email = _check(asks_for=["email"])
    detail = lambda res: next(r.detail for r in res.risks if r.title == "Couldn't find a privacy policy")  # noqa: E731
    assert "California" not in detail(trackers_only)
    assert "California requires commercial websites" in detail(asks_email)


def test_overlong_links_and_hosts_are_dropped_not_fatal():
    req = SitePolicyRequest(
        origin=ORIGIN, policy_urls=["https://shopco.example/" + "a" * 3000, POLICY_URL],
        opt_out_url="https://shopco.example/" + "b" * 3000, third_party_hosts=["a" * 300 + ".example", "cdn.example.com"],
    )
    assert (req.policy_urls, req.opt_out_url, req.third_party_hosts) == ([POLICY_URL], None, ["cdn.example.com"])


# ---------- how Dossier knows, promises that don't add up, and forgetting ----------

# A policy that promises not to sell and says nothing about selling otherwise.
PROMISE_POLICY = "\n".join([
    "ShopCo Privacy Policy", FILLER, FILLER,
    "Information we collect",
    "We collect personal information such as your name and email address when you order.",
    "We share your information with service providers who help us run the store.",
    "We disclose personal information to our payment processor to complete your order.",
    "We do not sell your personal information to anyone, for money or anything else.",
])


def test_every_risk_says_how_dossier_knows(monkeypatch):
    _use(monkeypatch)
    res = _check(
        page_text=website.html_to_text(POLICY_HTML), policy_urls=[POLICY_URL], opt_out_url=f"{ORIGIN}/do-not-sell",
        third_party_hosts=["static.hotjar.com", "connect.facebook.net", "rlcdn.com", "platform.twitter.com"],
        asks_for=["email", "ssn"], insecure_fields=["ssn"],
    )
    without_policy = site_policy.page_risks(
        "no_policy", res.trackers, ["card"], [], BrokerMatch(name="PeopleFinder"),
        AdSellers(status="done", url="https://shopco.example/ads.txt", count=3, companies=["Google"]),
    )
    risks = res.risks + without_policy
    assert len({r.title for r in risks}) >= 12  # policy risks, page risks and the no-policy branch
    assert all(r.how for r in risks), [r.title for r in risks if not r.how]


def test_a_promise_not_to_sell_is_weighed_against_the_ad_tech_on_the_page(monkeypatch):
    _use(monkeypatch)
    promise = lambda res: [r for r in res.risks if r.title.startswith("It says it doesn't sell")]  # noqa: E731
    res = _check(page_text=PROMISE_POLICY, policy_urls=[POLICY_URL], third_party_hosts=["static.criteo.net", "rlcdn.com"])
    assert res.no_sale_quote == "We do not sell your personal information to anyone, for money or anything else."
    [risk] = promise(res)
    assert risk.title == "It says it doesn't sell your data, but ad companies and data brokers see this visit"
    assert (risk.level, risk.quote) == ("medium", res.no_sale_quote)
    assert risk.evidence == ["rlcdn.com", "static.criteo.net"]  # data brokers first, like the tracker list
    assert "LiveRamp and Criteo" in risk.detail and "can't see what those tags send" in risk.detail
    assert "leak" not in res.model_dump_json().lower()
    # Analytics alone isn't ad tech, and a policy that also says it sells has no promise to weigh.
    analytics = _check(page_text=PROMISE_POLICY, policy_urls=[POLICY_URL], third_party_hosts=["www.google-analytics.com"])
    sells_too = _check(
        page_text=website.html_to_text(POLICY_HTML), policy_urls=[POLICY_URL], third_party_hosts=["connect.facebook.net"]
    )
    assert sells_too.no_sale_quote and promise(analytics) == promise(sells_too) == []


def test_forgetting_drops_every_site_and_only_the_extensions_log_entries(client, monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(200, json={}) if r.url.host == "api.exa.ai" else fake_web(r))

    async def run():
        await outbound.request(
            "exa", "POST", "https://api.exa.ai/search", purpose="Stage 1: find listings", json_body={"query": "Jane Example"}
        )
        await site_policy.check_site(_req(policy_urls=[POLICY_URL], deep=True))  # the policy, ads.txt and Gemini
        await site_policy._cache["shopco.example"].task

    asyncio.run(run())
    assert {e.service for e in outbound.get_log()} == {"exa", "website", "gemini"}
    # The extension's entries name the site, so all of them carry the prefix forgetting looks for.
    assert all(e.purpose.startswith(site_policy.LOG_PREFIX) for e in outbound.get_log() if e.service != "exa")

    from_page = client.delete("/api/site-policy", headers={"Origin": "https://evil.example"})
    assert from_page.status_code == 403 and "shopco.example" in site_policy._cache

    res = client.delete("/api/site-policy", headers={"Origin": "chrome-extension://abcdef"})
    assert res.status_code == 200
    assert res.json()["sites"] == 1 and res.json()["log_entries"] >= 3
    assert not site_policy._cache
    assert [e.service for e in outbound.get_log()] == ["exa"]  # a scan's own requests stay in the log


# ---------- denials, headings and how strict the levels are ----------

# Built the way large sites' policies are: curly apostrophes, a denial that names data brokers, the
# HTML source wrapped mid-sentence, account linking the user asks for, and a heading whose section
# holds the real sentence.
WRAPPED_POLICY_HTML = f"""<html><body><main><h1>ShopCo Privacy Policy</h1><p>{FILLER}</p>
<h2>We use personal data to run ShopCo.</h2>
<p>Any data we collect is used primarily to provide our Services. We don’t sell your personal data to third
        parties, including data brokers.</p>
<h2>Information We Collect</h2>
<p>We collect personal information such as your email address when you create an account.</p>
<h3>Information Collected from Other Sources</h3>
<p>We may receive information about you from advertising partners and combine it with
        information you give us, using a hash of your email address.</p>
<p>We don’t buy information about you from data brokers.</p>
<h2>Linked Services</h2>
<p>If you link your ShopCo account with a third-party service, ShopCo will share the information you
        authorize with that third-party service.</p>
<p>We disclose personal information to our payment processor to complete your order.</p>
</main></body></html>"""


def test_source_line_breaks_are_spaces_like_in_a_browser():
    text = website.html_to_text("<p>We don’t sell your data to third\n    parties.</p><pre>keep\nthese</pre>")
    assert text.splitlines() == ["We don’t sell your data to third parties.", "keep", "these"]


def test_a_denial_is_never_cited_as_evidence_of_what_it_denies(monkeypatch):
    _use(monkeypatch)
    res = _check(policy_urls=[POLICY_URL], page_text=website.html_to_text(WRAPPED_POLICY_HTML))
    denial = "We don’t sell your personal data to third parties, including data brokers."
    assert res.status == "ok" and res.no_sale_quote == denial
    assert res.clauses == []  # not the denial, and not the account linking the user asks for
    assert not any(r.quote == denial for r in res.risks)
    assert res.risk == "medium"  # it does get data from advertisers; nothing it admits is high
    # The LLM can pick the denial too: the same rule drops it.
    picked = s4.parse_clauses({"clauses": [{"sentence": 1, "category": "data_broker"}]}, [denial], "shopco")
    assert site_policy.not_legal_only(picked) == []
    assert site_policy.not_legal_only([PolicyClause(category="data_broker", quote=denial, explanation="x")]) == []


def test_a_heading_gives_way_to_the_sentence_under_it_and_denials_dont_count():
    collected = site_policy.collected_data(website.html_to_text(WRAPPED_POLICY_HTML), "shopco")
    from_others = next(c for c in collected if c.category == "from_others")
    assert from_others.quote.startswith("We may receive information about you from advertising partners")
    assert "data brokers" not in from_others.quote  # "We don’t buy ... from data brokers" is a denial
    risk = next(r for r in site_policy.risks_for(collected, [], None) if r.title.startswith("It gets data"))
    assert risk.level == "medium"  # partners, not brokers


def test_high_is_kept_for_what_the_company_admits():
    trackers = site_policy.match_trackers(["static.hotjar.com", "rlcdn.com", "connect.facebook.net"], "shopco.example")
    ads = AdSellers(status="done", url="https://shopco.example/ads.txt", count=40, companies=["Google"])
    page = site_policy.page_risks("ok", trackers, ["email"], [], None, ads)
    assert {r.level for r in page} <= {"medium", "low"}  # tags it loads say what they can do, not what they did
    health = site_policy.collected_data("Information we collect\nYour health information and medical history.")
    ad_clause = PolicyClause(category="advertising", quote="We share your data with advertising partners.", explanation="x")
    sale_clause = PolicyClause(category="sale", quote="We sell your personal information.", explanation="x")
    level = lambda clauses: next(  # noqa: E731
        r.level for r in site_policy.risks_for(health, clauses, None) if r.title == "It collects sensitive data"
    )
    assert (level([ad_clause]), level([sale_clause])) == ("medium", "high")
    opt_out = site_policy.risks_for([], [], "https://shopco.example/do-not-sell")
    assert [r.level for r in opt_out] == ["low"]  # offering an opt-out isn't itself a risk


# ---------- the download on the website ----------


def test_the_extension_download_is_for_signed_in_accounts(client):
    import io
    import zipfile

    res = client.get("/api/extension.zip")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert "dossier-privacy-check/manifest.json" in names
    assert "dossier-privacy-check/content.js" in names
    assert all(name.startswith("dossier-privacy-check/") for name in names)
    client.cookies.clear()
    assert client.get("/api/extension.zip").status_code == 401
