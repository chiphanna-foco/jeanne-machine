"""CLI command: run enrichment pipeline on un-enriched raw documents."""

import asyncio
import logging
import sys

import click
from sqlalchemy import select

sys.path.insert(0, ".")

from enrichment.pipeline import enrich_document
from storage.database import async_session
from storage.models import PolicyItem, RawDocument

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_enrichment(batch_size: int):
    """Find un-enriched RawDocuments and run the enrichment pipeline."""
    async with async_session() as session:
        # Find raw docs that don't have a corresponding PolicyItem yet
        subquery = select(PolicyItem.raw_document_id)
        query = (
            select(RawDocument)
            .where(RawDocument.id.notin_(subquery))
            .order_by(RawDocument.fetched_at.desc())
            .limit(batch_size)
        )
        result = await session.execute(query)
        raw_docs = result.scalars().all()

        if not raw_docs:
            logger.info("No un-enriched documents found")
            return

        logger.info(f"Found {len(raw_docs)} un-enriched documents")

        enriched = 0
        irrelevant = 0
        errors = 0

        for raw in raw_docs:
            try:
                item = await enrich_document(session, raw)
                if item:
                    enriched += 1
                else:
                    irrelevant += 1
            except Exception as e:
                logger.error(f"Error enriching {raw.external_id}: {e}")
                errors += 1

        await session.commit()
        logger.info(
            f"Enrichment complete: {enriched} enriched, {irrelevant} irrelevant, {errors} errors"
        )


@click.command()
@click.option("--batch-size", default=100, help="Max documents to enrich per run")
def main(batch_size: int):
    asyncio.run(run_enrichment(batch_size))


if __name__ == "__main__":
    main()
