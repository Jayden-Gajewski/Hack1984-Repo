"""Digital footprint: request rules, draft templates and the routes. Postgres is replaced by an
in-memory store with the same scoping rules, and any outbound request fails the test.
Offline, fictional data only."""

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from app import db, footprint, outbound

TODAY = date.today()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()

# Two fictional local accounts, by session cookie.
SESSIONS = {"token-ada": "11111111-1111-4111-8111-111111111111", "token-bo": "22222222-2222-4222-8222-222222222222"}
ADA = {"Cookie": "h84_session=token-ada"}
BO = {"Cookie": "h84_session=token-bo"}

COMPANY = {
    "name": "ExampleShop",
    "website": "shop.example",
    "account_label": "jane@mail.example",
    "notes": "Loyalty card since 2019.",
}


class FakeFootprint:
    """Dict-backed stand-ins for the db.footprint_* functions."""

    def __init__(self):
        self.companies: dict[str, dict] = {}
        self.requests: dict[str, dict] = {}
        self.events: list[dict] = []
        self.clock = 0
        self.next_id = 0

    def _now(self) -> str:
        self.clock += 1
        return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.clock)).isoformat()

    def _id(self) -> str:
        self.next_id += 1
        return f"00000000-0000-4000-8000-{self.next_id:012d}"

    def _company(self, user_id, company_id):
        c = self.companies.get(company_id)
        return c if c and c["user_id"] == user_id else None

    def _request(self, user_id, request_id):
        r = self.requests.get(request_id)
        return r if r and self._company(user_id, r["company_id"]) else None

    def footprint_companies(self, user_id, company_id=None):
        rows = [c for c in self.companies.values() if c["user_id"] == user_id and company_id in (None, c["id"])]
        out = []
        for c in sorted(rows, key=lambda c: c["updated_at"], reverse=True):
            requests = sorted(
                (r for r in self.requests.values() if r["company_id"] == c["id"]),
                key=lambda r: r["created_at"],
                reverse=True,
            )
            out.append(
                {
                    **{k: v for k, v in c.items() if k != "user_id"},
                    "requests": [
                        {
                            **{k: v for k, v in r.items() if k != "company_id"},
                            "history": [
                                {k: e[k] for k in ("status", "happened_on", "note", "recorded_at")}
                                for e in sorted(
                                    (e for e in self.events if e["request_id"] == r["id"]),
                                    key=lambda e: (e["happened_on"], e["recorded_at"]),
                                )
                            ],
                        }
                        for r in requests
                    ],
                }
            )
        return out

    def create_footprint_company(self, user_id, company):
        cid, now = self._id(), self._now()
        self.companies[cid] = {"id": cid, "user_id": user_id, **company, "created_at": now, "updated_at": now}
        return cid

    def update_footprint_company(self, user_id, company_id, company):
        c = self._company(user_id, company_id)
        if not c:
            return False
        c.update(company, updated_at=self._now())
        return True

    def delete_footprint_company(self, user_id, company_id):
        if not self._company(user_id, company_id):
            return False
        del self.companies[company_id]
        gone = {rid for rid, r in self.requests.items() if r["company_id"] == company_id}
        self.requests = {rid: r for rid, r in self.requests.items() if rid not in gone}
        self.events = [e for e in self.events if e["request_id"] not in gone]
        return True

    def create_footprint_request(self, user_id, company_id, kind, law, subject, body):
        c = self._company(user_id, company_id)
        if not c:
            return None
        rid, now = self._id(), self._now()
        self.requests[rid] = {
            "id": rid, "company_id": company_id, "kind": kind, "law": law, "subject": subject,
            "body": body, "status": "draft", "created_at": now, "updated_at": now,
        }  # fmt: skip
        c["updated_at"] = now
        return rid

    def footprint_request(self, user_id, request_id):
        r = self._request(user_id, request_id)
        if not r:
            return None
        dates = [date.fromisoformat(e["happened_on"]) for e in self.events if e["request_id"] == request_id]
        return {"company_id": r["company_id"], "status": r["status"], "last_on": max(dates, default=None)}

    def update_footprint_request_text(self, user_id, request_id, subject, body):
        r = self._request(user_id, request_id)
        if not r:
            return False
        now = self._now()
        r.update(subject=subject, body=body, updated_at=now)
        self.companies[r["company_id"]]["updated_at"] = now
        return True

    def add_footprint_event(self, user_id, request_id, status, happened_on, note):
        r = self._request(user_id, request_id)
        if not r:
            return False
        now = self._now()
        self.events.append(
            {"request_id": request_id, "status": status, "happened_on": happened_on.isoformat(), "note": note, "recorded_at": now}
        )
        r.update(status=status, updated_at=now)
        self.companies[r["company_id"]]["updated_at"] = now
        return True

    def undo_footprint_event(self, user_id, request_id):
        r = self._request(user_id, request_id)
        if not r:
            return None
        steps = sorted((e for e in self.events if e["request_id"] == request_id), key=lambda e: (e["happened_on"], e["recorded_at"]))
        if not steps:
            return r["company_id"], False
        self.events.remove(steps[-1])
        r.update(status=steps[-2]["status"] if len(steps) > 1 else "draft", updated_at=self._now())
        return r["company_id"], True

    def delete_footprint_request(self, user_id, request_id):
        r = self._request(user_id, request_id)
        if not r:
            return None
        del self.requests[request_id]
        self.events = [e for e in self.events if e["request_id"] != request_id]
        self.companies[r["company_id"]]["updated_at"] = self._now()
        return r["company_id"]


