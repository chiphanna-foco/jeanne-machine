"""Open States API v3 adapter — primary state-level source.

Phase 0 scope: Ohio (OH) and Colorado (CO) only.
API docs: https://docs.openstates.org/api-v3/
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.openstates.org"

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

    @property
    def source_name(self) -> str:
        return "openstates"

    def __init__(self, client: httpx.AsyncClient | None = None, states: list[str] | None = None):
        super().__init__(client or httpx.AsyncClient(timeout=120.0))
        if states is None:
            states = ALL_STATES if settings.openstates_scope == "all" else PHASE0_STATES
        self.states = states
        self.api_key = settings.openstates_api_key

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "Accept": "application/json"}

    async def discover_jurisdictions(self) -> list[dict]:
        """Return jurisdiction info for the configured states."""
        jurisdictions = []
        for state in self.states:
            resp = await self.client.get(
                f"{BASE_URL}/jurisdictions",
                params={"classification": "state"},
                headers=self._headers(),
            )
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

        for state in self.states:
            jurisdiction_id = STATE_TO_JURISDICTION.get(state.lower())
            if not jurisdiction_id:
                logger.warning(f"No OCD jurisdiction ID for state: {state}")
                continue

            try:
                state_docs = await self._fetch_state_bills(state, jurisdiction_id, since_str)
                docs.extend(state_docs)
                logger.info(f"OpenStates: fetched {len(state_docs)} bills from {state.upper()} since {since_str}")
            except Exception as e:
                logger.error(f"OpenStates: failed for {state.upper()}: {e}")
                # Continue with other states instead of aborting

        return docs

    async def _fetch_state_bills(self, state: str, jurisdiction_id: str, since_str: str) -> list[RawDoc]:
        """Fetch bills for a single state with retries and smaller page size."""
        import asyncio

        docs = []
        page = 1
        max_pages = 50  # Cap to avoid runaway pagination (50 pages × 20/page = 1000 bills/state/run)

        while page <= max_pages:
            resp = None
            last_err = None

            # Retry up to 3 times per page
            for attempt in range(3):
                try:
                    resp = await self.client.get(
                        f"{BASE_URL}/bills",
                        params={
                            "jurisdiction": jurisdiction_id,
                            "updated_since": since_str,
                            "page": page,
                            "per_page": 20,
                            "apikey": self.api_key,
                        },
                        headers=self._headers(),
                    )
                    break
                except Exception as req_err:
                    last_err = req_err
                    logger.warning(f"OpenStates {state.upper()} page {page} attempt {attempt+1} failed: {type(req_err).__name__}")
                    await asyncio.sleep(2 * (attempt + 1))

            if resp is None:
                raise Exception(f"Open States request failed for {state.upper()} after 3 retries: {type(last_err).__name__}: {last_err}")

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
