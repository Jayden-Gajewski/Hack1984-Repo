"""PostgreSQL access. The database runs locally in Docker (docker-compose.yml at the repo root).

It stores saved scans, so "load last scan" still works if the venue Wi-Fi dies, the
email aliases from Stage 7, local accounts, and each account's digital footprint (tracked
companies and data requests). The rows hold personal data: the database stays on this
laptop and nothing from it is committed.

This uses psycopg's sync API on purpose; call it through asyncio.to_thread(). psycopg's
async mode doesn't work with the default event loop on Windows.
"""

import uuid
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

from app.auth import current_user
from app.config import get_settings

SCHEMA = """
create table if not exists scans (
    id          uuid primary key,
    created_at  timestamptz not null default now(),
    request     jsonb not null,
    response    jsonb not null
);

create table if not exists aliases (
    alias           text primary key,
    company         text not null,
    company_domains jsonb not null,
    created_at      timestamptz not null default now()
);

create table if not exists users (
    id            uuid primary key,
    email         text unique not null,
    password_hash text not null,
    created_at    timestamptz not null default now()
);
-- Accounts are email + password only; drop the name column an earlier version created.
alter table users drop column if exists name;

create table if not exists sessions (
    token       text primary key,
    user_id     uuid not null references users(id) on delete cascade,
    created_at  timestamptz not null default now()
);

-- Digital footprint: companies the user tracks, their data requests, and each request's history.
create table if not exists footprint_companies (
    id            uuid primary key,
    user_id       uuid not null references users(id) on delete cascade,
    name          text not null,
    website       text not null default '',
    account_label text not null default '',
    notes         text not null default '',
    controls      jsonb not null default '[]',
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create table if not exists footprint_requests (
    id          uuid primary key,
    company_id  uuid not null references footprint_companies(id) on delete cascade,
    kind        text not null,
    law         text not null,
    subject     text not null,
    body        text not null,
    status      text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table if not exists footprint_events (
    id          bigserial primary key,
    request_id  uuid not null references footprint_requests(id) on delete cascade,
    status      text not null,
    happened_on date not null,
    note        text not null default '',
    recorded_at timestamptz not null default now()
);

-- Saved scans belong to the account that ran them. Rows saved before accounts existed have no
-- owner, so nobody who is signed in sees them.
alter table scans add column if not exists user_id uuid references users(id) on delete cascade;
"""


def connect() -> psycopg.Connection:
    url = get_settings().database_url
    # docker-compose publishes Postgres on 127.0.0.1 only. Given "localhost", libpq tries ::1
    # first, and on Windows that costs the whole connect_timeout (3 s) on every call.
    ipv4 = {"host": "127.0.0.1"} if urlsplit(url).hostname == "localhost" else {}
    return psycopg.connect(url, autocommit=True, connect_timeout=3, **ipv4)


def init_schema() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)


def ping() -> bool:
    try:
        with connect() as conn:
            conn.execute("select 1")
        return True
    except psycopg.Error:
        return False


def _owner() -> uuid.UUID | None:
    """The signed-in account of the current API request, which owns the scans it saves and reads."""
    user = current_user()
    return uuid.UUID(user) if user else None


def save_scan(scan_id: str, request: dict[str, Any], response: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "insert into scans (id, request, response, user_id) values (%s, %s, %s, %s)",
            (uuid.UUID(scan_id), Jsonb(request), Jsonb(response), _owner()),
        )


def find_scan(name: str, city: str, state: str) -> tuple[str, dict[str, Any]] | None:
    """(saved-at ISO timestamp, response) for the newest saved scan of this person, or None.
    Matches name and city ignoring case and extra spaces, and the state code exactly."""
    with connect() as conn:
        row = conn.execute(
            """
            select created_at, response from scans
            where lower(regexp_replace(trim(request->>'name'), '\\s+', ' ', 'g')) = %s
              and lower(regexp_replace(trim(request->>'city'), '\\s+', ' ', 'g')) = %s
              and upper(request->>'state') = %s
              and user_id is not distinct from %s
            order by created_at desc
            limit 1
            """,
            (_squash(name), _squash(city), state.upper(), _owner()),
        ).fetchone()
    return (row[0].isoformat(), row[1]) if row else None


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def latest_scan() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (request, response) for this account's most recent saved scan, or None."""
    with connect() as conn:
        row = conn.execute(
            "select request, response from scans where user_id is not distinct from %s"
            " order by created_at desc limit 1",
            (_owner(),),
        ).fetchone()
    return (row[0], row[1]) if row else None


