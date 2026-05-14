"""Pipeline coverage audit — shared by cli.audit and /admin/audit/* HTTP endpoints.

Two operations:
  - coverage(states, days_back): for each state, enumerate Open States bills
    tagged with one of our housing subjects in the last N days, then report
    how many reached raw_document, how many became policy_item, and the
    classifier drop count.
  - trace(refs, rerun_classifier): for specific bills (STATE:IDENT), report
    where each one fell off in the pipeline. Optionally re-run the relevance
    classifier on the stored raw_text.
"""

import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from adapters.openstates import (
    BASE_URL,
    RELEVANT_SUBJECTS,
    STATE_TO_JURISDICTION,
)
from config import settings
from enrichment.classifier import classify_document
from storage.database import async_session
from storage.models import PolicyItem, RawDocument


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
    found: dict[str, dict] = {}
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
                break
            data = resp.json()
            for bill in data.get("results", []):
                found[bill["id"]] = bill
            pagination = data.get("pagination", {})
            if page >= pagination.get("max_page", 1):
                break
            page += 1
    return list(found.values())


async def coverage(states: list[str], days_back: int) -> dict:
    """Per-state coverage rows + a summary header."""
    since = datetime.utcnow() - timedelta(days=days_back)
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=120.0) as client, async_session() as session:
        for state in states:
            try:
                bills = await _fetch_housing_bills(client, state, since)
            except Exception as e:
                rows.append({"state": state.upper(), "error": str(e)})
                continue

            os_ids = [b["id"] for b in bills]
            if not os_ids:
                rows.append(
                    {
                        "state": state.upper(),
                        "os_total": 0,
                        "in_raw": 0,
                        "in_policy": 0,
                        "classified_out": 0,
                        "missing_examples": [],
                    }
                )
                continue

            raw_res = await session.execute(
                select(RawDocument.external_id).where(
                    RawDocument.external_id.in_(os_ids)
                )
            )
            raw_ids = {r[0] for r in raw_res.all()}

            policy_res = await session.execute(
                select(RawDocument.external_id)
                .join(PolicyItem, PolicyItem.raw_document_id == RawDocument.id)
                .where(RawDocument.external_id.in_(os_ids))
            )
            policy_ids = {r[0] for r in policy_res.all()}

            missing = [b for b in bills if b["id"] not in raw_ids]
            rows.append(
                {
                    "state": state.upper(),
                    "os_total": len(bills),
                    "in_raw": len(raw_ids),
                    "in_policy": len(policy_ids),
                    "classified_out": len(raw_ids - policy_ids),
                    "missing_examples": [
                        {
                            "identifier": b.get("identifier"),
                            "title": (b.get("title") or "")[:120],
                        }
                        for b in missing[:5]
                    ],
                }
            )
    return {"since": since.isoformat(), "days_back": days_back, "rows": rows}


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


async def trace(refs: list[str], rerun_classifier: bool) -> list[dict]:
    """Per-bill trace through OS → raw_document → policy_item."""
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=60.0) as client, async_session() as session:
        for ref in refs:
            m = _BILL_REF.match(ref.strip())
            if not m:
                results.append(
                    {"ref": ref, "error": "bad ref (expected STATE:IDENT)"}
                )
                continue
            state, identifier = m.group(1).lower(), m.group(2).strip()
            entry: dict = {"ref": f"{state.upper()}:{identifier}"}

            bill = await _find_os_bill(client, state, identifier)
            if not bill:
                entry["openstates"] = "NOT_FOUND"
                results.append(entry)
                continue
            entry["openstates"] = {
                "id": bill["id"],
                "subjects": bill.get("subject") or [],
                "title": (bill.get("title") or "")[:200],
            }

            raw_q = await session.execute(
                select(RawDocument).where(RawDocument.external_id == bill["id"])
            )
            raw = raw_q.scalars().first()
            if not raw:
                entry["pipeline"] = "NOT_INGESTED"
                results.append(entry)
                continue
            entry["pipeline"] = {
                "raw_document_id": raw.id,
                "fetched_at": raw.fetched_at.isoformat() if raw.fetched_at else None,
            }

            policy_q = await session.execute(
                select(PolicyItem).where(PolicyItem.raw_document_id == raw.id)
            )
            policy = policy_q.scalars().first()
            if policy:
                entry["policy_item"] = {
                    "id": policy.id,
                    "impact_score": policy.impact_score,
                    "topics": policy.topic_tags,
                }
            else:
                entry["policy_item"] = None
                if rerun_classifier:
                    entry["reclassified"] = await classify_document(
                        raw.raw_text or ""
                    )
            results.append(entry)
    return results
