"""PostgreSQL access. The database runs locally in Docker (docker-compose.yml at the repo root).

It stores saved scans, so "load last scan" still works if the venue Wi-Fi dies, the
email aliases from Stage 7, and local accounts (usernames, password hashes, roles and
hashed session tokens; see auth.py). The rows hold personal data: the database stays on this
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

create table if not exists users (
    id            serial primary key,
    username      text not null unique,
    password_hash text not null,
    role          text not null default 'user' check (role in ('user', 'admin')),
    created_at    timestamptz not null default now()
);

create table if not exists sessions (
    token_hash text primary key,
    user_id    integer not null references users(id) on delete cascade,
    expires_at timestamptz not null
);

-- One-time codes an admin creates for a user who forgot their password. Hashed, like sessions.
create table if not exists password_resets (
    code_hash  text primary key,
    user_id    integer not null references users(id) on delete cascade,
    expires_at timestamptz not null
);

-- Each saved scan belongs to the user who ran it. Scans saved before accounts existed have
-- no owner and are never returned.
alter table scans add column if not exists user_id integer references users(id) on delete cascade;

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


def save_scan(scan_id: str, request: dict[str, Any], response: dict[str, Any], user_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "insert into scans (id, request, response, user_id) values (%s, %s, %s, %s)",
            (uuid.UUID(scan_id), Jsonb(request), Jsonb(response), user_id),
        )


def find_scan(name: str, city: str, state: str, user_id: int) -> tuple[str, dict[str, Any]] | None:
    """(saved-at ISO timestamp, response) for this user's newest saved scan of this person, or
    None. Matches name and city ignoring case and extra spaces, and the state code exactly."""
    with connect() as conn:
        row = conn.execute(
            """
            select created_at, response from scans
            where lower(regexp_replace(trim(request->>'name'), '\\s+', ' ', 'g')) = %s
              and lower(regexp_replace(trim(request->>'city'), '\\s+', ' ', 'g')) = %s
              and upper(request->>'state') = %s
              and user_id = %s
            order by created_at desc
            limit 1
            """,
            (_squash(name), _squash(city), state.upper(), user_id),
        ).fetchone()
    return (row[0].isoformat(), row[1]) if row else None


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def latest_scan(user_id: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (request, response) for this user's most recent saved scan, or None."""
    with connect() as conn:
        row = conn.execute(
            "select request, response from scans where user_id = %s order by created_at desc limit 1",
            (user_id,),
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


# ---------- accounts (see auth.py) ----------

_USER_COLUMNS = "id, username, role, created_at"


def _user(row: Any) -> dict[str, Any]:
    return {"id": row[0], "username": row[1], "role": row[2], "created_at": row[3].isoformat()}


def create_user(username: str, password_hash: str) -> dict[str, Any] | None:
    """Create an account. The first account ever becomes the admin. Returns None if the
    username is taken."""
    with connect() as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(1984)")  # two first sign-ups can't both be admin
        try:
            row = conn.execute(
                f"""
                insert into users (username, password_hash, role)
                values (%s, %s, case when exists (select 1 from users) then 'user' else 'admin' end)
                returning {_USER_COLUMNS}
                """,
                (username, password_hash),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            return None
    return _user(row)


def user_with_hash(username: str) -> tuple[dict[str, Any], str] | None:
    """(user, password hash) for a login check, or None if there's no such user."""
    with connect() as conn:
        row = conn.execute(
            f"select {_USER_COLUMNS}, password_hash from users where username = %s", (username,)
        ).fetchone()
    return (_user(row), row[4]) if row else None


def create_session(token_hash: str, user_id: int, days: int) -> None:
    with connect() as conn:
        conn.execute("delete from sessions where expires_at < now()")  # tidy up old logins
        conn.execute(
            "insert into sessions (token_hash, user_id, expires_at) values (%s, %s, now() + %s * interval '1 day')",
            (token_hash, user_id, days),
        )


def user_for_session(token_hash: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            f"""
            select {", ".join("u." + c.strip() for c in _USER_COLUMNS.split(","))}
            from sessions s join users u on u.id = s.user_id
            where s.token_hash = %s and s.expires_at > now()
            """,
            (token_hash,),
        ).fetchone()
    return _user(row) if row else None


def delete_session(token_hash: str) -> None:
    with connect() as conn:
        conn.execute("delete from sessions where token_hash = %s", (token_hash,))


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(f"select {_USER_COLUMNS} from users order by id").fetchall()
    return [_user(r) for r in rows]


def set_role(user_id: int, role: str) -> dict[str, Any] | None:
    """Change a user's role, refusing to demote the last admin. Returns the updated user, or
    None if there's no such user. Raises ValueError for the last admin."""
    with connect() as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(1984)")
        if role != "admin" and _is_last_admin(conn, user_id):
            raise ValueError("That's the only admin. Make someone else an admin first.")
        row = conn.execute(
            f"update users set role = %s where id = %s returning {_USER_COLUMNS}", (role, user_id)
        ).fetchone()
    return _user(row) if row else None


def delete_user(user_id: int) -> bool:
    """Delete a user with their sessions and saved scans. Refuses the last admin (ValueError).
    Returns False if there's no such user."""
    with connect() as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(1984)")
        if _is_last_admin(conn, user_id):
            raise ValueError("That's the only admin. Make someone else an admin first.")
        return conn.execute("delete from users where id = %s", (user_id,)).rowcount > 0


def _is_last_admin(conn: psycopg.Connection, user_id: int) -> bool:
    row = conn.execute(
        "select count(*) filter (where role = 'admin'), bool_or(id = %s and role = 'admin') from users",
        (user_id,),
    ).fetchone()
    return bool(row[1]) and row[0] <= 1


# ---------- passwords ----------


def password_hash_for(user_id: int) -> str | None:
    with connect() as conn:
        row = conn.execute("select password_hash from users where id = %s", (user_id,)).fetchone()
    return row[0] if row else None


def set_password(user_id: int, password_hash: str, keep_session: str | None = None) -> None:
    """Store a new password hash and log out every session of this user except keep_session
    (the token hash of the login that made the change, if any). Unused reset codes go too."""
    with connect() as conn, conn.transaction():
        conn.execute("update users set password_hash = %s where id = %s", (password_hash, user_id))
        conn.execute(
            "delete from sessions where user_id = %s and token_hash is distinct from %s",
            (user_id, keep_session),
        )
        conn.execute("delete from password_resets where user_id = %s", (user_id,))


def create_reset(code_hash: str, user_id: int, minutes: int) -> str:
    """Store a reset code for a user, replacing any earlier one. Returns its expiry (ISO)."""
    with connect() as conn, conn.transaction():
        conn.execute("delete from password_resets where user_id = %s or expires_at < now()", (user_id,))
        row = conn.execute(
            "insert into password_resets (code_hash, user_id, expires_at) "
            "values (%s, %s, now() + %s * interval '1 minute') returning expires_at",
            (code_hash, user_id, minutes),
        ).fetchone()
    return row[0].isoformat()


def use_reset(code_hash: str, username: str) -> int | None:
    """Spend a reset code: the user id if the code is valid, unexpired and belongs to this
    username, else None. A valid code works once."""
    with connect() as conn:
        row = conn.execute(
            """
            delete from password_resets r using users u
            where r.code_hash = %s and r.user_id = u.id and u.username = %s and r.expires_at > now()
            returning r.user_id
            """,
            (code_hash, username),
        ).fetchone()
    return row[0] if row else None
