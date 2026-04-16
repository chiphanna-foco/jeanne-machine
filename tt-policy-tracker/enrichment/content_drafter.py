"""Content draft generator — creates blog post and social content from high-impact PolicyItems.

Takes policy items scored "high" or "med" and generates ready-to-edit blog post
drafts, social media posts, and newsletter blurbs for the TT content team.
Human-in-the-loop: all drafts start as status="draft" and must be approved.
"""

import json
import logging

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from storage.models import ContentDraft, PolicyItem

logger = logging.getLogger(__name__)

BLOG_PROMPT = """You are a content writer for TurboTenant, a property management platform for independent landlords.

Given a policy item (a new law, regulation, or court ruling affecting rental housing), write a blog post draft aimed at small landlords who manage 1-10 rental units.

Guidelines:
- Tone: helpful, clear, and practical — like a smart friend explaining what just happened and what to do
- Opening: Lead with what changed and who it affects. No fluff.
- Body: Explain the change, who it applies to, what landlords need to do (or not do)
- Include a "What This Means For You" section with 2-3 concrete action items
- Closing: brief, forward-looking, mention TurboTenant can help them stay compliant
- Length: 500-800 words
- SEO-friendly title (different from the policy item title)
- Include a meta description (150-160 chars)
- Suggest 3-5 tags for the blog

Respond with ONLY valid JSON (no markdown):
{
  "title": "SEO-friendly blog title",
  "body": "Full blog post in markdown format",
  "seo_description": "150-160 char meta description",
  "suggested_tags": ["tag1", "tag2", "tag3"]
}"""

SOCIAL_PROMPT = """You are a social media manager for TurboTenant, a property management platform for independent landlords.

Given a policy item (a new law, regulation, or court ruling), write a social media post for LinkedIn aimed at landlords.

Guidelines:
- Hook first line that creates urgency or curiosity
- 2-3 sentences explaining the change in plain English
- One clear call-to-action
- Under 250 words total
- Include 3-5 relevant hashtags

Respond with ONLY valid JSON (no markdown):
{
  "title": "Short headline for the post",
  "body": "The full social post text with hashtags at the end",
  "seo_description": null,
  "suggested_tags": ["hashtag1", "hashtag2"]
}"""


async def generate_blog_draft(
    session: AsyncSession,
    item: PolicyItem,
) -> ContentDraft | None:
    """Generate a blog post draft from a PolicyItem."""
    return await _generate_draft(session, item, "blog_post", BLOG_PROMPT)


async def generate_social_draft(
    session: AsyncSession,
    item: PolicyItem,
) -> ContentDraft | None:
    """Generate a social media post draft from a PolicyItem."""
    return await _generate_draft(session, item, "social_post", SOCIAL_PROMPT)


async def _generate_draft(
    session: AsyncSession,
    item: PolicyItem,
    content_type: str,
    system_prompt: str,
) -> ContentDraft | None:
    """Generate a content draft of the given type."""
    # Check if draft already exists
    existing = await session.execute(
        select(ContentDraft).where(
            ContentDraft.policy_item_id == item.id,
            ContentDraft.content_type == content_type,
        )
    )
    if existing.scalars().first():
        logger.debug(f"Draft already exists for item {item.id} ({content_type})")
        return None

    user_prompt = (
        f"Policy item:\n"
        f"Title: {item.title}\n"
        f"Summary: {item.summary}\n"
        f"Impact: {item.impact_score} — {item.impact_reasoning or ''}\n"
        f"Topics: {', '.join(item.topic_tags) if item.topic_tags else 'N/A'}\n"
        f"Action needed: {item.action_needed or 'N/A'}\n"
        f"Source URL: {item.source_url or 'N/A'}\n"
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.summarizer_model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)
    except (json.JSONDecodeError, anthropic.APIError) as e:
        logger.error(f"Content draft generation failed for item {item.id}: {e}")
        return None

    draft = ContentDraft(
        policy_item_id=item.id,
        content_type=content_type,
        title=str(result.get("title", item.title)),
        body=str(result.get("body", "")),
        seo_description=result.get("seo_description"),
        suggested_tags=result.get("suggested_tags", []),
        status="draft",
    )
    session.add(draft)
    await session.flush()

    logger.info(f"Generated {content_type} draft for: {item.title}")
    return draft


async def generate_drafts_for_high_impact(
    session: AsyncSession,
    min_impact: str = "med",
    max_drafts: int = 10,
) -> list[ContentDraft]:
    """Find high-impact PolicyItems without drafts and generate blog posts."""
    impact_values = ["high"] if min_impact == "high" else ["high", "med"]

    # Find items that don't have a blog draft yet
    existing_ids_q = select(ContentDraft.policy_item_id).where(
        ContentDraft.content_type == "blog_post"
    )

    query = (
        select(PolicyItem)
        .where(
            PolicyItem.impact_score.in_(impact_values),
            PolicyItem.id.notin_(existing_ids_q),
        )
        .order_by(PolicyItem.discovered_at.desc())
        .limit(max_drafts)
    )

    result = await session.execute(query)
    items = result.scalars().all()

    drafts = []
    for item in items:
        draft = await generate_blog_draft(session, item)
        if draft:
            drafts.append(draft)

    return drafts
