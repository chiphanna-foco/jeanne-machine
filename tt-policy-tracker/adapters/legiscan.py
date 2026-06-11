"""LegiScan multi-state legislature adapter (LegiScan Pull API).

LegiScan mirrors bill data for all 50 states + DC + Congress behind a single
free API key (30,000 queries/month — roughly 4x Open States' 250/day cap).
We use it for two jobs:

  1. Coverage-gap backstop. Some states' bills never surface through Open
     States' search (e.g. Colorado HB26-1196 "Tenant Data Information" — a
     squarely on-topic rental bill that OS returns ``q_search_match: false``
     for despite having the 2026A session). LegiScan carries them.
  2. Quota relief. The whole current session for a state comes back in ONE
     ``getMasterList`` call, already including title + description +
     last_action — enough for the downstream Haiku classifier to filter on,
     with zero per-bill ``getBill`` spend. A 50-state sweep costs ~50 queries.

Design mirrors wa_leg: a thin first-party-style fetch, normalization into
RawDoc, and a per-state ``last_run_stats`` breakdown so the pipeline can
surface coverage the same way it does for Open States.

API reference (LegiScan Pull API v1.91):
  - getMasterList?state=ST   → {status, masterlist:{ "0":{bill_id,number,
                                  change_hash,url,status_date,status,
                                  last_action_date,last_action,title,
                                  description}, ..., "session":{...} }}
  - getBill?id=BILL_ID       → full detail incl. state_link, history, texts
                                (only fetched for bills we want full text on)
Quota optimization via change_hash (skip getBill on unchanged bills) is a
planned v2 enhancement; v1 ingests masterlist summaries directly and relies
on the pipeline's content_hash dedup to no-op unchanged re-fetches.

LegiScan house rules honored here (per the API manual):
  - Every response's ``status`` is checked; non-OK raises (see _get_json).
  - Spend is minimal: one getMasterList per state per run. We never hit the
    bulk dataset endpoints, so the dataset_hash suspension rule is moot.
  - When v2 adds getBill/getBillText, store change_hash and only re-fetch
    bills whose hash changed, and never re-download an unchanged doc blob.
  - Attribution: data is licensed CC BY 4.0 and must credit LegiScan. We
    store the legiscan.com bill URL on every item; the web UI should render
    a "Data via LegiScan (CC BY 4.0)" credit (tracked in coverage-gap-plan).
"""

import asyncio
import logging
import re
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.legiscan.com/"

# Polite pacing between LegiScan calls. The published guidance is daily-cache
# oriented and there is no tight per-minute limit at our volume, but a short
# floor keeps us courteous and bounds bursts.
LEGISCAN_MIN_INTERVAL = 0.3


def colorado_bill_id(number: str, year_start: int | None) -> str:
    """Render a LegiScan bill number in Colorado's official ``HB26-1196`` form.

    LegiScan reports the number as ``HB1196``; Colorado publishes it as
    ``HB26-1196`` where ``26`` is the two-digit session start year. We surface
    that official form so a search for "1196" or "HB26-1196" matches. Other
    states don't use the year infix, so this is CO-specific by design.
    """
    if not year_start:
        return number
    # Split a leading alpha chamber prefix (HB, SB, HJR, SCR, ...) from the
    # trailing digits and insert the two-digit session year between them.
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", number)
    if not m:
        return number
    prefix, digits = m.group(1), m.group(2)
    yy = str(year_start)[-2:]
    return f"{prefix}{yy}-{digits}"