def save_alias(alias: str, company: str, company_domains: list[str]) -> str:
    """Store a new alias. Returns its creation date (YYYY-MM-DD)."""
    with connect() as conn:
        row = conn.execute(
            "insert into aliases (alias, company, company_domains) values (%s, %s, %s) returning created_at",
            (alias, company, Jsonb(company_domains)),
        ).fetchone()
    return row[0].date().isoformat()


def list_aliases() -> list[dict[str, Any]]:
    """Every saved alias, oldest first, as dicts shaped like models.Alias."""
    with connect() as conn:
        rows = conn.execute(
            "select alias, company, company_domains, created_at from aliases order by created_at"
        ).fetchall()
    return [
        {"alias": a, "company": c, "company_domains": d, "created_at": t.date().isoformat()}
        for a, c, d, t in rows
    ]


# ---------- Local accounts ----------


def create_user(email: str, password_hash: str) -> bool:
    """Insert a user. Returns False if the email is already taken."""
    with connect() as conn:
        row = conn.execute(
            "insert into users (id, email, password_hash) values (%s, %s, %s)"
            " on conflict (email) do nothing returning id",
            (uuid.uuid4(), email, password_hash),
        ).fetchone()
    return row is not None


def get_user(email: str) -> tuple[str, str] | None:
    """(id, password_hash) for an email, or None."""
    with connect() as conn:
        row = conn.execute(
            "select id, password_hash from users where email = %s", (email,)
        ).fetchone()
    return (str(row[0]), row[1]) if row else None


def claim_unowned_scans(user_id: str) -> int:
    """Scans saved before accounts existed go to the first account made on this laptop, so its
    "Load last scan" keeps working. Later accounts get nothing. Returns how many were claimed."""
    with connect() as conn, conn.transaction():
        if conn.execute("select count(*) from users").fetchone()[0] != 1:
            return 0
        return conn.execute("update scans set user_id = %s where user_id is null", (uuid.UUID(user_id),)).rowcount


def create_session(user_id: str, token: str) -> None:
    with connect() as conn:
        conn.execute(
            "insert into sessions (token, user_id) values (%s, %s)", (token, uuid.UUID(user_id))
        )


def session_user(token: str) -> str | None:
    """The email for a session token, or None. Sessions last 30 days."""
    with connect() as conn:
        row = conn.execute(
            "select u.email from sessions s join users u on u.id = s.user_id"
            " where s.token = %s and s.created_at > now() - interval '30 days'",
            (token,),
        ).fetchone()
    return row[0] if row else None


def delete_session(token: str) -> None:
    with connect() as conn:
        conn.execute("delete from sessions where token = %s", (token,))


def session_user_id(token: str) -> str | None:
    """The user id for a session token, or None. Same 30-day limit as session_user."""
    with connect() as conn:
        row = conn.execute(
            "select user_id from sessions where token = %s and created_at > now() - interval '30 days'",
            (token,),
        ).fetchone()
    return str(row[0]) if row else None


# ---------- Digital footprint ----------
# The user's own records of companies that hold their data and the requests they've made.
# Every query is scoped to the signed-in account's user_id. Shapes match models.TrackedCompany.


