"""Sonnet-based summarizer — Stage 3 of the enrichment pipeline.

Produces structured summaries with title, impact score, topics, and
action-needed classification. Uses tool-use / structured output for
reliable JSON extraction.
"""

import json
import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

SUMMARIZER_SYSTEM_PROMPT = """You are a legislative analyst for TurboTenant's rental housing policy tracker. The audience is TurboTenant's legal team and its customers: small, self-managing landlords with 1-5 rental properties.

Given a government document (bill, regulation, meeting minutes, or court ruling), produce a structured analysis.

Guidelines:
- Title: ≤90 characters, action-oriented (e.g. "Colorado Proposes 60-Day Security Deposit Return Requirement")
- Summary: 1-2 SHORT sentences in plain English. Name the jurisdiction and the specific change. The reader is busy — no filler.
- Impact score: "low" = minor procedural change, "med" = material change to landlord obligations in some jurisdictions, "high" = significant new restriction or requirement affecting many landlords.
- Impact reasoning: One sentence explaining why this matters to a SMALL landlord (1-5 units). If the law sets an applicability threshold — e.g. exempts owner-occupied buildings or applies only to landlords above N units — say so here explicitly, since that determines whether TurboTenant's customers are even covered.
- Topics: One or more from this fixed list:
  landlord_tenant_law, security_deposit, eviction, source_of_income,
  rental_registration, screening_restrictions, application_fee_limit,
  rent_control, habitability, fair_housing
- Action needed — this drives whether the legal team gets pinged, so apply the time-horizon rule strictly:
  - "urgent" = ALREADY BINDING or imminent: enacted/signed/adopted, or an effective date within ~6 months. Legal must look at this now.
  - "monitor" = actively moving (passed a chamber, on the governor's desk) AND could bind landlords within ~6 months if it passes.
  - "inform" = everything early-stage or speculative: just introduced, in committee, dead/postponed/vetoed, or — even if it eventually passed — there would still be 6+ months to react. Do NOT mark these urgent; they are watchlist items, not alerts.
- Effective date: ISO date if mentioned, otherwise null.

Respond with ONLY valid JSON (no markdown):
{
  "title": "...",
  "summary": "...",
  "impact_score": "low|med|high",
  "impact_reasoning": "...",
  "topics": ["..."],
  "action_needed": "inform|monitor|urgent",
  "effective_date": "YYYY-MM-DD or null"
}"""


async def summarize_document(text: str, max_chars: int = 15000) -> dict:
    """Produce a structured summary of a policy document.

    Returns dict with title, summary, impact_score, impact_reasoning,
    topics, action_needed, effective_date.
    """
    truncated = text[:max_chars]

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.summarizer_model,
            max_tokens=600,
            system=SUMMARIZER_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this document:\n\n{truncated}",
                }
            ],
        )

        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)

        # Validate and normalize
        valid_scores = {"low", "med", "high"}
        valid_actions = {"inform", "monitor", "urgent"}

        return {
            "title": str(result.get("title", ""))[:90],
            "summary": str(result.get("summary", "")),
            "impact_score": result.get("impact_score", "low")
            if result.get("impact_score") in valid_scores
            else "low",
            "impact_reasoning": str(result.get("impact_reasoning", "")),
            "topics": result.get("topics", []),
            "action_needed": result.get("action_needed", "inform")
            if result.get("action_needed") in valid_actions
            else "inform",
            "effective_date": result.get("effective_date"),
        }

    except (json.JSONDecodeError, anthropic.APIError) as e:
        logger.error(f"Summarizer error: {e}")
        raise
