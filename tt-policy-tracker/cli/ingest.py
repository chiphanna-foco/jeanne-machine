"""CLI command: ingest documents from all enabled adapters."""

import asyncio
import logging
import sys
from datetime import datetime, timedelta

import click

# Add project root to path
sys.path.insert(0, ".")

from adapters.congress import CongressAdapter
from adapters.federal_register import FederalRegisterAdapter
from adapters.openstates import OpenStatesAdapter
from enrichment.pipeline import ingest_raw_doc
from storage.database import async_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_ingestion(days_back: int, adapters_filter: list[str] | None):
    """Run ingestion from all enabled adapters."""
    since = datetime.utcnow() - timedelta(days=days_back)
    logger.info(f"Ingesting documents since {since.isoformat()} ({days_back} days back)")

    all_adapters = {
        "openstates": OpenStatesAdapter(),
        "congress": CongressAdapter(),
        "federal_register": FederalRegisterAdapter(),
    }

    if adapters_filter:
        adapters = {k: v for k, v in all_adapters.items() if k in adapters_filter}
    else:
        adapters = all_adapters

    total_fetched = 0
    total_stored = 0

    for name, adapter in adapters.items():
        logger.info(f"--- Running adapter: {name} ---")
        try:
            docs = await adapter.fetch_new_items(since)
            logger.info(f"{name}: fetched {len(docs)} raw documents")
            total_fetched += len(docs)

            async with async_session() as session:
                for doc in docs:
                    raw = await ingest_raw_doc(session, doc)
                    if raw:
                        total_stored += 1
                await session.commit()

            logger.info(f"{name}: stored {total_stored} new documents")
        except Exception as e:
            logger.error(f"{name} failed: {e}", exc_info=True)

    logger.info(f"Ingestion complete: {total_fetched} fetched, {total_stored} new stored")


@click.command()
@click.option("--days-back", default=7, help="How many days back to look for new items")
@click.option("--adapter", multiple=True, help="Only run specific adapters (e.g. --adapter openstates)")
def main(days_back: int, adapter: tuple):
    adapters_filter = list(adapter) if adapter else None
    asyncio.run(run_ingestion(days_back, adapters_filter))


if __name__ == "__main__":
    main()
