"""Browser extension backend (app/site_policy.py and clients/website.py), against a fake site and
a fake local LLM. Nothing here touches the network."""

import asyncio
import json
import re

import httpx
import pytest

from app import outbound, site_policy
from app.clients import ollama, website
from app.companies import registrable
from app.models import PolicyClause, SitePolicyRequest
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
    if host in ("localhost", "127.0.0.1") and path == "/api/generate":  # the local LLM
        prompt = json.loads(request.content)["prompt"]
        guess = lambda s: "sale" if "sell" in s else "affiliates" if "affiliat" in s else "sharing"  # noqa: E731
        picks = [
            {"sentence": int(n), "category": guess(s), "explanation": "x"}
            for n, s in re.findall(r"^\[(\d+)\] (.*)$", prompt, re.M)
        ]
        return httpx.Response(200, json={"response": json.dumps({"clauses": picks})})
    raise AssertionError(f"unexpected request: {request.url}")


def _use(monkeypatch, handler=fake_web):
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(ollama, "_generate_slots", asyncio.Semaphore(1))
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

    # Only the site itself was contacted: no search API, no local LLM in the quick pass, no query string.
    log = outbound.get_log()
    assert {e.service for e in log} == {"website"}
    assert {httpx.URL(e.url).host for e in log} == {"www.shopco.example"}
    assert not any("ref=footer" in e.url for e in log)


def test_deep_pass_runs_the_local_llm_in_the_background(monkeypatch):
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
    assert site_policy._cache["shopco.example"].text == ""
    # Opening the popup also read the site's ads.txt.
    assert first.ad_sellers.status == "running"
    assert (done.ad_sellers.status, done.ad_sellers.count) == ("done", 4)
    log = outbound.get_log()
    assert [e.url for e in log if e.service == "website"] == [POLICY_URL, "https://shopco.example/ads.txt"]
    assert all(e.local for e in log if e.service == "ollama")
    for entry in log:
        if not entry.local:
            assert "data brokers" not in json.dumps(entry.body)  # policy text never left the laptop


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
    assert res.opt_out_url == "https://evil.example/do-not-sell"  # still shown, with its host, in the popup
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
        ("Meta Pixel", "advertising", ["connect.facebook.net"]),
        ("Google Tag Manager", "tag_manager", ["www.googletagmanager.com"]),
    ]  # the site's own cdn.shopco.example isn't a tracker
    risks = {r.title: r for r in res.risks}
    assert risks["It records what you do on this page"].evidence == ["static.hotjar.com"]
    assert risks["It records what you do on this page"].level == "high"
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
    assert risk.title == "It sells profiles of people" and "Check whether it lists you" in risk.detail


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
