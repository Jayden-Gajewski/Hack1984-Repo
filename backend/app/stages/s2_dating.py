"""Stage 2: date each exposure. OWNER: Evidence.

"Public by" is the earliest Wayback snapshot: set public_by, public_by_source="wayback" and
public_by_evidence_url (clients/wayback.py has earliest_snapshot, snapshot_url and
timestamp_to_date). No snapshot: use the search API's published_date with source
"published_date". Neither: leave public_by as None with source "unknown". Never guess.

Reference: `git show 2f13f74:server/stages/2-dates.js`.
"""

from app.models import Exposure


async def date_exposures(exposures: list[Exposure]) -> tuple[list[Exposure], list[str]]:
    """Return (exposures with dates, errors). A Wayback timeout leaves that date "unknown"."""
    raise NotImplementedError
