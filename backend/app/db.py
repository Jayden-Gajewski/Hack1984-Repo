"""PostgreSQL access. The database runs locally in Docker (docker-compose.yml at the repo root).

It stores saved scans, so "load last scan" still works if the venue Wi-Fi dies, and the
email aliases from Stage 7. The rows hold personal data: the database stays on this
laptop and nothing from it is committed.

This uses psycopg's sync API on purpose; call it through asyncio.to_thread(). psycopg's
async mode doesn't work with the default event loop on Windows.
"""

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

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
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, autocommit=True, connect_timeout=3)


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


def save_scan(scan_id: str, request: dict[str, Any], response: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "insert into scans (id, request, response) values (%s, %s, %s)",
            (uuid.UUID(scan_id), Jsonb(request), Jsonb(response)),
        )


def latest_scan() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (request, response) for the most recent saved scan, or None if there isn't one."""
    with connect() as conn:
        row = conn.execute(
            "select request, response from scans order by created_at desc limit 1"
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
