"""AI law synthesizer — generates per-(jurisdiction, topic) "current state of law" summaries.

Given the set of PolicyItems we've collected for a specific jurisdiction + topic,
this asks Sonnet to synthesize a narrative of what the law currently looks like,
what's changed recently, and what's pending.

IMPORTANT: This is not a substitute for statutory research. Summaries reflect
only the policy activity we've observed via our feeds. We flag this in the
caveats field of every snapshot.
"""

import logging
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from enrichment.claude_client import create_json
from storage.models import Jurisdiction, LawSnapshot, PolicyItem

logger = logging.getLogger(__name__)

# The 10 canonical topics we track
TOPICS = [
    "landlord_tenant_law",
    "security_deposit",
    "eviction",
    "source_of_income",
    "rental_registration",
    "screening_restrictions",
    "application_fee_limit",
    "rent_control",
    "habitability",
    "fair_housing",
]

TOPIC_LABELS = {
    "landlord_tenant_law": "Landlord-Tenant Law (general)",
    "security_deposit": "Security Deposit Rules",
    "eviction": "Eviction Procedures",
    "source_of_income": "Source-of-Income Discrimination",
    "rental_registration": "Rental Registration / Licensing",
    "screening_restrictions": "Tenant Screening Restrictions",
    "application_fee_limit": "Application Fee Limits",
    "rent_control": "Rent Control / Stabilization",
    "habitability": "Habitability Standards",
    "fair_housing": "Fair Housing",
}


SYNTHESIZER_SYSTEM_PROMPT = """You are a rental housing policy analyst. Given a set of recent policy items (bills, regulations, court rulings) for a specific jurisdiction and topic, synthesize a concise summary of what the current law looks like based on this evidence.

Guidelines:
- Focus on what is currently in effect vs. what is proposed/pending.
- Note conflicting or rapidly changing areas.
- Be honest about gaps — say "based on observed activity, the law appears to..." rather than "the law is..." when uncertain.
- Cite a statute, code section, regulation or public law ONLY if that exact reference appears in the source items below. Never add a citation from memory, even one you are sure of. If the items cite nothing, return an empty "statutory_references" list and name no statute anywhere in the output.
- Keep the summary to 3-5 sentences.
- Produce 3-6 key bullet facts.

Respond with ONLY valid JSON (no markdown):
{
  "headline": "One-sentence headline, ≤120 chars",
  "summary": "3-5 sentence narrative describing current state and recent trend",
  "key_facts": ["bullet 1", "bullet 2", "bullet 3"],
  "statutory_references": ["CO Rev Stat § 38-12-103", ...],
  "confidence": "low|med|high",
  "caveats": "1-sentence warning about data limitations, if any"
}

Confidence scale:
- "high" = multiple consistent sources over time, clear direction
- "med" = single strong source OR multiple items but partial information
- "low" = only 1-2 items, or conflicting information, or very narrow coverage"""


# Statute-like references: section signs, U.S.C./C.F.R., state code names,
# public laws. Each match ends in a section number; that number is what we
# look for in the input. Bill numbers (HB 1234) are not citations of law and
# are left alone, and a bare year after a code name ("Laws 2024") is not a
# section number.
_SECTION = r"\d[\w.:\-]*(?:\([\w.]+\))*"
_NOT_A_YEAR = r"(?!(?:19|20)\d\d(?![\w.:\-]))"
CITATION_RE = re.compile(
    r"(?:§§?\s*" + _SECTION
    + r"|\b\d+\s+(?:U\.?\s?S\.?\s?C|C\.?\s?F\.?\s?R)\.?\s*(?:§§?\s*)?" + _SECTION
    + r"|\b(?:Rev(?:ised)?\.?\s+Stat(?:utes)?|Gen(?:eral)?\.?\s+Stat(?:utes)?|Stat(?:utes)?\.?"
    + r"|Code|Laws|RCW|ORS|ILCS|CRS|MCL|RSA)\.?\s*(?:Ann\.?\s*)?(?:§§?\s*)?"
    + _NOT_A_YEAR + _SECTION
    + r"|\b(?:Public\s+Law|Pub\.\s*L\.)\s*(?:No\.\s*)?\d+-\d+)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d[\w.:\-]*(?:\([\w.]+\))*$")
UNSUPPORTED_MARK = "[citation removed: not in source items]"


def _normalize(text: str) -> str:
    """Lowercase, with en and em dashes turned into '-'."""
    return (text or "").replace("\u2013", "-").replace("\u2014", "-").lower()


def _citation_key(citation: str) -> str:
    """The section number at the end of a citation, e.g. '38-12-103'."""
    m = _NUMBER_RE.search(citation.strip().rstrip(".,;"))
    return (m.group(0) if m else citation).rstrip(".")


def _has_token(source: str, number: str) -> bool:
    """True when `number` appears in `source` as a whole token.

    '§ 8' must not pass on the 8 in '38-12-108'.
    """
    pattern = r"(?<![\w.\-])" + re.escape(number) + r"(?![\w\-]|\.\w)"
    return re.search(pattern, source) is not None


