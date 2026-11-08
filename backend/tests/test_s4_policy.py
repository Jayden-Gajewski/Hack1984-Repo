"""Stage 4 tests: the filters that keep "they sold it" honest, and the stage against a fake
internet. The fake Gemini flags every sentence as a sale, so only the code's checks
decide what survives."""

import asyncio
import json
import re

import httpx
import pytest

from app import outbound
from app.clients import gemini
from app.stages import s4_policy as s4

SHOPCO = {"id": "shopco", "name": "ShopCo", "domains": ["shopco.example"], "privacy_url": None}
POLICY_URL = "https://www.shopco.example/legal/privacy"
POLICY = """# ShopCo Privacy Policy

## How we share information
We sell your personal information to advertising partners and data brokers for their own marketing.
We do not sell your personal information to anyone else for money.
We may share your personal data with service providers who process payments on our behalf.
If our business is sold to another company, your personal information may be transferred as part of that merger.
You have the right to opt out of the sale of your personal information at any time.
| Category | Shared with third parties for their own purposes |
We share your information with our affiliates to run and improve the Services.
## Cookies
We use cookies to remember your settings.
"""


def fake_web(request: httpx.Request, extract_works: bool = True) -> httpx.Response:
    host, path = request.url.host, request.url.path
    body = json.loads(request.content or b"{}")
    if host == "api.tavily.com" and path == "/search" and "excerpts" not in body.get("query", ""):
        if "privacy policy sell share" in body["query"]:  # the snippet fallback
            return httpx.Response(200, json={"results": [{"url": POLICY_URL, "content": POLICY}]})
        return httpx.Response(200, json={"results": [
            {"url": "https://www.shopco.example/shop", "title": "Shop"},
            {"url": POLICY_URL, "title": "Privacy Policy | ShopCo"},
        ]})
    if host == "api.tavily.com" and path == "/extract":
        content = POLICY if extract_works else None
        return httpx.Response(200, json={"results": [{"url": POLICY_URL, "raw_content": content}], "failed_results": []})
    if host == "generativelanguage.googleapis.com" and path.endswith(":generateContent"):
        numbers = re.findall(r"^\[(\d+)\]", body["contents"][0]["parts"][0]["text"], re.M)
        clauses = [{"sentence": int(n), "category": "sale", "explanation": "They sell it."} for n in numbers]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"clauses": clauses})}]}}]})
    raise AssertionError(f"unexpected request: {request.url}")