def footprint_companies(user_id: str, company_id: str | None = None) -> list[dict[str, Any]]:
    """The user's tracked companies, most recently changed first, each with its requests
    (newest first) and each request's history (in the order it happened). With company_id,
    just that company, or an empty list if it isn't this user's."""
    with connect() as conn:
        if company_id:
            companies = conn.execute(
                "select id, name, website, account_label, notes, controls, created_at, updated_at"
                " from footprint_companies where user_id = %s and id = %s",
                (uuid.UUID(user_id), uuid.UUID(company_id)),
            ).fetchall()
        else:
            companies = conn.execute(
                "select id, name, website, account_label, notes, controls, created_at, updated_at"
                " from footprint_companies where user_id = %s order by updated_at desc",
                (uuid.UUID(user_id),),
            ).fetchall()
        company_ids = [row[0] for row in companies]
        requests = (
            conn.execute(
                "select id, company_id, kind, law, subject, body, status, created_at, updated_at"
                " from footprint_requests where company_id = any(%s) order by created_at desc",
                (company_ids,),
            ).fetchall()
            if company_ids
            else []
        )
        request_ids = [row[0] for row in requests]
        events = (
            conn.execute(
                "select request_id, status, happened_on, note, recorded_at from footprint_events"
                " where request_id = any(%s) order by happened_on, recorded_at, id",
                (request_ids,),
            ).fetchall()
            if request_ids
            else []
        )

    history: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for request_id, status, happened_on, note, recorded_at in events:
        history.setdefault(request_id, []).append(
            {"status": status, "happened_on": happened_on.isoformat(), "note": note, "recorded_at": recorded_at.isoformat()}
        )
    by_company: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for request_id, company, kind, law, subject, body, status, created_at, updated_at in requests:
        by_company.setdefault(company, []).append(
            {
                "id": str(request_id),
                "kind": kind,
                "law": law,
                "subject": subject,
                "body": body,
                "status": status,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat(),
                "history": history.get(request_id, []),
            }
        )
    return [
        {
            "id": str(cid),
            "name": name,
            "website": website,
            "account_label": account_label,
            "notes": notes,
            "controls": controls,
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            "requests": by_company.get(cid, []),
        }
        for cid, name, website, account_label, notes, controls, created_at, updated_at in companies
    ]


def create_footprint_company(user_id: str, company: dict[str, Any]) -> str:
    """Insert a tracked company (fields shaped like models.TrackedCompanyInput). Returns its id."""
    company_id = uuid.uuid4()
    with connect() as conn:
        conn.execute(
            "insert into footprint_companies (id, user_id, name, website, account_label, notes, controls)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            (
                company_id,
                uuid.UUID(user_id),
                company["name"],
                company["website"],
                company["account_label"],
                company["notes"],
                Jsonb(company["controls"]),
            ),
        )
    return str(company_id)


def update_footprint_company(user_id: str, company_id: str, company: dict[str, Any]) -> bool:
    """Replace a tracked company's details. False if it isn't this user's."""
    with connect() as conn:
        updated = conn.execute(
            "update footprint_companies set name = %s, website = %s, account_label = %s, notes = %s,"
            " controls = %s, updated_at = now() where id = %s and user_id = %s",
            (
                company["name"],
                company["website"],
                company["account_label"],
                company["notes"],
                Jsonb(company["controls"]),
                uuid.UUID(company_id),
                uuid.UUID(user_id),
            ),
        ).rowcount
    return updated == 1


def delete_footprint_company(user_id: str, company_id: str) -> bool:
    """Delete a tracked company with all its requests and history. False if it isn't this user's."""
    with connect() as conn:
        deleted = conn.execute(
            "delete from footprint_companies where id = %s and user_id = %s",
            (uuid.UUID(company_id), uuid.UUID(user_id)),
        ).rowcount
    return deleted == 1


def create_footprint_request(
    user_id: str, company_id: str, kind: str, law: str, subject: str, body: str
) -> str | None:
    """Save a new draft request for one of the user's companies. None if the company isn't theirs."""
    request_id = uuid.uuid4()
    with connect() as conn, conn.transaction():
        owned = conn.execute(
            "update footprint_companies set updated_at = now() where id = %s and user_id = %s returning id",
            (uuid.UUID(company_id), uuid.UUID(user_id)),
        ).fetchone()
        if not owned:
            return None
        conn.execute(
            "insert into footprint_requests (id, company_id, kind, law, subject, body, status)"
            " values (%s, %s, %s, %s, %s, %s, 'draft')",
            (request_id, uuid.UUID(company_id), kind, law, subject, body),
        )
    return str(request_id)