def unsupported_citations(text: str, source: str) -> list[str]:
    """Citations in `text` whose section number does not appear in `source`."""
    source_n = _normalize(source)
    source_keys = set()
    for m in CITATION_RE.finditer(source_n):
        k = _citation_key(m.group(0))
        source_keys.update({k, k.split("(", 1)[0]})
    bad = []
    for m in CITATION_RE.finditer(_normalize(text)):
        key = _citation_key(m.group(0))
        # A subsection of a cited section counts: 3604(b) is fine if 3604 is there.
        base = key.split("(", 1)[0]
        if key in source_keys or base in source_keys:
            continue
        # A multi-part number (38-12-103, 59.18.280) is specific enough to
        # match anywhere in the source as a whole token. A bare number like
        # 8 must match a citation in the source, not "HB 8".
        if re.search(r"[.\-:]", base) and (
            _has_token(source_n, key) or _has_token(source_n, base)
        ):
            continue
        bad.append(m.group(0))
    return bad


def _strip(text: str, source: str, removed: list[str]) -> str:
    """Replace each unsupported citation in `text` with a visible marker."""
    for bad in unsupported_citations(text, source):
        removed.append(bad)
        text = re.sub(re.escape(bad), UNSUPPORTED_MARK, _normalize_dashes(text),
                      count=1, flags=re.IGNORECASE)
    return text


def _normalize_dashes(text: str) -> str:
    return (text or "").replace("\u2013", "-").replace("\u2014", "-")


def strip_unsupported_citations(result: dict, source: str) -> tuple[dict, list[str]]:
    """Remove citations the model did not get from the source items.

    Method: find statute-like references with CITATION_RE, and keep one only
    if its section number appears as a whole token in the prompt we sent
    (dashes normalized on both sides). Then:
      * statutory_references: an unsupported entry is dropped.
      * key_facts, headline, summary: only the citation text is replaced
        with a visible marker; the rest of the sentence stays.
    Any removal adds a line to caveats, so the snapshot is flagged.
    """
    removed: list[str] = []

    refs = []
    for ref in result.get("statutory_references") or []:
        bad = unsupported_citations(str(ref), source)
        if bad:
            removed.extend(bad)
        else:
            refs.append(ref)
    result["statutory_references"] = refs

    result["key_facts"] = [
        _strip(str(fact), source, removed) for fact in result.get("key_facts") or []
    ]
    for field in ("headline", "summary"):
        result[field] = _strip(str(result.get(field, "") or ""), source, removed)

    if removed:
        note = (
            f"{len(removed)} citation(s) were removed because they do not appear "
            "in the source items."
        )
        caveats = str(result.get("caveats", "") or "").strip()
        result["caveats"] = f"{caveats} {note}".strip()
    return result, removed


# (jurisdiction_id, topic) pairs whose last synthesis attempt failed. In
# memory: a redeploy clears it, which only means a failed pair gets one more
# early try.
_failed_last_attempt: set[tuple[int, str]] = set()


