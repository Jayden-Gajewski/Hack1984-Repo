"""Monitored emails: proof of ownership, then the hashed HIBP check.

Ownership: a 6-digit code is emailed to the address through the SMTP server set in .env
(outbound.send_mail, logged with the code redacted). Only a hash of the code is stored; it
expires after 15 minutes and allows 5 tries. Without SMTP settings an address can be added
but is never verified or checked.

An address that's never verified is deleted a day after its last code expired. Once verified,
the address itself is deleted: only its SHA-1 hash (needed for the check) and a
masked form for display ("j•••e@example.com") are kept in backend/local/monitor.json.

The check: HIBP's k-anonymity search gets the first 6 characters of the hash, and answers with
every hash suffix under that prefix. The one matching this address is kept; the rest are
discarded immediately, as HIBP's terms require, and never stored or logged.
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app import outbound
from app.clients import hibp
from app.config import get_settings
from app.models import MonitoredEmail
from app.monitor import store

log = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)
UNVERIFIED_TTL = timedelta(hours=24)
MAX_RETRY_WAIT = 10  # seconds; a longer HIBP rate-limit wait is reported instead of waited out
NO_SMTP = (
    "Email verification needs an SMTP server in .env (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, "
    "SMTP_PASSWORD, SMTP_FROM). Until then this address can't be verified or checked."
)
_sleep = asyncio.sleep  # tests replace this


def sha1_hex(address: str) -> str:
    return hashlib.sha1(address.strip().lower().encode("utf-8")).hexdigest().upper()


def mask(address: str) -> str:
    local, _, domain = address.partition("@")
    if len(local) <= 2:
        return f"{local[:1]}•@{domain}"
    return f"{local[0]}•••{local[-1]}@{domain}"


def _hash_code(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def view(record: dict[str, Any]) -> MonitoredEmail:
    check = record.get("check") or {}
    code = record.get("code") or {}
    return MonitoredEmail(
        id=record["id"],
        display=record["display"],
        added_at=record["added_at"],
        verified=bool(record.get("verified_at")),
        verified_at=record.get("verified_at"),
        code_sent_at=code.get("sent_at"),
        code_expires_at=code.get("expires_at"),
        check_status=check.get("status", "never"),
        check_message=check.get("message", ""),
        last_checked=check.get("checked_at"),
        breaches_found=len(check.get("breaches") or []),
    )


def prune_unverified(data: dict[str, Any], now: datetime | None = None) -> int:
    """Delete addresses that were never verified, UNVERIFIED_TTL after their last code expired
    (or after they were added, if no code was ever sent). An unverified address is the only
    place the monitor keeps an email in plain text, so it shouldn't linger."""
    now = now or datetime.now(timezone.utc)
    keep, dropped = [], 0
    for record in data["emails"]:
        if record.get("verified_at"):
            keep.append(record)
            continue
        since = _parse((record.get("code") or {}).get("expires_at")) or _parse(record.get("added_at"))
        if since and now - since > UNVERIFIED_TTL:
            dropped += 1
        else:
            keep.append(record)
    if dropped:
        data["emails"] = keep
        store.add_event(data, "email", f"Removed {dropped} unverified address{'es' if dropped != 1 else ''} after a day without verification.")
    return dropped


def _find(data: dict[str, Any], email_id: str) -> dict[str, Any]:
    record = next((e for e in data["emails"] if e["id"] == email_id), None)
    if record is None:
        raise LookupError("No monitored email with that id.")
    return record


async def add(address: str) -> MonitoredEmail:
    """Add an address and, if SMTP is set up, send its code. `address` is already validated."""
    digest = sha1_hex(address)
    async with store.edit() as data:
        prune_unverified(data)
        if any(e.get("address") == address or e.get("sha1") == digest for e in data["emails"]):
            raise ValueError("You're already monitoring that address.")
        record = {
            "id": f"em-{secrets.token_hex(4)}",
            "address": address,  # deleted once verified
            "sha1": None,
            "display": address,
            "added_at": store.now(),
            "verified_at": None,
            "code": None,
            "check": {"status": "never", "message": "", "checked_at": None, "breaches": []},
        }
        data["emails"].append(record)
        store.add_event(data, "email", f"Added {mask(address)}. It needs verifying before it's checked.")
    if get_settings().smtp_configured:
        try:
            return await send_code(record["id"])
        except Exception as exc:  # added, but the code didn't go out; the UI offers "send again"
            # Only the error type: SMTP errors can carry the recipient address in their text.
            log.warning("Verification code not sent (%s).", type(exc).__name__)
    return view(record)


