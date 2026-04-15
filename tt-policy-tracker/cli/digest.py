"""CLI command: build and send digest emails for active subscriptions."""

import asyncio
import logging
import sys
from datetime import datetime

import click
from sqlalchemy import select

sys.path.insert(0, ".")

from config import settings
from digest.builder import build_digest
from digest.sender import send_via_postmark
from storage.database import async_session
from storage.models import DigestSend, Subscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_digest(frequency: str, force: bool):
    """Build and send digests for all matching active subscriptions."""
    async with async_session() as session:
        query = select(Subscription).where(
            Subscription.active.is_(True),
            Subscription.frequency == frequency,
        )
        result = await session.execute(query)
        subs = result.scalars().all()

        if not subs:
            logger.info(f"No active {frequency} subscriptions found")
            # If force mode, create a default subscription for the configured recipient
            if force:
                logger.info(f"Force mode: creating default subscription for {settings.digest_recipient}")
                sub = Subscription(
                    user_id="chip",
                    email=settings.digest_recipient,
                    frequency=frequency,
                    active=True,
                )
                session.add(sub)
                await session.flush()
                subs = [sub]

        sent = 0
        for sub in subs:
            try:
                html, item_ids = await build_digest(session, sub)

                if not item_ids and not force:
                    logger.info(f"No new items for subscription {sub.id} ({sub.email})")
                    continue

                subject = f"TT Policy Tracker — {frequency.title()} Digest"
                message_id = await send_via_postmark(sub.email, subject, html)

                # Record the send
                digest_send = DigestSend(
                    subscription_id=sub.id,
                    item_ids=item_ids,
                    message_id=message_id,
                )
                session.add(digest_send)

                # Update last_sent_at
                sub.last_sent_at = datetime.utcnow()

                sent += 1
                logger.info(f"Digest sent to {sub.email} ({len(item_ids)} items)")

            except Exception as e:
                logger.error(f"Failed to send digest for {sub.email}: {e}", exc_info=True)

        await session.commit()
        logger.info(f"Digest run complete: {sent}/{len(subs)} sent")


@click.command()
@click.option("--frequency", default="weekly", type=click.Choice(["daily", "weekly"]))
@click.option("--force", is_flag=True, help="Send even if no new items; create default sub if none exist")
def main(frequency: str, force: bool):
    asyncio.run(run_digest(frequency, force))


if __name__ == "__main__":
    main()