async def _synthesize_law_snapshot(
    session: AsyncSession,
    jurisdiction_id: int,
    topic: str,
    items: list[PolicyItem],
) -> LawSnapshot | None:
    """Synthesize or update a LawSnapshot (see synthesize_law_snapshot).

    Raises EnrichmentAPIError / EnrichmentParseError instead of returning
    None, so the run counts the failure. The existing snapshot is untouched,
    so its updated_at shows how stale it is.
    """
    if not items:
        return None

    # Build the prompt context from policy items (newest first)
    items_sorted = sorted(items, key=lambda i: i.discovered_at or datetime.min, reverse=True)

    item_blocks = []
    for idx, item in enumerate(items_sorted[:15], start=1):  # Cap at 15 items to keep prompt size sane
        date_str = item.published_at.strftime("%Y-%m-%d") if item.published_at else "unknown"
        item_blocks.append(
            f"[{idx}] ({date_str}, impact={item.impact_score}) {item.title}\n"
            f"    {item.summary}\n"
            f"    Reasoning: {item.impact_reasoning or '—'}"
        )

    jur = await session.get(Jurisdiction, jurisdiction_id)
    jur_name = jur.name if jur else f"Jurisdiction #{jurisdiction_id}"

    prompt = (
        f"Jurisdiction: {jur_name} ({jur.level if jur else 'unknown'})\n"
        f"Topic: {TOPIC_LABELS.get(topic, topic)}\n"
        f"Number of observed policy items: {len(items)}\n\n"
        f"Source items (most recent first):\n\n"
        + "\n\n".join(item_blocks)
    )

    result = await create_json(
        f"law synthesizer {jur_name}/{topic}",
        model=settings.law_synth_model,
        max_tokens=settings.law_synth_max_tokens,
        output_config={"effort": settings.law_synth_effort},
        # Opus at effort high can think for minutes; the client-wide 120 s
        # is sized for Haiku and Sonnet.
        timeout=600,
        system=SYNTHESIZER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    result, unsupported = strip_unsupported_citations(result, prompt)
    if unsupported:
        logger.warning(
            f"Law synthesizer {jur_name}/{topic}: removed {len(unsupported)} "
            f"citation(s) not found in the source items: {unsupported}"
        )

    valid_confidence = {"low", "med", "high"}
    confidence = result.get("confidence", "med")
    if confidence not in valid_confidence:
        confidence = "med"

    # Check for existing snapshot
    existing_q = select(LawSnapshot).where(
        LawSnapshot.jurisdiction_id == jurisdiction_id,
        LawSnapshot.topic == topic,
    )
    existing = (await session.execute(existing_q)).scalars().first()

    source_item_ids = [item.id for item in items]

    if existing:
        existing.headline = str(result.get("headline", ""))[:200]
        existing.summary = str(result.get("summary", ""))
        existing.key_facts = result.get("key_facts", []) or []
        existing.statutory_references = result.get("statutory_references", []) or []
        existing.source_item_ids = source_item_ids
        existing.confidence = confidence
        existing.caveats = str(result.get("caveats", "")) or None
        snapshot = existing
    else:
        snapshot = LawSnapshot(
            jurisdiction_id=jurisdiction_id,
            topic=topic,
            headline=str(result.get("headline", ""))[:200],
            summary=str(result.get("summary", "")),
            key_facts=result.get("key_facts", []) or [],
            statutory_references=result.get("statutory_references", []) or [],
            source_item_ids=source_item_ids,
            confidence=confidence,
            caveats=str(result.get("caveats", "")) or None,
        )
        session.add(snapshot)

    await session.flush()
    return snapshot


async def find_jurisdiction_topic_pairs_with_items(
    session: AsyncSession,
    min_items: int = 1,
) -> list[tuple[int, str, list[PolicyItem]]]:
    """Find all (jurisdiction_id, topic, items) groups that have at least min_items policy items."""
    # Pull all policy items with jurisdictions
    result = await session.execute(
        select(PolicyItem).where(PolicyItem.jurisdiction_id.is_not(None))
    )
    all_items = result.scalars().all()

    # Group by (jurisdiction_id, topic)
    groups: dict[tuple[int, str], list[PolicyItem]] = {}
    for item in all_items:
        if not item.topic_tags:
            continue
        for topic in item.topic_tags:
            if topic not in TOPICS:
                continue
            key = (item.jurisdiction_id, topic)
            groups.setdefault(key, []).append(item)

    return [
        (jur_id, topic, items)
        for (jur_id, topic), items in groups.items()
        if len(items) >= min_items
    ]


async def synthesize_law_snapshot(
    session: AsyncSession,
    jurisdiction_id: int,
    topic: str,
    items: list[PolicyItem],
) -> LawSnapshot | None:
    """Synthesize or update a LawSnapshot for a (jurisdiction, topic) pair.

    Raises EnrichmentAPIError / EnrichmentParseError instead of returning
    None, so the run counts the failure. A failed pair is remembered so the
    next capped refresh tries pairs that have not failed first.
    """
    key = (jurisdiction_id, topic)
    try:
        snapshot = await _synthesize_law_snapshot(session, jurisdiction_id, topic, items)
    except Exception:
        _failed_last_attempt.add(key)
        raise
    _failed_last_attempt.discard(key)
    return snapshot

def order_pairs_for_refresh(
    pairs: list[tuple[int, str, list[PolicyItem]]],
    snapshots: dict[tuple[int, str], "LawSnapshot"],
) -> list[tuple[int, str, list[PolicyItem]]]:
    """Order (jurisdiction, topic) pairs so a capped refresh does the right ones.

    Pairs whose last attempt failed go behind every pair that has not
    failed, so one bad pair cannot hold a slot every week. Then: pairs with
    items the last snapshot did not include (or no snapshot yet) come before
    the rest. Inside each group, the oldest snapshot goes first (no snapshot
    counts as oldest). Before this, the weekly run took the same first 50
    pairs in dict order every week.
    """
    def key(pair):
        jur_id, topic, items = pair
        failed = 1 if (jur_id, topic) in _failed_last_attempt else 0
        snap = snapshots.get((jur_id, topic))
        if snap is None:
            return (failed, 0, 0, 0.0)
        seen = set(snap.source_item_ids or [])
        has_new = any(item.id not in seen for item in items)
        updated = snap.updated_at.timestamp() if snap.updated_at else 0.0
        return (failed, 0 if has_new else 1, 1, updated)

    return sorted(pairs, key=key)


async def select_pairs_for_refresh(
    session: AsyncSession,
    pairs: list[tuple[int, str, list[PolicyItem]]],
    limit: int,
) -> list[tuple[int, str, list[PolicyItem]]]:
    """The `limit` pairs most in need of a new snapshot."""
    rows = (await session.execute(select(LawSnapshot))).scalars().all()
    snapshots = {(s.jurisdiction_id, s.topic): s for s in rows}
    return order_pairs_for_refresh(pairs, snapshots)[:limit]
