"""LegiScan multi-state legislature adapter (LegiScan Pull API).

LegiScan mirrors bill data for all 50 states + DC + Congress behind a single
free API key (30,000 queries/month — roughly 4x Open States' 250/day cap).
We use it for two jobs:

  1. Coverage-gap backstop. Some states' bills never surface through Open
     States' search (e.g. Colorado HB26-1196 "Tenant Data Information" — a
     squarely on-topic rental bill that OS returns ``q_search_match: false``
     for despite having the 2026A session). LegiScan carries them.
  2. Quota relief. One ``getMasterList`` call returns a state's whole session.
     We keyword-prescreen those thin summaries and spend a ``getBill`` query
     ONLY on the ~5-8% that look housing-relevant — so a state costs roughly
     1 + (a few dozen) queries, not 700.

Why getBill is necessary (not just masterlist): the masterlist ``description``
is frequently boilerplate — CO HB26-1196 "Tenant Data Information" carries the
description "Concerning tenant data information", which is too thin for the
classifier. getBill adds the ``subjects`` tags (e.g. "Housing") and the action
``history``; folding those into raw_text gives the classifier a real signal.
This is a RECALL fix for vaguely-titled bills, not a CO special case.

Design mirrors wa_leg: a thin first-party-style fetch, normalization into
RawDoc, and a per-state ``last_run_stats`` breakdown so the pipeline can
surface coverage the same way it does for Open States.

change_hash caching: ``seen_change_hashes`` ({bill_id: change_hash}, populated
by the pipeline from prior raw docs) lets us skip the getBill query for bills
that haven't changed since last run. The change_hash is embedded in the RawDoc
``external_id`` (``legiscan-{bill_id}-{change_hash}``) so it round-trips with
no schema change. "Use the hashes. Really." — the LegiScan manual.

API reference (LegiScan Pull API v1.91):
  - getMasterList?state=ST   → {status, masterlist:{ "0":{bill_id,number,
                                  change_hash,title,description,...}, "session"}}
  - getBill?id=BILL_ID       → full detail: bill_number, description, subjects[],
                                history[], state_link, session{year_start}, ...

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
from enrichment.geotagger import CODE_TO_STATE
from enrichment.keywords import passes_keyword_prescreen

logger = logging.getLogger(__name__)

# Two-letter code → full state name (e.g. "CO" → "Colorado") for nicer
# jurisdiction display names. Falls back to the code itself if unknown.
STATE_NAMES = CODE_TO_STATE

BASE_URL = "https://api.legiscan.com/"

# Polite pacing between LegiScan calls. The published guidance is daily-cache
# oriented and there is no tight per-minute limit at our volume, but a short
# floor keeps us courteous and bounds bursts.
LEGISCAN_MIN_INTERVAL = 0.3


class LegiScanApiError(Exception):
    """A non-OK LegiScan envelope (quota exceeded, throttle, bad key, …).

    Distinct from a transient network fault so ``_get_json`` can fail fast:
    retrying an application-level error just burns more quota against the same
    failure (and once quota is exhausted, every retry is another wasted call).
    """


class LegiScanBudgetExceeded(Exception):
    """Raised before a call when we've hit our self-imposed monthly ceiling.

    Stops spend at ``settings.legiscan_monthly_budget`` so we never reach
    LegiScan's hard 30,000/month limit (which suspends the account).
    """


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
        seen_change_hashes: dict[int, str] | None = None,
        budget_remaining: int | None = None,
    ):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        # LegiScan uses uppercase two-letter abbreviations (CO, WA, ...).
        self.states = [s.upper() for s in (states or [])]
        self.api_key = api_key if api_key is not None else settings.legiscan_api_key
        # {legiscan_bill_id: change_hash} we've already ingested. A bill whose
        # current change_hash matches is unchanged → skip the getBill spend.
        # The pipeline populates this from prior raw docs (see api/main.py).
        self.seen_change_hashes = seen_change_hashes or {}
        # Queries left this calendar month before our self-imposed ceiling
        # (settings.legiscan_monthly_budget − spend so far). None disables the
        # guard. ``queries_used`` counts this run's spend so the caller can
        # persist it back to the api_usage counter.
        self.budget_remaining = budget_remaining
        self.queries_used = 0
        # Mirror openstates_by_state / wa_leg so the pipeline surfaces a
        # per-state breakdown under the "legiscan_by_state" key.
        self.last_run_stats: dict[str, dict] = {}

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {"name": st, "level": "state", "state_code": st} for st in self.states
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """For each configured state: pull the session master list (1 query),
        keyword-prescreen each bill's thin summary, and for the housing-relevant
        candidates fetch full detail via getBill so the classifier sees the
        subject tags + action history (the masterlist description is often
        useless boilerplate, e.g. CO HB26-1196 "Concerning tenant data
        information"). change_hash caching skips getBill on unchanged bills."""
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
            st_stats = {
                "list_status": None, "listed": 0, "candidates": 0,
                "fetched": 0, "skipped_unchanged": 0, "kept": 0,
                "detail_err": 0, "error": None,
            }
            try:
                payload = await self._get_json({"op": "getMasterList", "state": st})
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
                # Cheap keyword prescreen on the thin masterlist summary; only
                # housing-relevant candidates are worth a getBill query.
                if not self._is_candidate(bill):
                    continue
                st_stats["candidates"] += 1

                bid = bill.get("bill_id")
                change_hash = bill.get("change_hash")
                if bid is not None and self.seen_change_hashes.get(bid) == change_hash:
                    st_stats["skipped_unchanged"] += 1
                    continue

                try:
                    detail = await self._get_bill(bid)
                    st_stats["fetched"] += 1
                except Exception as e:
                    st_stats["detail_err"] += 1
                    logger.error(
                        f"legiscan: getBill({bid}) failed: {type(e).__name__}: {str(e)[:150]}"
                    )
                    continue

                doc = self._normalize_detail(detail, st, year_start, change_hash)
                if doc:
                    docs.append(doc)
                    st_stats["kept"] += 1

            stats[st] = st_stats

        self.last_run_stats = stats
        return docs

    @staticmethod
    def _is_candidate(bill: dict) -> bool:
        """Housing-keyword prescreen on the masterlist summary (number + title +
        description). Bounds getBill spend to the ~5-8% of bills that look
        rental-relevant, and matches the same broad, recall-oriented stem list
        the enrichment pipeline uses downstream."""
        text = " ".join(
            (bill.get(f) or "") for f in ("number", "title", "description")
        )
        return passes_keyword_prescreen(text)

    async def _get_bill(self, bill_id) -> dict:
        payload = await self._get_json({"op": "getBill", "id": bill_id})
        return payload.get("bill", {}) or {}

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
        # Self-imposed monthly budget guard: refuse to spend past our ceiling
        # so we never trip LegiScan's hard 30,000/month limit (which suspends
        # the account). Checked BEFORE the call so no quota is burned.
        if (
            self.budget_remaining is not None
            and self.queries_used >= self.budget_remaining
        ):
            raise LegiScanBudgetExceeded(
                f"LegiScan monthly budget reached "
                f"({self.queries_used}/{self.budget_remaining} this window); "
                f"deferring {params.get('op')} to next month/run"
            )

        params = {"key": self.api_key, **params}
        # Count one query per logical op (not per retry) — matches how LegiScan
        # meters and lets the caller persist this run's spend.
        self.queries_used += 1
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
                    # LegiScan reports errors as {"status":"ERROR","alert":{"message":...}}.
                    # This is an application-level failure (quota/throttle/bad
                    # key), NOT a transient network fault — fail fast instead of
                    # retrying, which would only burn more quota on the same error.
                    alert = data.get("alert", {}) or {}
                    raise LegiScanApiError(
                        f"LegiScan status={status or 'UNKNOWN'}: "
                        f"{alert.get('message', 'no message')}"
                    )
                return data
            except LegiScanApiError:
                raise
            except Exception as e:
                last_err = e
                await asyncio.sleep(2 ** attempt)
        raise Exception(
            f"LegiScan {params.get('op')}: 3 retries exhausted: "
            f"{type(last_err).__name__}: {last_err}"
        )

    def _normalize_detail(
        self,
        bill: dict,
        state: str,
        year_start: int | None,
        change_hash: str | None,
    ) -> RawDoc | None:
        """Build a RawDoc from a getBill detail payload.

        LegiScan's masterlist (and even getBill) ``description`` is often
        boilerplate, so the relevance signal comes from the ``subjects`` tags
        (e.g. "Housing") and the action ``history``. We fold both into raw_text
        so the Haiku classifier has something substantive to judge.
        """
        bill_id = bill.get("bill_id")
        number = (bill.get("bill_number") or "").strip()
        title = (bill.get("title") or "").strip()
        if not bill_id or not number or not title:
            return None

        ys = year_start
        sess = bill.get("session") or {}
        if not ys and isinstance(sess, dict):
            ys = sess.get("year_start")

        # Colorado publishes HB26-1196; LegiScan reports HB1196. Surface the
        # official display id (no-op for other states) so search matches.
        display_id = colorado_bill_id(number, ys) if state == "CO" else number

        description = (bill.get("description") or "").strip()
        subjects = [
            (s.get("subject_name") or "").strip()
            for s in (bill.get("subjects") or [])
            if isinstance(s, dict) and s.get("subject_name")
        ]
        history = bill.get("history") or []
        last_action = (history[-1].get("action") or "").strip() if history else ""
        last_action_date = (history[-1].get("date") or "").strip() if history else ""

        parts = [f"{display_id}: {title}"]
        if description and description.lower() != title.lower():
            parts.append(description)
        if subjects:
            parts.append(f"Subjects: {', '.join(subjects)}")
        if last_action:
            when = f" ({last_action_date})" if last_action_date else ""
            parts.append(f"Latest action{when}: {last_action}")
        # A compact recent-history trail gives the classifier real legislative
        # context beyond a one-line title.
        if history:
            recent = "; ".join(
                (h.get("action") or "").strip() for h in history[-5:] if h.get("action")
            )
            if recent:
                parts.append(f"History: {recent}")
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

        # Prefer the official state link; fall back to the LegiScan page.
        legiscan_url = (bill.get("url") or "").strip()
        url = (bill.get("state_link") or "").strip() or legiscan_url

        # change_hash embedded in external_id so the pipeline can read back what
        # we've ingested and skip getBill on unchanged bills next run.
        ch = change_hash or bill.get("change_hash") or ""
        external_id = f"legiscan-{bill_id}-{ch}" if ch else f"legiscan-{bill_id}"

        return RawDoc(
            external_id=external_id,
            source_name=self.source_name,
            title=f"[{state}] {display_id}: {title[:200]}",
            url=url,
            raw_text=raw_text,
            jurisdiction_name=STATE_NAMES.get(state, state),
            jurisdiction_level="state",
            state_code=state,
            published_at=published_at,
            extra={
                "legiscan_bill_id": bill_id,
                "legiscan_number": number,
                "display_id": display_id,
                "change_hash": ch,
                "subjects": subjects,
                "status": bill.get("status"),
                "legiscan_url": legiscan_url,  # CC BY 4.0 attribution link
            },
        )