def footprint_request(user_id: str, request_id: str) -> dict[str, Any] | None:
    """One of the user's requests: its company id, status and the last date recorded for it."""
    with connect() as conn:
        row = conn.execute(
            "select r.company_id, r.status,"
            " (select max(e.happened_on) from footprint_events e where e.request_id = r.id)"
            " from footprint_requests r join footprint_companies c on c.id = r.company_id"
            " where r.id = %s and c.user_id = %s",
            (uuid.UUID(request_id), uuid.UUID(user_id)),
        ).fetchone()
    return {"company_id": str(row[0]), "status": row[1], "last_on": row[2]} if row else None


def update_footprint_request_text(user_id: str, request_id: str, subject: str, body: str) -> bool:
    """Replace a request's subject and body. False if it isn't this user's."""
    with connect() as conn, conn.transaction():
        row = conn.execute(
            "update footprint_requests r set subject = %s, body = %s, updated_at = now()"
            " from footprint_companies c where r.id = %s and c.id = r.company_id and c.user_id = %s"
            " returning r.company_id",
            (subject, body, uuid.UUID(request_id), uuid.UUID(user_id)),
        ).fetchone()
        if row:
            conn.execute("update footprint_companies set updated_at = now() where id = %s", (row[0],))
    return row is not None


def add_footprint_event(user_id: str, request_id: str, status: str, happened_on: date, note: str) -> bool:
    """Record one step in a request's history and make its status current. False if not this user's."""
    with connect() as conn, conn.transaction():
        row = conn.execute(
            "update footprint_requests r set status = %s, updated_at = now()"
            " from footprint_companies c where r.id = %s and c.id = r.company_id and c.user_id = %s"
            " returning r.company_id",
            (status, uuid.UUID(request_id), uuid.UUID(user_id)),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "insert into footprint_events (request_id, status, happened_on, note) values (%s, %s, %s, %s)",
            (uuid.UUID(request_id), status, happened_on, note),
        )
        conn.execute("update footprint_companies set updated_at = now() where id = %s", (row[0],))
    return True


def undo_footprint_event(user_id: str, request_id: str) -> tuple[str, bool] | None:
    """Remove the last recorded step of one of the user's requests and go back to the status
    before it (Draft if none). (company id, whether a step was removed), or None if not theirs."""
    rid = uuid.UUID(request_id)
    with connect() as conn, conn.transaction():
        owned = conn.execute(
            "select r.company_id from footprint_requests r join footprint_companies c on c.id = r.company_id"
            " where r.id = %s and c.user_id = %s",
            (rid, uuid.UUID(user_id)),
        ).fetchone()
        if not owned:
            return None
        removed = conn.execute(
            "delete from footprint_events where id = (select id from footprint_events where request_id = %s"
            " order by happened_on desc, recorded_at desc, id desc limit 1) returning id",
            (rid,),
        ).fetchone()
        if removed:
            before = conn.execute(
                "select status from footprint_events where request_id = %s"
                " order by happened_on desc, recorded_at desc, id desc limit 1",
                (rid,),
            ).fetchone()
            conn.execute(
                "update footprint_requests set status = %s, updated_at = now() where id = %s",
                (before[0] if before else "draft", rid),
            )
            conn.execute("update footprint_companies set updated_at = now() where id = %s", (owned[0],))
    return str(owned[0]), removed is not None


def delete_footprint_request(user_id: str, request_id: str) -> str | None:
    """Delete one of the user's requests and its history. Returns its company id, or None."""
    with connect() as conn, conn.transaction():
        row = conn.execute(
            "delete from footprint_requests r using footprint_companies c"
            " where r.id = %s and c.id = r.company_id and c.user_id = %s returning r.company_id",
            (uuid.UUID(request_id), uuid.UUID(user_id)),
        ).fetchone()
        if row:
            conn.execute("update footprint_companies set updated_at = now() where id = %s", (row[0],))
    return str(row[0]) if row else None
