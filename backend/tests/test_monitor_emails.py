"""Email ownership codes and the hashed HIBP check (app/monitor/emails.py)."""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.clients import hibp
from app.monitor import emails, store
from tests.monitor_fixtures import EMAIL, use_settings

SMTP = {"smtp_host": "smtp.mail.example", "smtp_from": "dossier@mail.example", "smtp_username": "u", "smtp_password": "app-password"}


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    async def send_mail(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(emails.outbound, "send_mail", send_mail)
    return sent


def code_from(mail):
    return re.search(r"\b(\d{6})\b", mail["text"]).group(1)


def test_mask_and_hash():
    assert emails.mask("jane.example@mail.example") == "j•••e@mail.example"
    assert emails.mask("jo@mail.example") == "j•@mail.example"
    assert emails.sha1_hex(" Jane@Mail.Example ") == emails.sha1_hex("jane@mail.example")
    assert len(emails.sha1_hex("x@y.example")) == 40


def test_without_smtp_an_address_is_added_but_never_verified(monkeypatch, outbox):
    use_settings(monkeypatch)
    added = asyncio.run(emails.add(EMAIL))
    assert not added.verified and added.display == EMAIL and outbox == []
    with pytest.raises(RuntimeError, match="SMTP"):
        asyncio.run(emails.send_code(added.id))
    with pytest.raises(ValueError, match="already monitoring"):
        asyncio.run(emails.add(EMAIL))


def test_code_verifies_and_then_the_address_is_deleted(monkeypatch, outbox):
    use_settings(monkeypatch, **SMTP)
    added = asyncio.run(emails.add(EMAIL))
    [mail] = outbox
    assert mail["to"] == EMAIL and mail["host"] == "smtp.mail.example"
    code = code_from(mail)
    assert mail["secrets"] == [code]  # outbound redacts it in the log
    raw = store.STORE_PATH.read_text()
    assert code not in raw  # only a salted hash of the code is stored

    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(ValueError, match="4 tries left"):
        asyncio.run(emails.verify(added.id, wrong))
    verified = asyncio.run(emails.verify(added.id, code))
    assert verified.verified and verified.display == "j•••e@mail.example"

    raw = store.STORE_PATH.read_text()
    assert EMAIL not in raw  # only the hash and the masked form are kept
    record = store.load()["emails"][0]
    assert record["address"] is None and record["sha1"] == emails.sha1_hex(EMAIL)


def test_codes_expire_run_out_and_are_rate_limited(monkeypatch, outbox):
    use_settings(monkeypatch, **SMTP)
    added = asyncio.run(emails.add(EMAIL))
    with pytest.raises(ValueError, match="less than a minute"):
        asyncio.run(emails.send_code(added.id))

    data = store.load()
    data["emails"][0]["code"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    store.save(data)
    with pytest.raises(ValueError, match="expired"):
        asyncio.run(emails.verify(added.id, code_from(outbox[0])))

    data = store.load()
    data["emails"][0]["code"] = {"hash": "x", "salt": "y", "sent_at": "2000-01-01T00:00:00+00:00",
                                 "expires_at": "2999-01-01T00:00:00+00:00", "attempts": emails.MAX_ATTEMPTS}
    store.save(data)
    with pytest.raises(ValueError, match="Too many tries"):
        asyncio.run(emails.verify(added.id, "123456"))
    assert store.load()["emails"][0]["code"] is None


def test_a_failed_send_can_be_retried_at_once(monkeypatch):
    use_settings(monkeypatch, **SMTP)

    async def broken(**kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(emails.outbound, "send_mail", broken)
    added = asyncio.run(emails.add(EMAIL))  # added even though the code didn't go out
    assert added.code_sent_at is None
    with pytest.raises(RuntimeError, match="connection refused"):
        asyncio.run(emails.send_code(added.id))


def verified_record(address=EMAIL, breaches=None, checked_at=None):
    return {"id": "em-1", "address": None, "sha1": emails.sha1_hex(address), "display": emails.mask(address),
            "added_at": "2026-11-07T00:00:00+00:00", "verified_at": "2026-11-07T00:00:00+00:00", "code": None,
            "check": {"status": "ok" if breaches is not None else "never", "message": "",
                      "checked_at": checked_at, "breaches": breaches or []}}


def test_check_without_a_key_sends_nothing(monkeypatch):
    use_settings(monkeypatch)
    calls = []

    async def range_search(prefix):
        calls.append(prefix)
        return []

    monkeypatch.setattr(hibp, "range_search", range_search)
    result = asyncio.run(emails.check([verified_record(breaches=["Earlier"], checked_at="2026-01-01T00:00:00+00:00")]))
    assert calls == []
    assert result["em-1"]["status"] == "not_configured" and "HIBP_API_KEY" in result["em-1"]["message"]
    assert result["em-1"]["breaches"] == ["Earlier"]  # an earlier real result is kept, not replaced


def test_check_sends_only_the_prefix_and_keeps_only_the_match(monkeypatch):
    use_settings(monkeypatch, hibp_api_key="k")
    digest = emails.sha1_hex(EMAIL)
    calls = []

    async def range_search(prefix):
        calls.append(prefix)
        return [
            {"hashSuffix": digest[6:].lower(), "websites": ["ShopCo", "OtherSite"]},
            {"hashSuffix": "F" * 34, "websites": ["SomeoneElses"]},
        ]

    monkeypatch.setattr(hibp, "range_search", range_search)
    unverified = {**verified_record(), "id": "em-2", "verified_at": None}
    result = asyncio.run(emails.check([verified_record(), unverified]))
    assert calls == [digest[:6]]
    assert set(result) == {"em-1"}  # unverified addresses are never checked
    assert result["em-1"]["status"] == "ok" and result["em-1"]["breaches"] == ["ShopCo", "OtherSite"]
    assert "SomeoneElses" not in str(result)


def test_rate_limits_wait_briefly_or_report(monkeypatch):
    use_settings(monkeypatch, hibp_api_key="k")
    slept, attempts = [], []

    async def sleep(seconds):
        slept.append(seconds)

    async def limited_once(prefix):
        attempts.append(prefix)
        if len(attempts) == 1:
            raise hibp.HibpError("HIBP's rate limit was reached.", 429, 2)
        return []

    monkeypatch.setattr(emails, "_sleep", sleep)
    monkeypatch.setattr(hibp, "range_search", limited_once)
    result = asyncio.run(emails.check([verified_record()]))
    assert slept == [2] and len(attempts) == 2 and result["em-1"]["status"] == "ok"

    async def limited_long(prefix):
        raise hibp.HibpError("HIBP's rate limit was reached. Try again in 60 s.", 429, 60)

    monkeypatch.setattr(hibp, "range_search", limited_long)
    result = asyncio.run(emails.check([verified_record(breaches=["ShopCo"], checked_at="2026-11-01T00:00:00+00:00")]))
    assert result["em-1"]["status"] == "rate_limited" and result["em-1"]["breaches"] == ["ShopCo"]


def test_plan_without_hashed_search_is_a_configuration_problem(monkeypatch):
    use_settings(monkeypatch, hibp_api_key="k")

    async def forbidden(prefix):
        raise hibp.HibpError("HIBP refused the request. The hashed email search needs a Pro or High RPM plan.", 403)

    monkeypatch.setattr(hibp, "range_search", forbidden)
    result = asyncio.run(emails.check([verified_record()]))
    assert result["em-1"]["status"] == "not_configured" and "Pro" in result["em-1"]["message"]


def test_unverified_addresses_are_deleted_after_a_day(monkeypatch, outbox):
    use_settings(monkeypatch)
    added = asyncio.run(emails.add(EMAIL))
    data = store.load()
    emails.prune_unverified(data)
    assert len(data["emails"]) == 1  # fresh: kept
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert emails.prune_unverified(data, now=later) == 1 and data["emails"] == []
    assert data["events"][0]["message"].startswith("Removed 1 unverified address")
    assert EMAIL not in data["events"][0]["message"]
    verified = verified_record()
    data["emails"] = [verified]
    assert emails.prune_unverified(data, now=later) == 0  # verified ones stay
    assert added.id  # (added through the normal path)


def test_a_failed_send_never_logs_the_address(monkeypatch, caplog):
    import smtplib

    use_settings(monkeypatch, **SMTP)

    async def refused(**kwargs):
        raise smtplib.SMTPRecipientsRefused({kwargs["to"]: (550, b"no such user")})

    monkeypatch.setattr(emails.outbound, "send_mail", refused)
    with caplog.at_level("WARNING"):
        asyncio.run(emails.add(EMAIL))
    assert "Verification code not sent" in caplog.text and EMAIL not in caplog.text
