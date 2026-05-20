"""Washington State Legislature direct adapter (WSL Web Services).

Bypasses Open States entirely for WA. The WSL Web Services API is public,
unauthenticated, returns XML, and isn't rate-limited the way OS is. We pull
bills under housing-related topical indexes — the same taxonomy that powers
app.leg.wa.gov's topical index page.

WSL docs: https://wslwebservices.leg.wa.gov/
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc

logger = logging.getLogger(__name__)

BASE_URL = "https://wslwebservices.leg.wa.gov"
NS = "{http://WSLWebServices.leg.wa.gov/}"

# Housing-relevant topical indexes maintained by the WA Legislature.
# Names must match WSL's catalog exactly (case-sensitive). If a topic
# returns 0 bills consistently, verify the name via GetTopicalIndexes.
HOUSING_TOPICAL_INDEXES = [
    "Landlord and Tenant",
    "Leases",
    "Low-Income Housing",
    "Housing",
    "Manufactured/Mobile Homes",
    "Eviction",
    "Rental Housing",
    "Affordable Housing",
    "Public Housing",
    "Homelessness",
]

# Polite pacing between WSL calls — they don't publish a rate limit but
# this matches typical civic-tech conventions.
WSL_MIN_INTERVAL = 0.5


def current_biennium(now: datetime | None = None) -> str:
    """Return WA legislative biennium string like '2025-26' for the given date."""
    now = now or datetime.utcnow()
    year = now.year
    if year % 2 == 0:
        # Even year: biennium started the previous (odd) year
        return f"{year - 1}-{str(year)[-2:]}"
    return f"{year}-{str(year + 1)[-2:]}"


class WaLegAdapter(BaseAdapter):
    """WA Legislature bills via WSL Web Services."""

    @property
    def source_name(self) -> str:
        return "wa_leg"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        topical_indexes: list[str] | None = None,
        biennium: str | None = None,
    ):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        self.topical_indexes = topical_indexes or HOUSING_TOPICAL_INDEXES
        self.biennium = biennium or current_biennium()
        # Surfaced via the pipeline's openstates_by_state-style breakdown
        self.last_run_stats: dict[str, dict] = {}

    async def discover_jurisdictions(self) -> list[dict]:
        return [{"name": "Washington", "level": "state", "state_code": "WA"}]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Pull bills from each housing-related topical index and normalize.

        Bills with last_action_date older than `since` are still ingested —
        relevance filtering happens downstream in the classifier. The `since`
        argument is accepted to match the BaseAdapter contract but isn't used
        as a hard filter here.
        """
        docs: list[RawDoc] = []
        seen: set[tuple[str, str]] = set()
        per_topic: dict[str, dict] = {}

        for topic in self.topical_indexes:
            try:
                bills = await self._list_bills_by_topic(topic)
                per_topic[topic] = {"found": len(bills), "error": None}
                logger.info(
                    f"wa_leg: topical_index={topic!r} returned {len(bills)} bills"
                )
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                logger.error(f"wa_leg: topic {topic!r} failed: {msg}")
                per_topic[topic] = {"found": 0, "error": msg}
                continue

            for bill in bills:
                key = (bill["biennium"], bill["bill_number"])
                if key in seen:
                    continue
                seen.add(key)
                try:
                    detail = await self._get_bill_detail(
                        bill["biennium"], bill["bill_number"]
                    )
                except Exception as e:
                    logger.error(
                        f"wa_leg: detail {bill['biennium']}/{bill['bill_number']} "
                        f"failed: {type(e).__name__}: {e}"
                    )
                    continue
                doc = self._normalize(detail, topic)
                if doc:
                    docs.append(doc)

        self.last_run_stats = per_topic
        return docs

    async def _get_xml(self, path: str, params: dict) -> ET.Element:
        """GET + parse XML with polite pacing and a small retry."""
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self.client.get(
                    f"{BASE_URL}{path}",
                    params=params,
                    headers={
                        "User-Agent": "jeanne-machine/1.0 (rental policy tracker)",
                        "Accept": "application/xml,text/xml",
                    },
                )
                resp.raise_for_status()
                await asyncio.sleep(WSL_MIN_INTERVAL)
                return ET.fromstring(resp.text)
            except Exception as e:
                last_err = e
                await asyncio.sleep(2 ** attempt)
        raise Exception(f"WSL {path}: 3 retries exhausted: {type(last_err).__name__}: {last_err}")

    async def _list_bills_by_topic(self, topic: str) -> list[dict]:
        """Return [{biennium, bill_id, bill_number}, ...] for one topical index."""
        root = await self._get_xml(
            "/LegislationService.asmx/GetLegislationByTopicalIndex",
            {"biennium": self.biennium, "topicalIndex": topic},
        )
        bills = []
        for info in root.findall(f"{NS}LegislationInfo"):
            biennium = (info.findtext(f"{NS}Biennium") or "").strip()
            bill_id = (info.findtext(f"{NS}BillId") or "").strip()
            bill_number = bill_id.split()[-1] if bill_id else ""
            if biennium and bill_id and bill_number:
                bills.append(
                    {
                        "biennium": biennium,
                        "bill_id": bill_id,
                        "bill_number": bill_number,
                    }
                )
        return bills

    async def _get_bill_detail(self, biennium: str, bill_number: str) -> dict:
        """Fetch full bill detail. Returns a normalized dict."""
        root = await self._get_xml(
            "/LegislationService.asmx/GetLegislation",
            {"biennium": biennium, "billNumber": bill_number},
        )
        leg = root.find(f"{NS}Legislation")
        if leg is None:
            raise Exception(f"No <Legislation> element for {biennium}/{bill_number}")

        def t(tag: str) -> str:
            return (leg.findtext(f"{NS}{tag}") or "").strip()

        return {
            "biennium": t("Biennium") or biennium,
            "bill_id": t("BillId"),
            "bill_number": t("BillNumber") or bill_number,
            "long_description": t("LongDescription"),
            "short_description": t("ShortDescription"),
            "history_line": t("HistoryLine"),
            "current_status": t("CurrentStatus"),
            "introduced_date": t("IntroducedDate"),
            "last_action_date": t("LastActionDate"),
            "url": (
                f"https://app.leg.wa.gov/billsummary"
                f"?BillNumber={bill_number}&Year={biennium.split('-')[0]}"
            ),
        }

    def _normalize(self, detail: dict, topic: str) -> RawDoc | None:
        bill_id = detail.get("bill_id", "")
        title = (
            detail.get("long_description")
            or detail.get("short_description")
            or bill_id
        )
        if not bill_id or not title:
            return None

        external_id = (
            f"waleg-{detail['biennium']}-{bill_id.replace(' ', '')}"
        )

        parts = [f"{bill_id}: {title}"]
        if detail.get("history_line"):
            parts.append(f"History: {detail['history_line']}")
        if detail.get("current_status"):
            parts.append(f"Status: {detail['current_status']}")
        parts.append(f"WA topical index: {topic}")
        raw_text = "\n".join(parts)

        published_at: datetime | None = None
        for date_field in ("last_action_date", "introduced_date"):
            v = detail.get(date_field)
            if not v:
                continue
            try:
                published_at = datetime.fromisoformat(v.replace("Z", "+00:00"))
                break
            except (ValueError, TypeError):
                continue

        return RawDoc(
            external_id=external_id,
            source_name=self.source_name,
            title=f"[WA] {bill_id}: {title}",
            url=detail.get("url", ""),
            raw_text=raw_text,
            jurisdiction_name="Washington",
            jurisdiction_level="state",
            state_code="WA",
            published_at=published_at,
            extra={
                "biennium": detail["biennium"],
                "bill_id": bill_id,
                "topical_index": topic,
                "current_status": detail.get("current_status"),
            },
        )
