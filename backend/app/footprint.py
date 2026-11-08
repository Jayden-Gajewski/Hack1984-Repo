"""Digital footprint: the companies a user tracks, and the data requests they make to them.

Dossier only keeps the user's own records here. It never sends a request, never contacts a
company and never changes a company's settings: the user does those things and records what
happened. Nothing in this module touches the network, and nothing here goes to Gemini.
"""

import re
from datetime import date
from urllib.parse import urlsplit

STATUSES = ("draft", "ready_to_send", "sent", "response_received", "completed", "unable_to_complete")

LABEL = {
    "draft": "Draft",
    "ready_to_send": "Ready to send",
    "sent": "Sent",
    "response_received": "Response received",
    "completed": "Completed",
    "unable_to_complete": "Unable to complete",
}

# The text can change until the user marks the request sent; after that it stays as sent.
EDITABLE = frozenset({"draft", "ready_to_send"})

# Where a request can go next. "Response received" and "Completed" are only reachable once the
# user has marked it sent, so the app never suggests a company got a request nobody sent.
# The backward steps let people correct a mistake; every step stays in the history.
NEXT: dict[str, tuple[str, ...]] = {
    "draft": ("ready_to_send", "sent", "unable_to_complete"),
    "ready_to_send": ("draft", "sent", "unable_to_complete"),
    "sent": ("response_received", "completed", "unable_to_complete", "ready_to_send"),
    "response_received": ("completed", "unable_to_complete", "sent"),
    "completed": ("response_received",),
    "unable_to_complete": ("sent", "draft"),
}


def check_update(current: str, new: str, note: str, happened_on: date, last_on: date | None) -> None:
    """Raise ValueError when recording `new` on a request that is `current` isn't allowed.
    Recording the same status again is a note, so it needs one."""
    if last_on and happened_on < last_on:
        raise ValueError(f"Pick a date on or after {last_on.isoformat()}, the last step you recorded.")
    if new == current:
        if not note:
            raise ValueError("Add a note, or choose a different status.")
        return
    if new not in NEXT[current]:
        if current in EDITABLE and new in ("response_received", "completed"):
            raise ValueError("Mark the request sent before recording a response or completion.")
        raise ValueError(f"A request that is {LABEL[current].lower()} can't be marked {LABEL[new].lower()}.")


# ---------- Websites ----------

_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def normalize_website(value: str) -> str:
    """A website as the user typed it, with https:// added if they left it off. Blank stays blank.
    Anything that isn't a plain http(s) address is refused, so it can't become a script link."""
    value = value.strip()
    if not value:
        return ""
    candidate = value if re.match(r"^https?://", value, re.IGNORECASE) else f"https://{value}"
    parts = urlsplit(candidate)
    if any(ch.isspace() for ch in value) or not parts.hostname or not _HOST.match(parts.hostname):
        raise ValueError("Enter a website like example.com, or leave it blank.")
    return candidate


# ---------- Request drafts ----------
# Plain templates the user reviews, edits and sends themselves. They ask; they don't claim
# legal effect or promise a deadline. A law is only named when the user picks one.

LAW_SENTENCE = {
    "gdpr": {
        "access": "I am making this request under Article 15 of the GDPR (the EU and UK General Data Protection Regulation).",
        "deletion": "I am making this request under Article 17 of the GDPR (the EU and UK General Data Protection Regulation).",
    },
    "ccpa": {
        "access": "I am making this request under the California Consumer Privacy Act (CCPA), as amended by the CPRA.",
        "deletion": "I am making this request under the California Consumer Privacy Act (CCPA), as amended by the CPRA.",
    },
}


def draft(kind: str, law: str, company: str, account_label: str) -> tuple[str, str]:
    """(subject, body) for a request to `company`. [Bracketed] text is for the user to fill in."""
    who = (
        f"You can find my records under: {account_label}"
        if account_label
        else f"You can find my records under: [the email address, username or account number I use with {company}]"
    )
    if kind == "access":
        subject = "Request for a copy of my personal data"
        paragraphs = [
            f"Hello {company} privacy team,",
            f"I am asking for a copy of the personal data {company} holds about me.",
            who,
            "Please send me:\n"
            "- a copy of the personal data you hold about me\n"
            "- where you got it, if not from me\n"
            "- the companies you have shared it with or sold it to",
        ]
    else:
        subject = "Request to delete my account and personal data"
        paragraphs = [
            f"Hello {company} privacy team,",
            f"I am asking {company} to delete my account and the personal data you hold about me.",
            who,
            "Please also pass this request on to any company you have shared or sold my data to, "
            "and let me know once it is done.",
        ]
    if law in LAW_SENTENCE:
        paragraphs.append(LAW_SENTENCE[law][kind])
    paragraphs.append("Thank you,\n[Your name]")
    return subject, "\n\n".join(paragraphs)
