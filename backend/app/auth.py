"""Local accounts: sign up, log in, and two roles (user, admin). Everything stays in the local
Postgres, like the rest of the user data.

- Usernames only, no email: the app shouldn't collect more personal data than it needs.
- Passwords are hashed with scrypt (Python's standard library) and a random salt per user.
  The plain password is never stored or logged.
- A login creates a random session token. The browser keeps it in an httpOnly cookie, and
  the database keeps only its SHA-256, so a copy of the database can't be used to log in.
- The first account created becomes the admin. Admins can change roles and delete users.
- Forgotten passwords: there's no email, so an admin creates a one-time reset code and
  hands it to the user in person. Codes expire after RESET_MINUTES, work once, and only
  their hash is stored. Changing or resetting a password logs out the user's other sessions.
"""

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from app import db
from app.context import current_user_id

COOKIE = "hack1984_session"
SESSION_DAYS = 7
RESET_MINUTES = 30
# No 0/O or 1/I/L, so a code read aloud or copied off a screen isn't mistyped.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}  # ~50 ms per hash: slow for guessing, fine for a login

# Routes anyone can call. /api/auth/me answers 401 itself when nobody is logged in.
PUBLIC_PATHS = {
    "/api/status", "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    "/api/auth/reset",
}

# Failed logins per username: after MAX_FAILURES within FAILURE_WINDOW seconds, wait.
MAX_FAILURES = 5
FAILURE_WINDOW = 300
_failures: dict[str, deque[float]] = defaultdict(deque)


# ---------- passwords and tokens (pure) ----------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# Checked against when the username doesn't exist, so a wrong username takes as long as a
# wrong password and response times don't reveal which usernames exist.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_reset_code() -> str:
    """12 characters (~59 bits) in groups of four, e.g. "K7QM-2XRP-9HTD"."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def normalize_code(code: str) -> str:
    """Accept a code typed with spaces, without dashes or in lower case."""
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


# ---------- login throttling ----------


def check_throttle(username: str) -> None:
    attempts = _failures[username]
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILURE_WINDOW:
        attempts.popleft()
    if len(attempts) >= MAX_FAILURES:
        raise HTTPException(429, "Too many failed logins. Wait a few minutes and try again.")


def record_failure(username: str) -> None:
    _failures[username].append(time.monotonic())


def clear_failures(username: str) -> None:
    _failures.pop(username, None)


# ---------- request helpers ----------


async def user_from_request(request: Request) -> dict[str, Any] | None:
    """The logged-in user for this request's cookie, or None. Raises 503 if Postgres is down."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        return await asyncio.to_thread(db.user_for_session, token_hash(token))
    except Exception:
        raise HTTPException(503, "Logging in needs the local database. Start it with `docker compose up -d`.") from None


async def require_user(request: Request) -> dict[str, Any] | None:
    """App-wide dependency: every route except PUBLIC_PATHS needs a logged-in user. Sets
    current_user_id so the scan session and the outbound log are per user."""
    if request.url.path in PUBLIC_PATHS:
        return None
    user = await user_from_request(request)
    if user is None:
        raise HTTPException(401, "Log in first.")
    request.state.user = user
    current_user_id.set(user["id"])
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if user is None or user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do that.")
    return user
