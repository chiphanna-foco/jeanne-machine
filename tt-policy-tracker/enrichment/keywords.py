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
