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

CLASSIFIER_SYSTEM_PROMPT = """You are a legislative relevance classifier for a rental housing policy tracker.

You will be given the text of a government document — it may be a bill summary, meeting agenda item, court ruling excerpt, or federal regulation.

Decide whether the document is relevant to ANY of these rental housing topics:
1. landlord_tenant_law — General landlord-tenant statutes and reforms
2. security_deposit — Security deposit limits, handling, return timelines
3. eviction — Eviction procedures, moratoria, just-cause requirements
4. source_of_income — Source-of-income (SOI) discrimination protections
5. rental_registration — Rental registration, licensing, inspection programs
6. screening_restrictions — Background check and credit screening restrictions
7. application_fee_limit — Application fee caps or bans
8. rent_control — Rent control, rent stabilization, rent increase limits
9. habitability — Habitability standards, code enforcement, repair obligations
10. fair_housing — Fair housing updates, discrimination protections

Be STRICT — only mark relevant if the document actually proposes, discusses, amends, or rules on one of these topics. A document that merely mentions "housing" or "residents" in passing is NOT relevant. Budget line items, appropriations, and general government operations are NOT relevant unless they specifically modify rental housing law.

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
