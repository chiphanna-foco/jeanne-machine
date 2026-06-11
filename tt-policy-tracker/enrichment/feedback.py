"""Pure helpers for applying 👍/👎/👀 feedback to item lists.

Kept DB-free so they're easy to test; the API supplies the feedback map
(latest label per canonical bill key) loaded from the item_feedback table.

The loop mirrors the TT-LLM signal_layer: a 👎 ("down") suppresses the item
from lists/digests on every subsequent view, and precision = up/(up+down) is
the trust metric.
"""

from collections.abc import Iterable

from enrichment.triage import canonical_bill_key


def annotate_and_suppress(
    items: list[dict],
    feedback_map: dict[str, str],
    include_dismissed: bool = False,
) -> list[dict]:
    """Tag each item with its current ``feedback`` label and drop 👎'd ones.

    feedback_map: {bill_key: label} — the latest label per canonical bill key.
    include_dismissed: when True, keep 👎'd items (tagged) instead of hiding
    them — for a "show dismissed" toggle.
    """
    out: list[dict] = []
    for it in items:
        key = canonical_bill_key(it.get("source_url"), it.get("external_id"))
        label = feedback_map.get(key) if key else None
        if label == "down" and not include_dismissed:
            continue
        out.append({**it, "feedback": label, "bill_key": key})
    return out


def precision(labels: Iterable[str]) -> float | None:
    """up / (up + down) over the given labels. None if no up/down yet."""
    up = sum(1 for v in labels if v == "up")
    down = sum(1 for v in labels if v == "down")
    return up / (up + down) if (up + down) else None
