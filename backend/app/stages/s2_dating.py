"""Stage 2: date each exposure. OWNER: Evidence.

"Public by" for each listing, in this order (spec in backend/app/stages/CLAUDE.md):
1. The earliest Wayback snapshot of the listing URL: public_by_source="wayback", with the
   snapshot link in public_by_evidence_url.
2. No snapshot (or archive.org didn't answer): the search API's published_date, with
   public_by_source="published_date".
3. Neither: public_by=None, public_by_source="unknown". Never guess.

The listing URL (which can contain the person's name) goes to archive.org; that's expected
and it shows in the outbound log. clients/wayback.py caps it at 4 requests at once, with a
10 s timeout each, so a slow archive.org delays the scan by seconds, not minutes.

Not built yet (stretch): fetch a few monthly snapshots and record when each field first
appeared, by running the Stage 1 field prompt on them locally.
"""

import asyncio
import re

from app.clients import wayback
from app.models import Exposure

_TIMESTAMP_RE = re.compile(r"\d{14}")  # CDX timestamps: YYYYMMDDhhmmss


def date_from(exposure: Exposure, snapshot: str | None) -> Exposure:
    """Pure: the exposure with its public-by date filled in from the best evidence there is."""
    if snapshot and _TIMESTAMP_RE.fullmatch(snapshot):
        return exposure.model_copy(
            update={
                "public_by": wayback.timestamp_to_date(snapshot),
                "public_by_source": "wayback",
                "public_by_evidence_url": wayback.snapshot_url(snapshot, exposure.url),
            }
        )
    if exposure.published_date:
        return exposure.model_copy(
            update={
                "public_by": exposure.published_date,
                "public_by_source": "published_date",
                "public_by_evidence_url": None,
            }
        )
    return exposure.model_copy(
        update={"public_by": None, "public_by_source": "unknown", "public_by_evidence_url": None}
    )


async def date_exposures(exposures: list[Exposure]) -> tuple[list[Exposure], list[str]]:
    """Return (exposures with dates, errors). A Wayback failure falls back like "no snapshot"."""
    snapshots = await asyncio.gather(
        *(
            wayback.earliest_snapshot(
                e.url, purpose=f"Ask the Wayback Machine when the {e.broker} listing was first archived"
            )
            for e in exposures
        ),
        return_exceptions=True,
    )
    dated: list[Exposure] = []
    failed = 0
    for exposure, snapshot in zip(exposures, snapshots):
        if isinstance(snapshot, Exception):
            failed += 1
            snapshot = None
        dated.append(date_from(exposure, snapshot))

    errors = []
    if failed:
        errors.append(
            f"The Wayback Machine didn't answer for {failed} of {len(exposures)} listings, so their "
            "dates use the published date where there is one, or say unknown."
        )
    return dated, errors