async def send_code(email_id: str) -> MonitoredEmail:
    settings = get_settings()
    if not settings.smtp_configured:
        raise RuntimeError(NO_SMTP)
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    error = None
    async with store.edit() as data:
        record = _find(data, email_id)
        sent = _parse((record.get("code") or {}).get("sent_at"))
        if record.get("verified_at"):
            error = "That address is already verified."
        elif sent and datetime.now(timezone.utc) - sent < RESEND_AFTER:
            error = "A code was sent less than a minute ago. Check your inbox (and spam), or wait a moment."
        else:
            now = datetime.now(timezone.utc)
            record["code"] = {
                "hash": _hash_code(code, salt),
                "salt": salt,
                "sent_at": now.isoformat(timespec="seconds"),
                "expires_at": (now + CODE_TTL).isoformat(timespec="seconds"),
                "attempts": 0,
            }
            address = record["address"]
    if error:
        raise ValueError(error)

    try:
        await outbound.send_mail(
            purpose="Send an ownership code to the email you added (through your SMTP server)",
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            to=address,
            subject="Your Dossier verification code",
            text=(
                f"Your Dossier verification code is {code}.\n\n"
                "It expires in 15 minutes. Enter it in Dossier's threat monitor to confirm this "
                "address is yours. If you didn't ask for it, ignore this email.\n"
            ),
            secrets=[code],
        )
    except Exception as exc:
        async with store.edit() as data:
            _find(data, email_id)["code"] = None  # so "send again" works right away
        raise RuntimeError(f"Couldn't send the code: {exc}") from exc
    async with store.edit() as data:
        store.add_event(data, "email", f"Sent a verification code to {mask(address)}.")
        return view(_find(data, email_id))


async def verify(email_id: str, code: str) -> MonitoredEmail:
    error = None
    async with store.edit() as data:
        record = _find(data, email_id)
        pending = record.get("code")
        expires = _parse((pending or {}).get("expires_at"))
        if record.get("verified_at"):
            return view(record)
        if not pending:
            error = "Ask for a code first."
        elif expires is None or datetime.now(timezone.utc) > expires:
            record["code"] = None
            error = "That code expired. Ask for a new one."
        elif pending["attempts"] >= MAX_ATTEMPTS:
            record["code"] = None
            error = "Too many tries. Ask for a new code."
        else:
            pending["attempts"] += 1
            if hmac.compare_digest(_hash_code(code, pending["salt"]), pending["hash"]):
                address = record["address"]
                record.update(
                    verified_at=store.now(), sha1=sha1_hex(address), display=mask(address), address=None, code=None
                )
                store.add_event(data, "email", f"Verified {record['display']}. Refresh to check it with Have I Been Pwned.")
            else:
                left = MAX_ATTEMPTS - pending["attempts"]
                error = f"That code doesn't match. {left} {'try' if left == 1 else 'tries'} left."
                if left == 0:
                    record["code"] = None
        result = view(record)
    if error:
        raise ValueError(error)
    return result


async def remove(email_id: str) -> None:
    async with store.edit() as data:
        record = _find(data, email_id)
        data["emails"].remove(record)
        store.add_event(data, "email", f"Stopped monitoring {record['display'] if record.get('verified_at') else mask(record['display'])}.")


async def _range(prefix: str) -> list[dict[str, Any]]:
    try:
        return await hibp.range_search(prefix)
    except hibp.HibpError as exc:
        if exc.status == 429 and exc.retry_after is not None and exc.retry_after <= MAX_RETRY_WAIT:
            await _sleep(exc.retry_after)
            return await hibp.range_search(prefix)
        raise


async def check(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """New `check` dicts by email id for every verified email. Never raises: a failure is a
    status ("not_configured", "rate_limited", "error") with a message, and an earlier
    successful result is kept rather than replaced by a guess."""
    verified = [r for r in records if r.get("verified_at") and r.get("sha1")]
    results: dict[str, dict[str, Any]] = {}

    def keep(record: dict[str, Any], status: str, message: str) -> dict[str, Any]:
        previous = record.get("check") or {}
        return {
            "status": status,
            "message": message,
            "checked_at": previous.get("checked_at"),
            "breaches": previous.get("breaches") or [],
        }

    if not verified:
        return results
    if not get_settings().hibp_api_key:
        message = "Add an HIBP Pro key (HIBP_API_KEY) to check this address. Nothing was sent."
        return {r["id"]: keep(r, "not_configured", message) for r in verified}

    by_prefix: dict[str, list[dict[str, Any]]] = {}
    for record in verified:
        by_prefix.setdefault(record["sha1"][:6], []).append(record)

    for prefix, group in by_prefix.items():
        try:
            rows = await _range(prefix)
        except hibp.HibpError as exc:
            status = "rate_limited" if exc.status == 429 else ("not_configured" if exc.status in (401, 403) else "error")
            for record in group:
                results[record["id"]] = keep(record, status, str(exc))
            continue
        except Exception as exc:
            for record in group:
                results[record["id"]] = keep(record, "error", f"Couldn't reach Have I Been Pwned: {exc}")
            continue
        wanted = {r["sha1"][6:] for r in group}
        matches = {
            str(row.get("hashSuffix", "")).upper(): row.get("websites")
            for row in rows
            if str(row.get("hashSuffix", "")).upper() in wanted
        }
        del rows  # every other suffix is discarded here, unread
        checked_at = store.now()
        for record in group:
            names = [n for n in matches.get(record["sha1"][6:]) or [] if isinstance(n, str)]
            results[record["id"]] = {
                "status": "ok",
                "message": (
                    f"Found in {len(names)} breach{'es' if len(names) != 1 else ''} in Have I Been Pwned."
                    if names
                    else "Not found in any breach Have I Been Pwned's hashed search covers."
                ),
                "checked_at": checked_at,
                "breaches": names,
            }
    return results
