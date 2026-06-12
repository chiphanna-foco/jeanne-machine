"""Haiku-based relevance classifier — Stage 1 of the enrichment pipeline.

Runs a fast, cheap classification to filter out the ~95% of documents
that aren't about our target topics. Only documents passing this gate
proceed to the more expensive Sonnet summarization.
"""

import json
import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """You are the legislative relevance classifier for TurboTenant's rental-housing law tracker.

TurboTenant is software for small, self-managing landlords — typically 1 to 5 rental properties. Its legal team uses this feed to catch every law that changes (a) what small landlords must do, or (b) what TurboTenant's product must support: tenant screening & background checks, rental applications & application fees, lease agreements & required disclosures, online rent collection & late fees, security deposits, notices & evictions, listings & advertising, and renters insurance.

You will be given the text of a government document — a bill summary, meeting agenda item, court ruling excerpt, or federal regulation.

Decide whether it is relevant to ANY of these rental housing topics:
1. landlord_tenant_law — General landlord-tenant statutes and reforms
2. security_deposit — Security deposit limits, handling, return timelines
3. eviction — Eviction procedures, moratoria, just-cause requirements
4. source_of_income — Source-of-income (SOI) discrimination protections
5. rental_registration — Rental registration, licensing, inspection programs
6. screening_restrictions — Background check, credit screening, and tenant data/privacy restrictions
7. application_fee_limit — Application fee caps or bans
8. rent_control — Rent control, rent stabilization, rent increase limits
9. habitability — Habitability standards, code enforcement, repair obligations
10. fair_housing — Fair housing updates, discrimination protections

ORIENTATION — this is a legal-compliance feed, so err toward RECALL:
- A missed relevant law creates compliance risk for thousands of landlords. A false alarm costs a reviewer one click to dismiss.
- If the document plausibly changes any rule of operating a residential rental, mark it relevant. When uncertain, mark relevant with lower confidence rather than rejecting.
- State bill summaries are often boilerplate that restates the title (e.g. "Concerning tenant data information."). Thin text is NOT evidence of irrelevance — judge from the title, metadata, and what the bill would plausibly do.
- Documents may carry curated metadata lines: "Subjects: ..." (the legislature/aggregator's own topic tags) and "Matched policy searches: ..." (the standing full-text query that surfaced the bill). A housing-related subject tag, or a match on landlord/tenant search terms, is STRONG evidence of relevance even when the summary is thin.

Still NOT relevant: budget line items and appropriations; homeowner/HOA-only or mortgage/foreclosure-only matters; homelessness services with no landlord obligations; zoning or construction rules with no impact on operating a rental; documents that merely mention "housing" or "residents" in passing without changing any rental rule.

Respond with ONLY valid JSON (no markdown):
{"relevant": true/false, "topics": ["topic_1", "topic_2"], "confidence": 0.0-1.0}"""


async def classify_document(text: str, max_chars: int = 8000) -> dict:
    """Classify a document for relevance to rental housing topics.

    Returns: {"relevant": bool, "topics": list[str], "confidence": float}
    """
    # Truncate to save tokens on the cheap model
    truncated = text[:max_chars]

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.classifier_model,
            max_tokens=200,
            system=CLASSIFIER_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Classify this document:\n\n{truncated}",
                }
            ],
        )

        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)

        return {
            "relevant": bool(result.get("relevant", False)),
            "topics": result.get("topics", []),
            "confidence": float(result.get("confidence", 0.0)),
        }

    except (json.JSONDecodeError, anthropic.APIError) as e:
        logger.warning(f"Classifier error: {e}")
        # On failure, let it through so we don't silently drop items
        return {"relevant": True, "topics": [], "confidence": 0.0}
