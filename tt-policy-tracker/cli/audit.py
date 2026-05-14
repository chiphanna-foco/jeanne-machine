"""CLI command: audit pipeline coverage against the Open States ground truth.

Two subcommands:
  - coverage: enumerate housing-tagged bills in Open States for each state and
    compare to what's in raw_document / policy_item.
  - trace: trace specific bills (e.g. "CO:SB26-054") through the pipeline and
    optionally re-run the classifier to see what verdict it would give now.

Run inside the worker container so DATABASE_URL, OPENSTATES_API_KEY and
ANTHROPIC_API_KEY are available.
"""

import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta

import click
import httpx
from sqlalchemy import select

sys.path.insert(0, ".")

from adapters.openstates import (  # noqa: E402
    ALL_STATES,
    BASE_URL,
    RELEVANT_SUBJECTS,
    STATE_TO_JURISDICTION,
)
from config import settings  # noqa: E402
from enrichment.classifier import classify_document  # noqa: E402
from storage.database import async_session  # noqa: E402
from storage.models import PolicyItem, RawDocument  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _os_headers() -> dict:
    return {"X-API-KEY": settings.openstates_api_key, "Accept": "application/json"}


async def _fetch_housing_bills(
    client: httpx.AsyncClient, state: str, since: datetime
) -> list[dict]:
    """Pull every Open States bill for `state` tagged with one of our housing subjects."""
    jurisdiction_id = STATE_TO_JURISDICTION.get(state.lower())
    if not jurisdiction_id:
        return []
    since_str = since.strftime("%Y-%m-%d")
    all_bills: dict[str, dict] = {}
    for subject in sorted(RELEVANT_SUBJECTS):
        page = 1
        while True:
            resp = await client.get(
                f"{BASE_URL}/bills",
                params={
                    "jurisdiction": jurisdiction_id,
                    "subject": subject,
                    "updated_since": since_str,
                    "page": page,
                    "per_page": 20,
                },
                headers=_os_headers(),
            )
            if resp.status_code != 200:
                logger.warning(
                    f"OS /bills {state} subject={subject!r}: HTTP {resp.status_code}"
                )
                break
            data = resp.json()
            for bill in data.get("results", []):
                all_bills[bill["id"]] = bill
            pagination = data.get("pagination", {})
            if page >= pagination.get("max_page", 1):
                break
            page += 1
    return list(all_bills.values())


async def run_coverage(states: list[str], days_back: int) -> None:
    since = datetime.utcnow() - timedelta(days=days_back)
    logger.info(
        f"Coverage audit: states={states} since={since.date().isoformat()}"
    )

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=120.0) as client, async_session() as session:
        for state in states:
            try:
                bills = await _fetch_housing_bills(client, state, since)
            except Exception as e:
                logger.error(f"{state.upper()} OS fetch failed: {e}")
                continue

            os_ids = [b["id"] for b in bills]
            if not os_ids:
                rows.append(
                    {
                        "state": state.upper(),
                        "os_total": 0,
                        "in_raw": 0,
                        "in_policy": 0,
                        "missing_examples": [],
                        "classified_out": 0,
                    }
                )
                continue

            raw_result = await session.execute(
                select(RawDocument.external_id).where(
                    RawDocument.external_id.in_(os_ids)
                )
            )
            raw_ids = {r[0] for r in raw_result.all()}

            policy_result = await session.execute(
                select(RawDocument.external_id)
                .join(PolicyItem, PolicyItem.raw_document_id == RawDocument.id)
                .where(RawDocument.external_id.in_(os_ids))
            )
            policy_ids = {r[0] for r in policy_result.all()}

            missing = [b for b in bills if b["id"] not in raw_ids]
            rows.append(
                {
                    "state": state.upper(),
                    "os_total": len(bills),
                    "in_raw": len(raw_ids),
                    "in_policy": len(policy_ids),
                    "missing_examples": [
                        f"{b.get('identifier', '?')} — {(b.get('title') or '')[:80]}"
                        for b in missing[:5]
                    ],
                    "classified_out": len(raw_ids - policy_ids),
                }
            )

    click.echo("\n=== Coverage Audit ===\n")
    click.echo(
        f"{'STATE':<6} {'OS_HOUSING':>10} {'IN_DB':>7} "
        f"{'ENRICHED':>9} {'CLASSIFIER_DROPS':>17}"
    )
    for r in rows:
        click.echo(
            f"{r['state']:<6} "
            f"{r['os_total']:>10} "
            f"{r['in_raw']:>7} "
            f"{r['in_policy']:>9} "
            f"{r['classified_out']:>17}"
        )
        for ex in r["missing_examples"]:
            click.echo(f"        not ingested: {ex}")
    click.echo()


