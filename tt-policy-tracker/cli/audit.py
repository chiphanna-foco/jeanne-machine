"""CLI wrapper around audit.coverage / audit.trace.

Run inside the worker container so DATABASE_URL, OPENSTATES_API_KEY and
ANTHROPIC_API_KEY are available.
"""

import asyncio
import logging
import sys

import click

sys.path.insert(0, ".")

from adapters.openstates import ALL_STATES  # noqa: E402
from audit import coverage as audit_coverage  # noqa: E402
from audit import trace as audit_trace  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _print_coverage(report: dict) -> None:
    click.echo("\n=== Coverage Audit ===")
    click.echo(f"since: {report['since']}  days_back: {report['days_back']}\n")
    click.echo(
        f"{'STATE':<6} {'OS_HOUSING':>10} {'IN_DB':>7} "
        f"{'ENRICHED':>9} {'CLASSIFIER_DROPS':>17}"
    )
    for r in report["rows"]:
        if "error" in r:
            click.echo(f"{r['state']:<6} ERROR: {r['error']}")
            continue
        click.echo(
            f"{r['state']:<6} "
            f"{r['os_total']:>10} "
            f"{r['in_raw']:>7} "
            f"{r['in_policy']:>9} "
            f"{r['classified_out']:>17}"
        )
        for ex in r.get("missing_examples") or []:
            click.echo(f"        not ingested: {ex['identifier']} — {ex['title']}")
    click.echo()


def _print_trace(results: list[dict]) -> None:
    for entry in results:
        click.echo(f"\n--- {entry['ref']} ---")
        if "error" in entry:
            click.echo(f"  {entry['error']}")
            continue
        os_info = entry.get("openstates")
        if os_info == "NOT_FOUND":
            click.echo("  Open States:      NOT FOUND")
            continue
        click.echo(f"  Open States id:   {os_info['id']}")
        click.echo(f"  OS subjects:      {os_info['subjects']}")
        click.echo(f"  OS title:         {os_info['title']}")
        pipeline = entry.get("pipeline")
        if pipeline == "NOT_INGESTED":
            click.echo("  Pipeline status:  NOT INGESTED")
            continue
        click.echo(
            f"  Pipeline status:  raw_document.id={pipeline['raw_document_id']}, "
            f"fetched_at={pipeline['fetched_at']}"
        )
        policy = entry.get("policy_item")
        if policy:
            click.echo(
                f"  Policy item:      id={policy['id']}, "
                f"impact={policy['impact_score']}, topics={policy['topics']}"
            )
        else:
            click.echo("  Policy item:      MISSING")
            rc = entry.get("reclassified")
            if rc:
                click.echo(
                    f"  Re-classified:    relevant={rc['relevant']}, "
                    f"conf={rc['confidence']:.2f}, topics={rc.get('topics')}"
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
    report = asyncio.run(audit_coverage(states, days_back))
    _print_coverage(report)


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
    results = asyncio.run(audit_trace(list(bills), rerun_classifier))
    _print_trace(results)


if __name__ == "__main__":
    cli()
