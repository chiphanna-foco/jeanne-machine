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

# Phase 0: only OH and CO
PHASE0_STATES = ["oh", "co"]

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
        super().__init__(client)
        self.states = states or PHASE0_STATES
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
            page = 1
            while True:
                resp = await self.client.get(
                    f"{BASE_URL}/bills",
                    params={
                        "jurisdiction": state,
                        "updated_since": since_str,
                        "page": page,
                        "per_page": 50,
                    },
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])

                if not results:
                    break

                for bill in results:
                    doc = self._normalize_bill(bill, state)
                    if doc:
                        docs.append(doc)

                # Check for next page
                pagination = data.get("pagination", {})
                if page >= pagination.get("max_page", 1):
                    break
                page += 1

            logger.info(f"OpenStates: fetched {len(docs)} bills from {state.upper()} since {since_str}")

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
