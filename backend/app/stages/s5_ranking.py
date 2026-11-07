"""Stage 5: rank likely sources. OWNER: Local LLM & ranking.

Pure function: no network calls, so unit-test it with fixtures in backend/tests/.
- proven:   an alias given only to company X got mail from someone else.
- likely:   a breach at X falls 0 to 3 years before the listing's public_by date AND exposed
            at least one field the listing shows. An unknown date can't support it.
- possible: X's privacy policy allows selling or sharing data.
Keep one lead per company at its strongest tier, with every reason written as a sentence that
cites dates and their sources. Sort proven, likely, possible. Say "likely source", never
"leaked by" or "who leaked it".

Reference: `git show 2f13f74:server/stages/5-rank.js`.
"""

from app.models import AliasHit, BreachEvent, Exposure, PolicyResult


def rank_sources(
    exposures: list[Exposure],
    breaches: list[BreachEvent],
    policies: list[PolicyResult],
    alias_hits: list[AliasHit],
) -> list[Exposure]:
    """Return the exposures with `leads` filled in, strongest first."""
    raise NotImplementedError
