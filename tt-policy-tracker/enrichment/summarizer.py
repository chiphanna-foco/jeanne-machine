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

SUMMARIZER_SYSTEM_PROMPT = """You are a legislative analyst for a rental housing policy tracker used by property managers and landlords.

Given a government document (bill, regulation, meeting minutes, or court ruling), produce a structured analysis.

Guidelines:
- Title: ≤90 characters, action-oriented (e.g. "Colorado Proposes 60-Day Security Deposit Return Requirement")
- Summary: 2-3 sentences in plain English. Name the jurisdiction and describe the specific change.
- Impact score: "low" = minor procedural change, "med" = material change to landlord obligations in some jurisdictions, "high" = significant new restriction or requirement affecting many landlords.
- Impact reasoning: One sentence explaining why this matters to a landlord.
- Topics: One or more from this fixed list:
  landlord_tenant_law, security_deposit, eviction, source_of_income,
  rental_registration, screening_restrictions, application_fee_limit,
  rent_control, habitability, fair_housing
- Action needed: "inform" = FYI only, "monitor" = track for updates, "urgent" = immediate impact or effective date within 90 days.
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
