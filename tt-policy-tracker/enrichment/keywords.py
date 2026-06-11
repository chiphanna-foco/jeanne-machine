"""Cheap keyword pre-screen to avoid spending Haiku on obviously off-topic docs.

Most ingested documents (court opinions, budget bills, transportation
measures, etc.) have nothing to do with rental housing. Running the Haiku
classifier on all of them is slow and costs money. This pre-screen does a
fast local keyword check first: a doc only proceeds to Haiku if it mentions
at least one housing-related term.

Design for RECALL, not precision. A false positive just goes to Haiku, which
correctly rejects it. A false negative would silently drop a real housing
doc, so the stem list is deliberately broad and matched with a leading word
boundary + any suffix (so "rent" catches rental/rents/renting but not
"current"/"parent"/"different").
"""

import re

# Word stems matched with a leading \b and any trailing characters.
HOUSING_STEMS = [
    "landlord",
    "tenan",          # tenant, tenants, tenancy
    "renter",
    "rent",           # rent, rental, rents, renting, rented (not "current"/"parent")
    "sublease",
    "sublet",
    "lease",          # lease, leases, leasehold (not "please")
    "evict",          # evict, eviction, evicted
    "unlawful detainer",
    "habitab",        # habitable, habitability
    "occupanc",       # occupancy, occupance
    "dwelling",
    "deposit",        # security deposit, deposits
    "fair housing",
    "housing",
    "source of income",
    "manufactured home",
    "mobile home",
    "mobile/manufactured",
    "rooming house",
    "boarding house",
    "just cause",
    "section 8",
    "right to counsel",
    "code enforcement",
    "rent control",
    "rent stabiliz",  # stabilization, stabilisation
    "application fee",
    "screening",
    "premises",
    "lodger",
]

_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in HOUSING_STEMS) + r")",
    re.IGNORECASE,
)


def passes_keyword_prescreen(text: str) -> bool:
    """True if the text mentions any housing-related keyword (merits Haiku)."""
    return bool(_KEYWORD_RE.search(text or ""))


# Curated subject tags (e.g. from LegiScan getBill) that, when present, are a
# STRONG signal a bill is rental-housing relevant — strong enough to override
# the classifier's deliberate strictness on thin summaries. The LegiScan
# adapter writes these as a "Subjects: ..." line in raw_text. Unlike a passing
# keyword in body text, a curated subject is editorial metadata, so trusting it
# is high-precision. (This is what was missing for CO HB26-1196 "Tenant Data
# Information": title + description too thin for Haiku, but tagged "Housing".)
HOUSING_SUBJECTS = [
    "housing",
    "landlord",
    "tenant",
    "eviction",
    "rent",            # rent, rental (within a short curated subject line)
    "lease",
    "real estate",
    "mobile home",
    "manufactured home",
    "fair housing",
    "security deposit",
    "habitability",
]

# Matches the "Subjects: ..." line the LegiScan adapter writes into raw_text.
_SUBJECTS_LINE_RE = re.compile(r"^Subjects:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def has_housing_subject_tag(text: str) -> bool:
    """True if the doc carries a curated housing-related subject tag.

    Only fires on the explicit ``Subjects:`` line (curated metadata), not on
    incidental keyword mentions — so it stays high-precision.
    """
    m = _SUBJECTS_LINE_RE.search(text or "")
    if not m:
        return False
    line = m.group(1).lower()
    return any(s in line for s in HOUSING_SUBJECTS)
