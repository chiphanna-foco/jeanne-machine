"""Alert policy — what's worth pinging the legal team about, right now.

The product rule (from TurboTenant, 2026-06-11): alert only on things that
make an immediate impact on landlords within the next ~3-6 months. A bill
that isn't approved yet — and that would still leave six months to react even
if it were approved — is TRACKED (dashboard, triage buckets) but NOT posted.
Keep legal informed without overwhelming them.

Everything still gets ingested and classified (recall-first); this gate only
controls Slack pushes. Pure functions, no DB.
"""

from datetime import datetime, timedelta

# Effective dates this far ahead are still "react now" territory.
ALERT_HORIZON_DAYS = 180
# Recently-effective laws are still alert-worthy this long after the date —
# they're binding NOW and may have been surfaced late.
RECENT_GRACE_DAYS = 90


def should_alert(
    action_needed: str | None,
    effective_date: datetime | None,
    today: datetime,
) -> bool:
    """True if this item merits an immediate Slack ping.

    - urgent → yes (the summarizer reserves this for enacted/imminent laws).
    - any item whose effective date falls inside [today-90d, today+180d] → yes,
      regardless of label (a known effective date inside the window is the
      strongest "act now" signal there is).
    - everything else → tracked silently. The dashboard triage view and the
      weekly digest carry the watchlist; alerts carry only the act-now slice.
    """
    if action_needed == "urgent":
        return True
    if effective_date is not None:
        eff = effective_date.replace(tzinfo=None)
        now = today.replace(tzinfo=None)
        if now - timedelta(days=RECENT_GRACE_DAYS) <= eff <= now + timedelta(days=ALERT_HORIZON_DAYS):
            return True
    return False


def alert_sort_key(item: dict) -> tuple:
    """Soonest-binding first: urgent label, then nearest effective date, then impact."""
    urgency = 0 if item.get("action_needed") == "urgent" else 1
    eff = item.get("effective_date")
    eff_key = str(eff) if eff else "9999"
    impact = {"high": 0, "med": 1, "low": 2}.get(item.get("impact_score"), 3)
    return (urgency, eff_key, impact)
