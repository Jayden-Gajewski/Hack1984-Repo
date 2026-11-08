"""Shared fixtures for the threat monitor tests. Fictional companies and .example domains only;
the HIBP entries copy the real API's shape (GET /api/v3/breaches)."""

import dataclasses
from typing import Any

from app.config import get_settings

SHOPCO = {"id": "shopco", "name": "ShopCo", "domains": ["shopco.example"], "privacy_url": None}
CHATTER = {"id": "chatter", "name": "Chatter", "domains": ["chatter.example"], "privacy_url": None}
EMAIL = "jane.example@mail.example"


def breach(
    name: str,
    *,
    title: str | None = None,
    domain: str = "",
    date: str = "2021-03-04",
    classes: tuple[str, ...] = ("Email addresses", "Passwords"),
    verified: bool = True,
    description: str | None = None,
    **flags: Any,
) -> dict[str, Any]:
    shown = title or name
    return {
        "Name": name,
        "Title": shown,
        "Domain": domain,
        "BreachDate": date,
        "AddedDate": "2021-06-01T10:00:00Z",
        "ModifiedDate": "2021-06-01T10:00:00Z",
        "PwnCount": 120000,
        "Description": description
        if description is not None
        else (
            f'In March 2021, <a href="https://news.example/{name.lower()}" target="_blank" rel="noopener">'
            f"{shown} had 120,000 accounts exposed</a>. Users were advised to reset their passwords &amp; enable 2FA."
        ),
        "DataClasses": list(classes),
        "IsVerified": verified,
        "IsFabricated": flags.get("fabricated", False),
        "IsSensitive": flags.get("sensitive", False),
        "IsRetired": flags.get("retired", False),
        "IsSpamList": flags.get("spam_list", False),
        "IsMalware": False,
        "IsSubscriptionFree": False,
        "IsStealerLog": False,
        "LogoPath": "https://logos.example/logo.png",
        "DisclosureUrl": flags.get("disclosure"),
    }


CATALOG = [
    breach("ShopCo", domain="shopco.example"),
    breach(
        "ShopCo2023",
        title="ShopCo (2023)",
        domain="shopco.example",
        date="2023-01-10",
        classes=("Email addresses", "Names", "Dates of birth", "Physical addresses"),
    ),
    breach("ShopCoSpam", title="ShopCo spam list", spam_list=True),
    breach("ChatterLink", title="Chatter.link", domain="chatterlink.example"),
    breach("ChatterForum", title="Chatter", date="2019-05-01", classes=("Usernames", "IP addresses")),
    breach("OtherSite", domain="othersite.example", date="2018-02-02", classes=("Email addresses", "Phone numbers")),
]


def use_settings(monkeypatch, **overrides: Any):
    """Settings with every key and SMTP setting off unless given, in every module that reads them."""
    from app.clients import hibp
    from app.monitor import analysis, emails, service

    base = dataclasses.replace(
        get_settings(),
        exa_api_key="",
        tavily_api_key="",
        hibp_api_key="",
        smtp_host="",
        smtp_from="",
        smtp_username="",
        smtp_password="",
    )
    settings = dataclasses.replace(base, **overrides)
    for module in (hibp, analysis, emails, service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings
