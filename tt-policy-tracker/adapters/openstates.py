"""Open States API v3 adapter — primary state-level source.

Phase 0 scope: Ohio (OH) and Colorado (CO) only.
API docs: https://docs.openstates.org/api-v3/
"""

import asyncio
import logging
import time
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.openstates.org"

# Free-tier Open States caps at 10 req/min. We pace at ~7.5/min (8s min
# interval) and share that rate state across every OpenStatesAdapter
# instance in the process — concurrent pipelines (e.g. a cron run firing
# while a manual backfill is in progress) would otherwise each have their
# own limiter and collectively exceed the cap.
OS_MIN_REQUEST_INTERVAL = 8.0

# Phase 0: OH, CO, WA. Phase 2: all 50 states + DC.
PHASE0_STATES = ["oh", "co", "wa"]

# Open States API v3 requires OCD jurisdiction IDs
STATE_TO_JURISDICTION = {
    "al": "ocd-jurisdiction/country:us/state:al/government",
    "ak": "ocd-jurisdiction/country:us/state:ak/government",
    "az": "ocd-jurisdiction/country:us/state:az/government",
    "ar": "ocd-jurisdiction/country:us/state:ar/government",
    "ca": "ocd-jurisdiction/country:us/state:ca/government",
    "co": "ocd-jurisdiction/country:us/state:co/government",
    "ct": "ocd-jurisdiction/country:us/state:ct/government",
    "de": "ocd-jurisdiction/country:us/state:de/government",
    "fl": "ocd-jurisdiction/country:us/state:fl/government",
    "ga": "ocd-jurisdiction/country:us/state:ga/government",
    "hi": "ocd-jurisdiction/country:us/state:hi/government",
    "id": "ocd-jurisdiction/country:us/state:id/government",
    "il": "ocd-jurisdiction/country:us/state:il/government",
    "in": "ocd-jurisdiction/country:us/state:in/government",
    "ia": "ocd-jurisdiction/country:us/state:ia/government",
    "ks": "ocd-jurisdiction/country:us/state:ks/government",
    "ky": "ocd-jurisdiction/country:us/state:ky/government",
    "la": "ocd-jurisdiction/country:us/state:la/government",
    "me": "ocd-jurisdiction/country:us/state:me/government",
    "md": "ocd-jurisdiction/country:us/state:md/government",
    "ma": "ocd-jurisdiction/country:us/state:ma/government",
    "mi": "ocd-jurisdiction/country:us/state:mi/government",
    "mn": "ocd-jurisdiction/country:us/state:mn/government",
    "ms": "ocd-jurisdiction/country:us/state:ms/government",
    "mo": "ocd-jurisdiction/country:us/state:mo/government",
    "mt": "ocd-jurisdiction/country:us/state:mt/government",
    "ne": "ocd-jurisdiction/country:us/state:ne/government",
    "nv": "ocd-jurisdiction/country:us/state:nv/government",
    "nh": "ocd-jurisdiction/country:us/state:nh/government",
    "nj": "ocd-jurisdiction/country:us/state:nj/government",
    "nm": "ocd-jurisdiction/country:us/state:nm/government",
    "ny": "ocd-jurisdiction/country:us/state:ny/government",
    "nc": "ocd-jurisdiction/country:us/state:nc/government",
    "nd": "ocd-jurisdiction/country:us/state:nd/government",
    "oh": "ocd-jurisdiction/country:us/state:oh/government",
    "ok": "ocd-jurisdiction/country:us/state:ok/government",
    "or": "ocd-jurisdiction/country:us/state:or/government",
    "pa": "ocd-jurisdiction/country:us/state:pa/government",
    "ri": "ocd-jurisdiction/country:us/state:ri/government",
    "sc": "ocd-jurisdiction/country:us/state:sc/government",
    "sd": "ocd-jurisdiction/country:us/state:sd/government",
    "tn": "ocd-jurisdiction/country:us/state:tn/government",
    "tx": "ocd-jurisdiction/country:us/state:tx/government",
    "ut": "ocd-jurisdiction/country:us/state:ut/government",
    "vt": "ocd-jurisdiction/country:us/state:vt/government",
    "va": "ocd-jurisdiction/country:us/state:va/government",
    "wa": "ocd-jurisdiction/country:us/state:wa/government",
    "wv": "ocd-jurisdiction/country:us/state:wv/government",
    "wi": "ocd-jurisdiction/country:us/state:wi/government",
    "wy": "ocd-jurisdiction/country:us/state:wy/government",
    "dc": "ocd-jurisdiction/country:us/district:dc/government",
}

ALL_STATES = list(STATE_TO_JURISDICTION.keys())

# Topics we consider relevant for pre-filtering via Open States subject tags
RELEVANT_SUBJECTS = {
    "housing",
    "landlord",
    "tenant",
    "rental",
    "eviction",
    "security deposit",
    "rent control",
    "fair housing",
    "habitability",
    "discrimination",
    "screening",
    "application fee",
}


class OpenStatesAdapter(BaseAdapter):
    """Fetches state-level bills from the Open States API v3."""

    # Class-level rate state so concurrent adapter instances share the budget.
    _last_request_at: float = 0.0
    _rate_lock: asyncio.Lock | None = None

    @property
    def source_name(self) -> str:
        return "openstates"

    def __init__(self, client: httpx.AsyncClient | None = None, states: list[str] | None = None):
        super().__init__(client or httpx.AsyncClient(timeout=120.0))
        if states is None:
            states = ALL_STATES if settings.openstates_scope == "all" else PHASE0_STATES
        self.states = states
        self.api_key = settings.openstates_api_key
        # Lazy-init the class-level lock on first instance so we don't need a
        # running event loop at module import time.
        if OpenStatesAdapter._rate_lock is None:
            OpenStatesAdapter._rate_lock = asyncio.Lock()

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "Accept": "application/json"}

    async def _request(
        self,
        path: str,
        params: dict,
        max_retries: int = 10,
    ) -> httpx.Response:
        """Rate-limited GET with 429 / transient-error backoff.

        Paces requests OS_MIN_REQUEST_INTERVAL seconds apart (shared across
        all adapter instances). On 429, honors Retry-After but never sleeps
        less than an exponentially-growing floor — so successive 429s wait
        progressively longer in case OS uses a multi-minute rolling window.
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            assert OpenStatesAdapter._rate_lock is not None
            async with OpenStatesAdapter._rate_lock:
                elapsed = time.monotonic() - OpenStatesAdapter._last_request_at
                if elapsed < OS_MIN_REQUEST_INTERVAL:
                    await asyncio.sleep(OS_MIN_REQUEST_INTERVAL - elapsed)
                OpenStatesAdapter._last_request_at = time.monotonic()

            try:
                resp = await self.client.get(
                    f"{BASE_URL}{path}", params=params, headers=self._headers()
                )
            except Exception as e:
                last_exc = e
                wait = min(2 ** attempt, 300)
                logger.warning(
                    f"OpenStates {path} attempt {attempt+1} request failed "
                    f"({type(e).__name__}); sleeping {wait}s"
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code == 429:
                # Exponential floor: 60, 120, 240, 480, capped at 600s
                exp_floor = min(60 * (2 ** attempt), 600)
                retry_after = exp_floor
                try:
                    header_value = int(resp.headers.get("Retry-After", "0"))
                    retry_after = max(header_value, exp_floor)
                except (TypeError, ValueError):
                    pass
                logger.warning(
                    f"OpenStates {path} 429 rate-limited; sleeping {retry_after}s "
                    f"(attempt {attempt+1}/{max_retries})"
                )
                await asyncio.sleep(retry_after)
                continue

            return resp

        if last_exc:
            raise Exception(
                f"OpenStates {path}: {max_retries} retries exhausted: "
                f"{type(last_exc).__name__}: {last_exc}"
            )
        raise Exception(
            f"OpenStates {path}: {max_retries} retries exhausted (last status 429)"
        )

    async def discover_jurisdictions(self) -> list[dict]:
        """Return jurisdiction info for the configured states."""
        jurisdictions = []
        for state in self.states:
            resp = await self._request("/jurisdictions", {"classification": "state"})
            resp.raise_for_status()
            for j in resp.json().get("results", []):
                jur_state = j.get("id", "").split("/")[-1].split(":")[0] if j.get("id") else ""
                if jur_state in self.states or j.get("name", "").lower() in self.states:
                    jurisdictions.append(
                        {
                            "name": j["name"],
                            "level": "state",
                            "state_code": state.upper(),
                            "external_id": j["id"],
                        }
                    )
            break  # Jurisdictions endpoint returns all states at once
        return jurisdictions

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Fetch bills updated since `since` for the configured states."""
        docs = []
        since_str = since.strftime("%Y-%m-%d")
        # Per-state results recorded on the instance so the pipeline can surface them.
        self.last_run_stats: dict[str, dict] = {}

        for state in self.states:
            jurisdiction_id = STATE_TO_JURISDICTION.get(state.lower())
            if not jurisdiction_id:
                logger.warning(f"No OCD jurisdiction ID for state: {state}")
                self.last_run_stats[state.upper()] = {"fetched": 0, "error": "no jurisdiction id"}
                continue

            try:
                state_docs = await self._fetch_state_bills(state, jurisdiction_id, since_str)
                docs.extend(state_docs)
                self.last_run_stats[state.upper()] = {"fetched": len(state_docs), "error": None}
                logger.info(f"OpenStates: fetched {len(state_docs)} bills from {state.upper()} since {since_str}")
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                logger.error(f"OpenStates: failed for {state.upper()}: {msg}")
                self.last_run_stats[state.upper()] = {"fetched": 0, "error": msg}
                # Continue with other states instead of aborting

        return docs

    async def _fetch_state_bills(self, state: str, jurisdiction_id: str, since_str: str) -> list[RawDoc]:
        """Fetch bills for a single state, rate-limited and 429-aware."""
        docs = []
        page = 1
        max_pages = 200  # 200 pages × 20/page = 4000 bills/state/run

        while page <= max_pages:
            resp = await self._request(
                "/bills",
                {
                    "jurisdiction": jurisdiction_id,
                    "updated_since": since_str,
                    "sort": "updated_desc",
                    "page": page,
                    "per_page": 20,
                },
            )

            if resp.status_code != 200:
                body = resp.text[:500]
                raise Exception(f"Open States API {resp.status_code} for {state.upper()}: {body}")

            data = resp.json()
            results = data.get("results", [])

            if not results:
                break

            for bill in results:
                doc = self._normalize_bill(bill, state)
                if doc:
                    docs.append(doc)

            pagination = data.get("pagination", {})
            if page >= pagination.get("max_page", 1):
                break
            page += 1

        return docs

    def _normalize_bill(self, bill: dict, state: str) -> RawDoc | None:
        """Convert an Open States bill dict into a RawDoc."""
        title = bill.get("title", "")
        identifier = bill.get("identifier", "")
        openstates_url = bill.get("openstates_url", "")

        # Build raw text from title + abstract + latest version text if available
        abstract = ""
        abstracts = bill.get("abstracts", [])
        if abstracts:
            abstract = abstracts[0].get("abstract", "")

        raw_text = f"{identifier}: {title}"
        if abstract:
            raw_text += f"\n\nAbstract: {abstract}"

        # Add subject/classification info for the classifier
        subjects = bill.get("subject", [])
        if subjects:
            raw_text += f"\n\nSubjects: {', '.join(subjects)}"

        # Parse dates
        created = bill.get("created_at")
        published = None
        if created:
            try:
                published = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return RawDoc(
            external_id=bill.get("id", identifier),
            source_name=self.source_name,
            title=f"[{state.upper()}] {identifier}: {title}",
            url=openstates_url or "",
            raw_text=raw_text,
            jurisdiction_name=state.upper(),
            jurisdiction_level="state",
            state_code=state.upper(),
            published_at=published,
            extra={
                "identifier": identifier,
                "session": bill.get("session", ""),
                "subjects": subjects,
                "classification": bill.get("classification", []),
            },
        )
