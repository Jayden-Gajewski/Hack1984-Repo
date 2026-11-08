"""What leaves the laptop for the threat monitor, checked through the real outbound log:
HIBP gets nothing personal (the breach list) or a 6-character hash prefix; SMTP mail is logged
with the code redacted and never the password."""

import asyncio
import json

import httpx
import pytest

from app import outbound
from app.clients import hibp
from app.monitor import emails
from tests.monitor_fixtures import EMAIL, use_settings


def _fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": outbound.USER_AGENT})


@pytest.fixture
def wire(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/range/" in request.url.path:
            return httpx.Response(200, json=[{"hashSuffix": "ABC", "websites": ["X"]}])
        if request.url.path.endswith("/breaches"):
            return httpx.Response(200, json=[{"Name": "X"}])
        return httpx.Response(404)

    monkeypatch.setattr(outbound, "_client", _fake_client(handler))
    outbound.clear_log()
    yield seen
    outbound.clear_log()


def test_the_breach_list_request_carries_nothing_personal(monkeypatch, wire):
    use_settings(monkeypatch, hibp_api_key="secret-hibp-key")
    assert asyncio.run(hibp.breaches()) == [{"Name": "X"}]
    [request] = wire
    assert str(request.url) == "https://haveibeenpwned.com/api/v3/breaches"
    assert "hibp-api-key" not in request.headers and request.headers["user-agent"]
    [entry] = outbound.get_log()
    assert entry.service == "hibp" and entry.body is None


def test_the_email_check_sends_a_hash_prefix_and_the_key_is_redacted(monkeypatch, wire):
    use_settings(monkeypatch, hibp_api_key="secret-hibp-key")
    prefix = emails.sha1_hex(EMAIL)[:6]
    asyncio.run(hibp.range_search(prefix))
    [request] = wire
    assert request.url.path == f"/api/v3/breachedaccount/range/{prefix}"
    assert request.headers["hibp-api-key"] == "secret-hibp-key"
    log = json.dumps([e.model_dump() for e in outbound.get_log()])
    assert "secret-hibp-key" not in log and outbound.REDACTED in log
    assert EMAIL not in log and emails.sha1_hex(EMAIL) not in log  # not even the full hash


@pytest.mark.parametrize("bad", [EMAIL, emails.sha1_hex(EMAIL), "ABC", "ZZZZZZ"])
def test_anything_but_a_prefix_is_refused_before_sending(monkeypatch, wire, bad):
    use_settings(monkeypatch, hibp_api_key="k")
    with pytest.raises(ValueError):
        asyncio.run(hibp.range_search(bad))
    assert wire == [] and outbound.get_log() == []


def test_hibp_errors_are_explained(monkeypatch):
    use_settings(monkeypatch, hibp_api_key="k")

    def handler(request):
        return httpx.Response(429, headers={"retry-after": "7"}, json={"statusCode": 429})

    monkeypatch.setattr(outbound, "_client", _fake_client(handler))
    with pytest.raises(hibp.HibpError) as err:
        asyncio.run(hibp.range_search("ABCDEF"))
    assert err.value.status == 429 and err.value.retry_after == 7 and "7 s" in str(err.value)

    use_settings(monkeypatch)
    with pytest.raises(hibp.HibpError, match="HIBP_API_KEY"):
        asyncio.run(hibp.range_search("ABCDEF"))
    outbound.clear_log()


def test_mail_is_logged_with_the_code_redacted(monkeypatch):
    sent = []
    monkeypatch.setattr(outbound, "_smtp_send", lambda *args: sent.append(args))
    outbound.clear_log()
    asyncio.run(outbound.send_mail(
        purpose="Send an ownership code", host="smtp.mail.example", port=587, username="u",
        password="app-password", sender="dossier@mail.example", to=EMAIL, subject="Code",
        text="Your code is 482913.", secrets=["482913"],
    ))
    [entry] = outbound.get_log()
    assert entry.service == "smtp" and entry.url == "smtp://smtp.mail.example:587" and entry.status == 250
    assert entry.headers["To"] == EMAIL  # the log shows exactly who received it
    dumped = json.dumps(entry.model_dump())
    assert "482913" not in dumped and "app-password" not in dumped
    assert sent and sent[0][0] == "smtp.mail.example"
    outbound.clear_log()


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.calls = host, []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def has_extn(self, name):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")
        if self.host != "localhost":
            raise outbound.smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, message):
        self.calls.append("send")


def test_remote_smtp_must_use_tls_and_a_local_catcher_may_not(monkeypatch):
    monkeypatch.setattr(outbound.smtplib, "SMTP", _FakeSMTP)
    message = outbound.EmailMessage()
    with pytest.raises(outbound.smtplib.SMTPNotSupportedError):
        outbound._smtp_send("smtp.mail.example", 587, "u", "p", message, 5)
    assert "send" not in _FakeSMTP.instances[-1].calls  # nothing sent in the clear
    outbound._smtp_send("localhost", 1025, "", "", message, 5)
    assert _FakeSMTP.instances[-1].calls == ["ehlo", "send"]