def _use(monkeypatch, handler):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(outbound, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(gemini, "_generate_slots", asyncio.Semaphore(2))
    monkeypatch.setattr(s4, "all_companies", lambda: [SHOPCO])
    outbound.clear_log()


@pytest.fixture(autouse=True)
def _clear_settings():
    yield
    from app.config import get_settings
    get_settings.cache_clear()


def test_stage_keeps_only_real_sale_and_sharing_clauses(monkeypatch):
    _use(monkeypatch, fake_web)
    [result], errors = asyncio.run(s4.check_policies(["shopco"]))

    assert errors == []
    assert result.policy_url == POLICY_URL  # found by searching the company's own domain
    assert [(c.category, c.quote[:24]) for c in result.clauses] == [
        ("sale", "We sell your personal in"),  # the model's pick
        ("affiliates", "We share your informatio"),  # found by the strict pattern
    ]
    # The denial, service providers, merger, opt-out right and table row were all dropped.


def test_policy_text_goes_only_to_gemini(monkeypatch):
    _use(monkeypatch, fake_web)
    asyncio.run(s4.check_policies(["shopco"]))
    log = outbound.get_log()
    assert any(e.service == "gemini" and "data brokers" in json.dumps(e.body) for e in log)
    for entry in log:
        if entry.service != "gemini":
            assert "data brokers" not in json.dumps(entry.body)
    extract = [e for e in outbound.get_log() if e.url.endswith("/extract")]
    assert extract[0].body == {"urls": [POLICY_URL], "extract_depth": "advanced"}


def test_blocked_policy_falls_back_to_snippets(monkeypatch):
    _use(monkeypatch, lambda r: fake_web(r, extract_works=False))
    [result], errors = asyncio.run(s4.check_policies(["shopco"]))
    assert any("search snippets" in e for e in errors)
    assert result.clauses and result.clauses[0].category == "sale"


def test_candidate_sentences_skip_headings_tables_and_markdown():
    sentences = s4.candidate_sentences(
        "## Sharing\n- We share your data with [our partners](https://x.example/p) for their own marketing.\n"
        "| Shared with | third parties for their own purposes and advertising |\nTargeted Advertising.\n"
        "Who We Share Your Information With & Why"
    )
    assert sentences == ["We share your data with our partners for their own marketing."]


@pytest.mark.parametrize("quote,category,kept", [
    ("We sell your personal information to data brokers.", "sale", True),
    ("We do not sell your personal information.", "sale", False),  # denial
    ("If our business is sold, your personal data may be transferred in the merger.", "sale", False),
    ("For the purposes of this section, “sell” means disclosure of personal information.", "sale", False),
    ("You have the right to opt out of the sale of your personal information.", "sale", False),
    ("We sell premium subscriptions that unlock extra features for members.", "sale", False),  # not about data
    ("We share personal data with service providers that work on our behalf.", "sharing", False),
    ("We share personal data with service providers, partners and other third parties.", "sharing", True),
    ("You have many choices about how your data is collected, used and shared.", "sharing", False),
    ("Personal information is shared with advertising partners.", "sharing", False),  # not the company's voice
    # Denials in the wordings real policies use, curly apostrophes included.
    ("We don’t sell your personal data to third parties, including data brokers.", "data_broker", False),
    ("ShopCo doesn’t sell or rent your personal information to anyone.", "sale", False),
    ("We do not, and will not, sell your personal information to advertising partners.", "sale", False),
    ("We do not currently sell personal information to third parties.", "sale", False),
    ("We won't share your personal data with advertisers for their own marketing.", "sharing", False),
    # Sharing the user asks for is the user's choice.
    ("If you link your ShopCo account with a third-party service, we will share the information you authorize "
     "with that third-party service.", "sharing", False),
    ("We share personal data with partners and other third parties for their own marketing.", "sharing", True),
])
def test_passes_checks(quote, category, kept):
    assert s4.passes_checks(quote, category, "ShopCo") is kept


def test_merge_caps_clauses_per_category():
    clauses = s4.pattern_clauses(
        [f"We share your personal data with partner number {i} for their own marketing." for i in range(6)]
    )
    assert len(s4.merge_clauses(clauses)) == s4.MAX_PER_CATEGORY


def test_merge_drops_truncated_and_repeated_quotes():
    full = "We share information that identifies you personally with our affiliates, such as Cricket."
    clauses = [
        s4.PolicyClause(category="sharing", quote="We share information that identifies you personally with our", explanation="x"),
        s4.PolicyClause(category="affiliates", quote=full, explanation="x"),
        s4.PolicyClause(category="affiliates", quote=full, explanation="y"),
    ]
    assert [c.quote for c in s4.merge_clauses(clauses)] == [full]


def test_candidate_sentences_rejoin_split_ligatures():
    text = "We share information that identi fi es you personally with our advertising partners."
    assert s4.candidate_sentences(text) == [
        "We share information that identifies you personally with our advertising partners."
    ]


def test_pattern_flags_a_sale_under_state_law_without_the_model():
    quote = (
        "We also share information in ways that may be considered a sale of information under some state "
        "laws, such as exchanging subscriber lists for marketing or sharing identifiers and other "
        "information with non-AT&T advertising companies."
    )
    assert [c.category for c in s4.pattern_clauses([quote], "AT&T")] == ["sale"]
