"""Local accounts: password hashing, session tokens, login throttling and reset codes.
Standard library only.

Accounts live in the local Postgres next to saved scans. Nothing here talks to the network.

- Passwords are scrypt hashes with a random salt each. The plain password is never stored or logged.
- A login creates a random session token. The browser keeps it in an httpOnly cookie; the database
  keeps only its SHA-256 (db.py), so a copy of the database can't be used to log in.
- Two roles. The first account made on this laptop is the admin; admins can change roles, remove
  accounts and create password reset codes. The last admin can't be demoted or removed.
- Forgotten passwords: there's no email sending for accounts, so an admin creates a one-time code
  and hands it over in person. Codes expire after RESET_MINUTES, work once, and only their hash is
  stored. Changing or resetting a password ends the account's other sessions.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from contextvars import ContextVar

COOKIE = "h84_session"
RESET_MINUTES = 30
# No 0/O or 1/I/L, so a code read aloud or copied off a screen isn't mistyped.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Failed password checks per account email: after MAX_FAILURES within FAILURE_WINDOW seconds, wait.
MAX_FAILURES = 5
FAILURE_WINDOW = 300
_failures: dict[str, deque[float]] = defaultdict(deque)

# The signed-in account for the API request being handled. main.py's session middleware sets it,
# and db.py uses it to keep saved scans per account. None outside a request (scripts, tests).
CURRENT_USER: ContextVar[str | None] = ContextVar("current_user", default=None)


def current_user() -> str | None:
    return CURRENT_USER.get()


# ---------- passwords and tokens ----------

_N, _R, _P = 2**14, 8, 1  # scrypt cost


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P)
    except ValueError:
        return False
    return hmac.compare_digest(check.hex(), digest)


# Checked when an email has no account, so a wrong email takes as long as a wrong password and
# response times don't reveal which emails have accounts.
DUMMY_HASH = hash_password(secrets.token_hex(8))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What the database keeps for a session token or reset code."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_reset_code() -> str:
    """12 characters (~59 bits) in groups of four, e.g. "K7QM-2XRP-9HTD"."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def normalize_code(code: str) -> str:
    """Accept a code typed with spaces, without dashes or in lower case."""
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


# ---------- throttling ----------
# In memory, per email. It slows guessing a password or a reset code; a restart clears it.


def throttled(key: str) -> bool:
    attempts = _failures.get(key)
    if not attempts:
        return False
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILURE_WINDOW:
        attempts.popleft()
    if not attempts:
        del _failures[key]
        return False
    return len(attempts) >= MAX_FAILURES


def record_failure(key: str) -> None:
    _failures[key].append(time.monotonic())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)
