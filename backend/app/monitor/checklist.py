"""The recommended steps for an incident, its one-line threat label and its risks. Pure.

Steps come from the categories of data exposed (data/breach_data_classes.json), most severe
first, plus "read the official notice" when there is one and "watch the account" always. A
step marked done is the user's own record; it never means the account is secure.
"""

from typing import Any

from app.models import SecurityAction
from app.monitor import breach_data

UNKNOWN_DATA_STEPS = ("change_password", "enable_2fa", "phishing_watch")
MAX_RISKS = 5


def steps(categories: list[str], company: str, progress: dict[str, str], official_url: str | None) -> list[SecurityAction]:
    keys: list[str] = ["read_notice"] if official_url else []
    for key in categories or []:
        keys += breach_data.category(key)["actions"]
    if not categories:
        keys += UNKNOWN_DATA_STEPS
    keys.append("monitor_activity")

    out = []
    for key in dict.fromkeys(keys):
        spec: dict[str, Any] = breach_data.action(key)
        out.append(
            SecurityAction(
                id=key,
                text=spec["text"].format(company=company),
                why=spec["why"],
                link=official_url if key == "read_notice" else spec.get("link"),
                done=key in progress,
                done_at=progress.get(key),
            )
        )
    return out


def threat_label(categories: list[str]) -> str:
    """"Passwords and email addresses exposed": the two most severe kinds of data."""
    if not categories:
        return "Breach reported; exposed data not yet known"
    labels = [breach_data.label(c) for c in categories[:2]]
    if len(labels) == 2:
        labels[1] = breach_data.sentence_label(categories[1])
    return " and ".join(labels) + " exposed"


def risks(categories: list[str]) -> list[str]:
    out: list[str] = []
    for key in categories:
        for risk in breach_data.category(key)["risks"]:
            if risk not in out:
                out.append(risk)
    return out[:MAX_RISKS]
