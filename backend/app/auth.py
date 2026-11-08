"""Local accounts: password hashing and session tokens. Standard library only.

Accounts live in the local Postgres next to saved scans. Nothing here talks to the network.
"""

import hashlib
import hmac
import secrets
from contextvars import ContextVar

COOKIE = "h84_session"

# The signed-in account for the API request being handled. main.py's session middleware sets it,
# and db.py uses it to keep saved scans per account. None outside a request (scripts, tests).
CURRENT_USER: ContextVar[str | None] = ContextVar("current_user", default=None)


def current_user() -> str | None:
    return CURRENT_USER.get()
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


def new_token() -> str:
    return secrets.token_urlsafe(32)
