"""Has a bill's legislative session already ended? (pure, no DB)

We don't store bill status or last-action dates, but the session is in the
source URL, and once a part-time legislature adjourns for the last year of
its session, every bill still pending in that session is dead. The digest's
"Worth watching" list uses this to skip those bills.

Only Open States URLs are parsed (the bulk of off-season early-stage items).
Anything we can't read returns False: an unknown bill stays listed rather
than being hidden by a guess.
"""

import re
from datetime import datetime

# Legislatures that keep meeting until the end of the session's last year,
# so a pending bill there can still pass in the fall.
YEAR_ROUND = {"PA", "NJ", "MA", "MI", "OH", "IL", "NC", "NY", "DC", "US"}

# (month, day) after which a part-time legislature's final-year bills are
# dead. Every part-time legislature adjourns by the end of June; California
# sits through Aug 31, and the governor has until Sep 30 to sign.
DEFAULT_CUTOFF = (7, 1)
CUTOFF = {"CA": (10, 1)}

# Open States uses the legislature number for Maine: the 132nd sits 2025-2026.
_NUMBERED = {"ME": lambda n: 2 * n + 1762}

_OPENSTATES = re.compile(r"openstates\.org/([a-z]{2})/bills/([^/]+)/", re.I)


def session_end_year(source_url: str | None) -> tuple[str, int] | None:
    """('IA', 2026) for .../ia/bills/2025-2026/SF2225/, or None if unknown."""
    m = _OPENSTATES.search(source_url or "")
    if not m:
        return None
    state, session = m.group(1).upper(), m.group(2)
    # "2026", "2025-2026", "20252026" (California), "2025A" (special session)
    years = re.findall(r"\d{4}", session)
    if years:
        return state, int(years[-1])
    if session.isdigit() and state in _NUMBERED:
        return state, _NUMBERED[state](int(session))
    return None


def session_over(source_url: str | None, today: datetime) -> bool:
    """True when the bill's session has ended, so a pending bill is dead."""
    parsed = session_end_year(source_url)
    if parsed is None:
        return False
    state, end_year = parsed
    if end_year < today.year:
        return True
    if end_year > today.year or state in YEAR_ROUND:
        return False
    month, day = CUTOFF.get(state, DEFAULT_CUTOFF)
    return (today.month, today.day) >= (month, day)
