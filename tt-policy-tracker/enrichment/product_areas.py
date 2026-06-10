"""Product-area registry — maps policy topics to TurboTenant product surfaces.

Phase 2b of the business context plan (the-plunger/docs/BUSINESS_CONTEXT_PLAN.md):
when a med/high-impact policy item lands with a mapped topic, the hub-alerts
payload attaches the affected product surfaces and DRI, and high-impact items
with a near effective date emit a dedicated product-change flag.

Edit this registry as product ownership changes — it's the only place the
topic → surface mapping lives.
"""

# DRI values are Slack handles/groups; surfaces are product areas as named
# internally. Topics absent here (landlord_tenant_law) only appear in the
# general digest, never as product flags.
PRODUCT_AREAS: dict[str, dict] = {
    "security_deposit": {"surfaces": ["lease_builder", "payments"], "dri": "@product-leases"},
    "rent_control": {"surfaces": ["lease_builder", "rent_payments"], "dri": "@product-payments"},
    "screening_restrictions": {"surfaces": ["screening", "applications"], "dri": "@product-screening"},
    "application_fee_limit": {"surfaces": ["applications", "billing"], "dri": "@product-screening"},
    "eviction": {"surfaces": ["lease_builder", "notices"], "dri": "@product-leases"},
    "fair_housing": {"surfaces": ["listings", "screening"], "dri": "@trust-safety"},
    "habitability": {"surfaces": ["maintenance"], "dri": "@product-maintenance"},
    "source_of_income": {"surfaces": ["screening", "listings"], "dri": "@trust-safety"},
    "rental_registration": {"surfaces": ["listings", "onboarding"], "dri": "@product-listings"},
}

# A high-impact item whose effective date is within this many days emits a
# product-change flag (distinct alert naming the surface + DRI).
FLAG_EFFECTIVE_WINDOW_DAYS = 180


def product_impact(topic_tags: list[str] | None) -> dict | None:
    """Aggregate surfaces/DRIs across an item's mapped topics; None if unmapped."""
    if not topic_tags:
        return None
    surfaces: list[str] = []
    dris: list[str] = []
    for tag in topic_tags:
        area = PRODUCT_AREAS.get(tag)
        if not area:
            continue
        for s in area["surfaces"]:
            if s not in surfaces:
                surfaces.append(s)
        if area["dri"] not in dris:
            dris.append(area["dri"])
    if not surfaces:
        return None
    return {"surfaces": surfaces, "dris": dris}
