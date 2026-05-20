"""Washington State Legislature direct adapter (WSL Web Services).

Pulls every bill introduced in the biennium since `since`, then fetches
full detail for each. The existing Haiku classifier handles housing-
relevance filtering downstream — WSL doesn't expose topical-index data
via SOAP (only via the separate Bill Information report system).

Bypasses Open States entirely for WA, sidestepping its 10/min rate
limit. WSL Web Services are public, unauthenticated, return XML, and
don't publish a rate limit at our volume.

Method discovery: see /admin/wsl-probe for the full method list across
WSL's services. We use only two from LegislationService:
  - GetLegislationInfoIntroducedSince(biennium, sinceDate)  → list IDs
  - GetLegislation(biennium, billNumber)                     → full detail
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

# Polite pacing between WSL calls. WSL doesn't publish a rate limit but a
# half-second floor between requests keeps us in civic-tech-friendly
# territory and bounds the rate at ~2 req/sec.
WSL_MIN_INTERVAL = 0.5


def current_biennium(now: datetime | None = None) -> str:
    """WA legislative biennium string like '2025-26' for the given date."""
    now = now or datetime.utcnow()
    year = now.year
    if year % 2 == 0:
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
        biennium: str | None = None,
    ):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        self.biennium = biennium or current_biennium()
        # Mirror the openstates_by_state pattern so the pipeline can surface
        # a per-adapter breakdown.
        self.last_run_stats: dict[str, dict] = {}

    async def discover_jurisdictions(self) -> list[dict]:
        return [{"name": "Washington", "level": "state", "state_code": "WA"}]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """List every bill introduced in this biennium since `since`,
        then fetch full detail for each and normalize."""
        since_date = since.strftime("%Y-%m-%d")
        docs: list[RawDoc] = []
        stats: dict = {"WA": {"list_status": None, "listed": 0, "detail_ok": 0, "detail_err": 0, "error": None}}

        try:
            bill_refs = await self._list_introduced_since(self.biennium, since_date)
            stats["WA"]["list_status"] = "ok"
            stats["WA"]["listed"] = len(bill_refs)
            logger.info(
                f"wa_leg: GetLegislationInfoIntroducedSince(biennium={self.biennium}, "
                f"sinceDate={since_date}) returned {len(bill_refs)} bills"
            )
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            logger.error(f"wa_leg: list call failed: {msg}")
            stats["WA"]["list_status"] = "error"
            stats["WA"]["error"] = msg
            self.last_run_stats = stats
            return docs

        for ref in bill_refs:
            try:
                detail = await self._get_bill_detail(ref["biennium"], ref["bill_number"])
                stats["WA"]["detail_ok"] += 1
            except Exception as e:
                stats["WA"]["detail_err"] += 1
                logger.error(
                    f"wa_leg: detail failed for {ref['biennium']}/{ref['bill_number']}: "
                    f"{type(e).__name__}: {e}"
                )
                continue
            doc = self._normalize(detail)
            if doc:
                docs.append(doc)

        self.last_run_stats = stats
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
        raise Exception(
            f"WSL {path}: 3 retries exhausted: {type(last_err).__name__}: {last_err}"
        )

    async def _list_introduced_since(self, biennium: str, since_date: str) -> list[dict]:
        """Return [{biennium, bill_id, bill_number}, ...] for every bill introduced since."""
        root = await self._get_xml(
            "/LegislationService.asmx/GetLegislationInfoIntroducedSince",
            {"biennium": biennium, "sinceDate": since_date},
        )
        refs: list[dict] = []
        for info in root.findall(f"{NS}LegislationInfo"):
            bie = (info.findtext(f"{NS}Biennium") or "").strip()
            bill_id = (info.findtext(f"{NS}BillId") or "").strip()
            bill_number = (info.findtext(f"{NS}BillNumber") or "").strip()
            if not bill_number and bill_id:
                bill_number = bill_id.split()[-1]
            if bie and bill_id and bill_number:
                refs.append(
                    {"biennium": bie, "bill_id": bill_id, "bill_number": bill_number}
                )
        return refs

    async def _get_bill_detail(self, biennium: str, bill_number: str) -> dict:
        """Fetch full bill detail and return a normalized dict.

        GetLegislation may return multiple <Legislation> entries (e.g. one
        per substitute version). Prefer the latest (highest substitute/
        engrossed pair) so we capture the most up-to-date title and status.
        """
        root = await self._get_xml(
            "/LegislationService.asmx/GetLegislation",
            {"biennium": biennium, "billNumber": bill_number},
        )
        leg_elements = root.findall(f"{NS}Legislation")
        if not leg_elements:
            raise Exception(f"No <Legislation> element for {biennium}/{bill_number}")

        # Pick the latest version by (engrossed, substitute) ordinal pair
        def version_key(leg: ET.Element) -> tuple[int, int]:
            def _int(tag: str) -> int:
                v = leg.findtext(f"{NS}{tag}") or "0"
                try:
                    return int(v.strip())
                except (TypeError, ValueError):
                    return 0
            return (_int("EngrossedVersion"), _int("SubstituteVersion"))

        leg = max(leg_elements, key=version_key)

        def t(tag: str) -> str:
            return (leg.findtext(f"{NS}{tag}") or "").strip()

        # CurrentStatus is nested
        current_status_el = leg.find(f"{NS}CurrentStatus")
        history_line = ""
        action_date = ""
        if current_status_el is not None:
            history_line = (current_status_el.findtext(f"{NS}HistoryLine") or "").strip()
            action_date = (current_status_el.findtext(f"{NS}ActionDate") or "").strip()

        return {
            "biennium": t("Biennium") or biennium,
            "bill_id": t("BillId"),
            "bill_number": t("BillNumber") or bill_number,
            "long_description": t("LongDescription"),
            "short_description": t("ShortDescription"),
            "legal_title": t("LegalTitle"),
            "history_line": history_line,
            "action_date": action_date,
            "introduced_date": t("IntroducedDate"),
            "sponsor": t("Sponsor"),
            "url": (
                f"https://app.leg.wa.gov/billsummary"
                f"?BillNumber={bill_number}&Year={biennium.split('-')[0]}"
            ),
        }

    def _normalize(self, detail: dict) -> RawDoc | None:
        bill_id = detail.get("bill_id", "")
        title = (
            detail.get("long_description")
            or detail.get("legal_title")
            or detail.get("short_description")
            or bill_id
        )
        if not bill_id or not title:
            return None

        external_id = f"waleg-{detail['biennium']}-{bill_id.replace(' ', '')}"

        parts = [f"{bill_id}: {title}"]
        if detail.get("legal_title") and detail["legal_title"] != detail.get("long_description"):
            parts.append(f"Legal title: {detail['legal_title']}")
        if detail.get("sponsor"):
            parts.append(f"Sponsor: {detail['sponsor']}")
        if detail.get("history_line"):
            parts.append(f"Latest action: {detail['history_line']}")
        raw_text = "\n".join(parts)

        published_at: datetime | None = None
        for date_field in ("action_date", "introduced_date"):
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
            title=f"[WA] {bill_id}: {title[:200]}",
            url=detail.get("url", ""),
            raw_text=raw_text,
            jurisdiction_name="Washington",
            jurisdiction_level="state",
            state_code="WA",
            published_at=published_at,
            extra={
                "biennium": detail["biennium"],
                "bill_id": bill_id,
                "sponsor": detail.get("sponsor"),
            },
        )