@pytest.fixture
def store(monkeypatch):
    fake = FakeFootprint()
    for name in (
        "footprint_companies", "create_footprint_company", "update_footprint_company",
        "delete_footprint_company", "create_footprint_request", "footprint_request",
        "update_footprint_request_text", "add_footprint_event", "delete_footprint_request",
        "undo_footprint_event",
    ):  # fmt: skip
        monkeypatch.setattr(db, name, getattr(fake, name))
    monkeypatch.setattr(db, "session_user_id", SESSIONS.get)

    # Every outbound call, whichever client makes it, needs outbound's HTTP client first.
    def no_network():
        raise AssertionError("the footprint feature must not make outbound requests")

    monkeypatch.setattr(outbound, "_get_client", no_network)
    return fake


def test_the_network_guard_really_trips(store, monkeypatch):
    """The guard above has to catch clients that imported `request` directly (exa, tavily, ...)."""
    import asyncio

    from app.clients import tavily

    monkeypatch.setattr(tavily, "_auth_headers", lambda: {"Authorization": "Bearer test"})  # no key needed
    with pytest.raises(AssertionError, match="must not make outbound requests"):
        asyncio.run(tavily.search("ExampleShop privacy policy", purpose="guard test", max_results=1))


def _company(client, headers=ADA):
    res = client.post("/api/footprint", json=COMPANY, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _draft(client, company_id, kind="access", law="none", headers=ADA):
    res = client.post(f"/api/footprint/{company_id}/requests", json={"kind": kind, "law": law}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["requests"][0]


def _update(client, request_id, headers=ADA, **body):
    return client.post(f"/api/footprint/requests/{request_id}/updates", json=body, headers=headers)


# ---------- Rules (pure) ----------


def test_drafts_ask_without_legal_claims_or_deadlines():
    subject, body = footprint.draft("access", "none", "ExampleShop", "jane@mail.example")
    assert subject == "Request for a copy of my personal data"
    assert "ExampleShop" in body and "jane@mail.example" in body and "[Your name]" in body
    assert "GDPR" not in body and "CCPA" not in body

    _, deletion = footprint.draft("deletion", "gdpr", "ExampleShop", "")
    assert "Article 17" in deletion and "[the email address, username or account number" in deletion
    assert "California Consumer Privacy Act" in footprint.draft("access", "ccpa", "ExampleShop", "")[1]

    for kind in ("access", "deletion"):
        for law in ("none", "gdpr", "ccpa"):
            text = " ".join(footprint.draft(kind, law, "ExampleShop", "")).lower()
            assert not any(w in text for w in ("days", "deadline", "within", "required by law", "you must"))


@pytest.mark.parametrize(
    "current, new, allowed",
    [
        ("draft", "ready_to_send", True),
        ("draft", "sent", True),
        ("draft", "unable_to_complete", True),
        ("draft", "response_received", False),
        ("draft", "completed", False),
        ("ready_to_send", "sent", True),
        ("ready_to_send", "completed", False),
        ("sent", "response_received", True),
        ("sent", "completed", True),
        ("sent", "ready_to_send", True),
        ("response_received", "completed", True),
        ("completed", "response_received", True),
        ("completed", "draft", False),
        ("unable_to_complete", "sent", True),
    ],
)
def test_status_transitions(current, new, allowed):
    if allowed:
        footprint.check_update(current, new, "", TODAY, None)
    else:
        with pytest.raises(ValueError):
            footprint.check_update(current, new, "", TODAY, None)


def test_updates_need_a_change_or_a_note_and_dates_stay_in_order():
    with pytest.raises(ValueError, match="note"):
        footprint.check_update("sent", "sent", "", TODAY, None)
    footprint.check_update("sent", "sent", "Called their support line", TODAY, None)
    with pytest.raises(ValueError, match="on or after 2026-02-01"):
        footprint.check_update("sent", "response_received", "", date(2026, 1, 15), date(2026, 2, 1))
    with pytest.raises(ValueError, match="sent before"):
        footprint.check_update("draft", "completed", "", TODAY, None)


def test_websites_must_be_plain_web_addresses():
    assert footprint.normalize_website("shop.example") == "https://shop.example"
    assert footprint.normalize_website("http://shop.example/privacy") == "http://shop.example/privacy"
    assert footprint.normalize_website("   ") == ""
    for bad in ("javascript:alert(1)", "not a website", "shop", "https://exa mple.example"):
        with pytest.raises(ValueError):
            footprint.normalize_website(bad)


# ---------- Routes ----------


def test_footprint_needs_a_session(client, store):
    assert client.get("/api/footprint").status_code == 401
    assert client.get("/api/footprint", headers={"Cookie": "h84_session=expired"}).status_code == 401
    assert client.post("/api/footprint", json=COMPANY).status_code == 401


def test_add_edit_and_remove_a_company(client, store):
    control = {"name": "Sell or share my personal information", "state": "off", "checked_on": TODAY.isoformat()}
    created = client.post("/api/footprint", json={**COMPANY, "controls": [control]}, headers=ADA)
    assert created.status_code == 200, created.text
    company = created.json()
    assert company["website"] == "https://shop.example" and company["requests"] == []
    assert company["controls"] == [{**control, "note": ""}]

    edited = client.put(f"/api/footprint/{company['id']}", json={**COMPANY, "name": "ExampleShop Inc."}, headers=ADA)
    assert edited.status_code == 200 and edited.json()["name"] == "ExampleShop Inc." and edited.json()["controls"] == []

    reloaded = client.get("/api/footprint", headers=ADA).json()
    assert [(c["name"], c["account_label"], c["notes"]) for c in reloaded] == [
        ("ExampleShop Inc.", "jane@mail.example", "Loyalty card since 2019.")
    ]

    assert client.delete(f"/api/footprint/{company['id']}", headers=ADA).json() == {"deleted": True}
    assert client.get("/api/footprint", headers=ADA).json() == []
    assert client.delete(f"/api/footprint/{company['id']}", headers=ADA).status_code == 404


def test_company_input_is_validated(client, store):
    assert client.post("/api/footprint", json={"name": "   "}, headers=ADA).status_code == 422
    bad_site = client.post("/api/footprint", json={"name": "ExampleShop", "website": "javascript:alert(1)"}, headers=ADA)
    assert bad_site.status_code == 422 and "website" in bad_site.text
    future = client.post(
        "/api/footprint", json={"name": "ExampleShop", "controls": [{"name": "Ads", "checked_on": TOMORROW}]}, headers=ADA
    )
    assert future.status_code == 422 and "future" in future.text
    assert client.get("/api/footprint/not-a-uuid", headers=ADA).status_code in (404, 405, 422)


def test_request_lifecycle_keeps_dates_notes_and_the_sent_text(client, store):
    company = _company(client)
    request = _draft(client, company["id"], kind="deletion", law="gdpr")
    assert request["status"] == "draft" and request["editable"] and request["history"] == []
    assert "ExampleShop" in request["body"] and "jane@mail.example" in request["body"] and "Article 17" in request["body"]
    assert "completed" not in request["next_statuses"]
    rid = request["id"]

    edited = client.patch(
        f"/api/footprint/requests/{rid}",
        json={"subject": "Delete my account", "body": "Please delete my ExampleShop account."},
        headers=ADA,
    )
    assert edited.json()["requests"][0]["body"] == "Please delete my ExampleShop account."

    early = _update(client, rid, status="completed")
    assert early.status_code == 409 and "sent before" in early.json()["detail"]

    sent_on = (TODAY - timedelta(days=10)).isoformat()
    sent = _update(client, rid, status="sent", happened_on=sent_on, note="Emailed privacy@shop.example")
    assert sent.status_code == 200, sent.text
    assert sent.json()["requests"][0]["status"] == "sent" and not sent.json()["requests"][0]["editable"]

    locked = client.patch(f"/api/footprint/requests/{rid}", json={"subject": "x", "body": "y"}, headers=ADA)
    assert locked.status_code == 409
    assert _update(client, rid, status="response_received", happened_on=(TODAY - timedelta(days=20)).isoformat()).status_code == 409

    _update(client, rid, status="response_received", note="They asked me to confirm the email address.")
    done = _update(client, rid, status="completed").json()["requests"][0]

    # A reload reads back everything the user recorded, in the order it happened.
    reloaded = client.get("/api/footprint", headers=ADA).json()[0]["requests"][0]
    assert reloaded == done
    assert reloaded["status"] == "completed" and reloaded["next_statuses"] == ["response_received"]
    assert reloaded["body"] == "Please delete my ExampleShop account."
    assert [(e["status"], e["happened_on"], e["note"]) for e in reloaded["history"]] == [
        ("sent", sent_on, "Emailed privacy@shop.example"),
        ("response_received", TODAY.isoformat(), "They asked me to confirm the email address."),
        ("completed", TODAY.isoformat(), ""),
    ]


def test_notes_future_dates_and_removing_a_request(client, store):
    company = _company(client)
    rid = _draft(client, company["id"])["id"]
    assert _update(client, rid, status="sent", happened_on=TOMORROW).status_code == 422
    assert _update(client, rid, status="draft").status_code == 409  # no change and no note
    noted = _update(client, rid, status="draft", note="Waiting until I close the account.")
    assert noted.json()["requests"][0]["history"][0]["note"] == "Waiting until I close the account."
    assert noted.json()["requests"][0]["status"] == "draft"

    after = client.delete(f"/api/footprint/requests/{rid}", headers=ADA)
    assert after.status_code == 200 and after.json()["requests"] == []
    assert client.delete(f"/api/footprint/requests/{rid}", headers=ADA).status_code == 404
    assert store.events == []


def test_undo_the_last_step(client, store):
    rid = _draft(client, _company(client)["id"])["id"]
    undo = lambda headers=ADA: client.delete(f"/api/footprint/requests/{rid}/updates/last", headers=headers)  # noqa: E731
    assert undo().status_code == 409  # nothing recorded yet
    _update(client, rid, status="ready_to_send")
    _update(client, rid, status="sent", note="Sent by mistake")
    assert undo(BO).status_code == 404  # not theirs
    back = undo().json()["requests"][0]
    assert back["status"] == "ready_to_send" and back["editable"] and [e["status"] for e in back["history"]] == ["ready_to_send"]
    assert undo().json()["requests"][0]["status"] == "draft"


def test_one_entry_per_company(client, store):
    first = _company(client)
    assert client.post("/api/footprint", json={**COMPANY, "name": "exampleshop"}, headers=ADA).status_code == 409
    second = client.post("/api/footprint", json={**COMPANY, "name": "ExampleFitness"}, headers=ADA).json()
    rename = client.put(f"/api/footprint/{second['id']}", json={**COMPANY, "name": "EXAMPLESHOP"}, headers=ADA)
    assert rename.status_code == 409 and "already track" in rename.json()["detail"]
    assert client.put(f"/api/footprint/{first['id']}", json={**COMPANY, "notes": "Kept"}, headers=ADA).status_code == 200
    assert client.post("/api/footprint", json=COMPANY, headers=BO).status_code == 200  # other accounts are separate


def test_accounts_only_see_their_own_records(client, store):
    company = _company(client)
    rid = _draft(client, company["id"])["id"]
    assert client.get("/api/footprint", headers=BO).json() == []
    assert client.put(f"/api/footprint/{company['id']}", json=COMPANY, headers=BO).status_code == 404
    assert client.delete(f"/api/footprint/{company['id']}", headers=BO).status_code == 404
    assert client.post(f"/api/footprint/{company['id']}/requests", json={"kind": "access"}, headers=BO).status_code == 404
    assert client.patch(f"/api/footprint/requests/{rid}", json={"subject": "x", "body": "y"}, headers=BO).status_code == 404
    assert _update(client, rid, headers=BO, status="sent").status_code == 404
    assert client.delete(f"/api/footprint/requests/{rid}", headers=BO).status_code == 404
    assert len(client.get("/api/footprint", headers=ADA).json()[0]["requests"]) == 1


def test_database_down_is_a_clear_error(client, store, monkeypatch):
    def down(*args):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db, "footprint_companies", down)
    res = client.get("/api/footprint", headers=ADA)
    assert res.status_code == 503 and "Postgres" in res.json()["detail"]