class LegiScanAdapter(BaseAdapter):
    """State bills via the LegiScan Pull API, one getMasterList call per state."""

    @property
    def source_name(self) -> str:
        return "legiscan"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        states: list[str] | None = None,
        api_key: str | None = None,
    ):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        # LegiScan uses uppercase two-letter abbreviations (CO, WA, ...).
        self.states = [s.upper() for s in (states or [])]
        self.api_key = api_key if api_key is not None else settings.legiscan_api_key
        # Mirror openstates_by_state / wa_leg so the pipeline surfaces a
        # per-state breakdown under the "legiscan_by_state" key.
        self.last_run_stats: dict[str, dict] = {}

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {"name": st, "level": "state", "state_code": st} for st in self.states
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """For each configured state, pull the current session master list and
        normalize every bill whose last action falls on/after ``since``."""
        docs: list[RawDoc] = []
        stats: dict = {}

        if not self.api_key:
            logger.error("legiscan: no API key configured (LEGISCAN_API_KEY); skipping")
            for st in self.states:
                stats[st] = {"list_status": "error", "listed": 0, "kept": 0,
                             "error": "no API key configured"}
            self.last_run_stats = stats
            return docs

        since_date = since.date()

        for st in self.states:
            st_stats = {"list_status": None, "listed": 0, "kept": 0, "error": None}
            try:
                payload = await self._get_json(
                    {"op": "getMasterList", "state": st}
                )
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                logger.error(f"legiscan: getMasterList({st}) failed: {msg}")
                st_stats["list_status"] = "error"
                st_stats["error"] = msg
                stats[st] = st_stats
                continue

            masterlist = payload.get("masterlist", {}) or {}
            session_meta = masterlist.get("session", {}) or {}
            year_start = session_meta.get("year_start")

            bills = [v for k, v in masterlist.items() if k != "session" and isinstance(v, dict)]
            st_stats["list_status"] = "ok"
            st_stats["listed"] = len(bills)
            logger.info(
                f"legiscan: getMasterList({st}) returned {len(bills)} bills "
                f"(session year_start={year_start})"
            )

            for bill in bills:
                if not self._within_window(bill, since_date):
                    continue
                doc = self._normalize(bill, st, year_start)
                if doc:
                    docs.append(doc)
                    st_stats["kept"] += 1

            stats[st] = st_stats

        self.last_run_stats = stats
        return docs

    @staticmethod
    def _within_window(bill: dict, since_date) -> bool:
        """Keep a bill if its last action (or status date) is on/after ``since``.

        Bills with no parseable date are kept — we'd rather over-include and let
        the classifier and content_hash dedup sort it out than silently drop.
        """
        for field in ("last_action_date", "status_date"):
            raw = (bill.get(field) or "").strip()
            if not raw:
                continue
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date() >= since_date
            except ValueError:
                continue
        return True

    async def _get_json(self, params: dict) -> dict:
        """GET the Pull API with polite pacing, retry, and status checking.

        Raises on a non-OK LegiScan envelope so the per-state loop records the
        error (and surfaces quota/throttle messages) instead of silently
        treating an error body as an empty session.
        """
        params = {"key": self.api_key, **params}
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self.client.get(
                    BASE_URL,
                    params=params,
                    headers={
                        "User-Agent": "jeanne-machine/1.0 (rental policy tracker)",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                await asyncio.sleep(LEGISCAN_MIN_INTERVAL)
                data = resp.json()
                status = (data.get("status") or "").upper()
                if status != "OK":
                    # LegiScan reports errors as {"status":"ERROR","alert":{"message":...}}
                    alert = data.get("alert", {}) or {}
                    raise Exception(
                        f"LegiScan status={status or 'UNKNOWN'}: "
                        f"{alert.get('message', 'no message')}"
                    )
                return data
            except Exception as e:
                last_err = e
                await asyncio.sleep(2 ** attempt)
        raise Exception(
            f"LegiScan {params.get('op')}: 3 retries exhausted: "
            f"{type(last_err).__name__}: {last_err}"
        )

    def _normalize(self, bill: dict, state: str, year_start: int | None) -> RawDoc | None:
        bill_id = bill.get("bill_id")
        number = (bill.get("number") or "").strip()
        title = (bill.get("title") or "").strip()
        if not bill_id or not number or not title:
            return None

        # Colorado publishes HB26-1196; LegiScan reports HB1196. Surface the
        # official display id (no-op for other states) so search matches.
        display_id = (
            colorado_bill_id(number, year_start) if state == "CO" else number
        )

        description = (bill.get("description") or "").strip()
        last_action = (bill.get("last_action") or "").strip()
        last_action_date = (bill.get("last_action_date") or "").strip()

        parts = [f"{display_id}: {title}"]
        if description and description != title:
            parts.append(description)
        if last_action:
            when = f" ({last_action_date})" if last_action_date else ""
            parts.append(f"Latest action{when}: {last_action}")
        raw_text = "\n".join(parts)

        published_at: datetime | None = None
        for v in (last_action_date, (bill.get("status_date") or "").strip()):
            if not v:
                continue
            try:
                published_at = datetime.strptime(v, "%Y-%m-%d")
                break
            except ValueError:
                continue

        return RawDoc(
            external_id=f"legiscan-{bill_id}",
            source_name=self.source_name,
            title=f"[{state}] {display_id}: {title[:200]}",
            url=(bill.get("url") or "").strip(),
            raw_text=raw_text,
            jurisdiction_name=state,
            jurisdiction_level="state",
            state_code=state,
            published_at=published_at,
            extra={
                "legiscan_bill_id": bill_id,
                "legiscan_number": number,
                "display_id": display_id,
                "change_hash": bill.get("change_hash"),
                "status": bill.get("status"),
            },
        )