_BILL_REF = re.compile(r"^([A-Za-z]{2}):(.+)$")


async def _find_os_bill(
    client: httpx.AsyncClient, state: str, identifier: str
) -> dict | None:
    jurisdiction_id = STATE_TO_JURISDICTION.get(state.lower())
    if not jurisdiction_id:
        return None
    resp = await client.get(
        f"{BASE_URL}/bills",
        params={
            "jurisdiction": jurisdiction_id,
            "q": identifier,
            "per_page": 20,
        },
        headers=_os_headers(),
    )
    if resp.status_code != 200:
        return None
    norm = identifier.replace(" ", "").replace("-", "").lower()
    for bill in resp.json().get("results", []):
        os_ident = (
            bill.get("identifier", "").replace(" ", "").replace("-", "").lower()
        )
        if os_ident == norm:
            return bill
    return None


async def run_trace(refs: list[str], rerun_classifier: bool) -> None:
    async with httpx.AsyncClient(timeout=60.0) as client, async_session() as session:
        for ref in refs:
            m = _BILL_REF.match(ref.strip())
            if not m:
                click.echo(
                    f"[skip] bad ref: {ref!r} (expected STATE:IDENT, e.g. CO:SB26-054)"
                )
                continue
            state, identifier = m.group(1).lower(), m.group(2).strip()
            click.echo(f"\n--- {state.upper()}:{identifier} ---")

            bill = await _find_os_bill(client, state, identifier)
            if not bill:
                click.echo(
                    "  Open States:      NOT FOUND "
                    "(missing from OS or different identifier format)"
                )
                continue
            click.echo(f"  Open States id:   {bill['id']}")
            click.echo(f"  OS subjects:      {bill.get('subject') or '[]'}")
            click.echo(f"  OS title:         {(bill.get('title') or '')[:120]}")

            raw_q = await session.execute(
                select(RawDocument).where(RawDocument.external_id == bill["id"])
            )
            raw = raw_q.scalars().first()
            if not raw:
                click.echo(
                    "  Pipeline status:  NOT INGESTED "
                    "(outside --days-back window or beyond page cap)"
                )
                continue
            click.echo(
                f"  Pipeline status:  raw_document.id={raw.id}, "
                f"fetched_at={raw.fetched_at}"
            )

            policy_q = await session.execute(
                select(PolicyItem).where(PolicyItem.raw_document_id == raw.id)
            )
            policy = policy_q.scalars().first()
            if policy:
                click.echo(
                    f"  Policy item:      id={policy.id}, "
                    f"impact={policy.impact_score}, topics={policy.topic_tags}"
                )
            else:
                click.echo(
                    "  Policy item:      MISSING "
                    "(classifier rejected or summarizer failed)"
                )
                if rerun_classifier:
                    verdict = await classify_document(raw.raw_text or "")
                    click.echo(
                        f"  Re-classified:    relevant={verdict['relevant']}, "
                        f"conf={verdict['confidence']:.2f}, "
                        f"topics={verdict.get('topics')}"
                    )


@click.group()
def cli() -> None:
    """Pipeline coverage audit."""


@cli.command()
@click.option(
    "--state",
    multiple=True,
    help="State codes to audit (repeatable). Default: all 50 states.",
)
@click.option(
    "--days-back",
    default=30,
    type=int,
    help="Look back N days for OS updates.",
)
def coverage(state: tuple, days_back: int) -> None:
    """Compare housing-tagged Open States bills to what's in our DB."""
    states = [s.lower() for s in state] if state else ALL_STATES
    asyncio.run(run_coverage(states, days_back))


@cli.command()
@click.option(
    "--bill",
    "bills",
    multiple=True,
    required=True,
    help='Bills to trace, format STATE:IDENT (repeatable). E.g. --bill CO:SB26-054',
)
@click.option(
    "--rerun-classifier/--no-rerun-classifier",
    default=True,
    help="Re-run the relevance classifier when no PolicyItem was created.",
)
def trace(bills: tuple, rerun_classifier: bool) -> None:
    """Trace specific bills through the pipeline."""
    asyncio.run(run_trace(list(bills), rerun_classifier))


if __name__ == "__main__":
    cli()
