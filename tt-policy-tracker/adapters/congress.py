"""Congress.gov API adapter — primary federal source.

API docs: https://api.congress.gov/
Requires an api.data.gov API key.
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.congress.gov/v3"

# Policy areas that map to our 10 target topics
RELEVANT_POLICY_AREAS = {
    "housing and community development",
    "law",
    "civil rights and liberties, minority issues",
    "government operations and politics",
    "finance and financial sector",
}


class CongressAdapter(BaseAdapter):
    """Fetches federal bills from the Congress.gov API."""

    @property
    def source_name(self) -> str:
        return "congress"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client)
        self.api_key = settings.congress_api_key

    def _params(self, extra: dict | None = None) -> dict:
        params = {"api_key": self.api_key, "format": "json"}
        if extra:
            params.update(extra)
        return params

    async def discover_jurisdictions(self) -> list[dict]:
        """Congress is always federal jurisdiction."""
        return [
            {
                "name": "United States Congress",
                "level": "federal",
                "state_code": None,
                "external_id": "us-congress",
            }
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Fetch bills updated since `since` from Congress.gov."""
        docs = []
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        offset = 0
        limit = 50

        while True:
            resp = await self.client.get(
                f"{BASE_URL}/bill",
                params=self._params(
                    {
                        "fromDateTime": since_str,
                        "sort": "updateDate+desc",
                        "offset": offset,
                        "limit": limit,
                    }
                ),
            )
            resp.raise_for_status()
            data = resp.json()
            bills = data.get("bills", [])

            if not bills:
                break

            for bill in bills:
                doc = await self._normalize_bill(bill)
                if doc:
                    docs.append(doc)

            # Check pagination
            pagination = data.get("pagination", {})
            total = pagination.get("count", 0)
            offset += limit
            if offset >= total or offset >= 500:  # Cap at 500 for Phase 0
                break

        logger.info(f"Congress: fetched {len(docs)} bills since {since_str}")
        return docs

    async def _normalize_bill(self, bill: dict) -> RawDoc | None:
        """Convert a Congress.gov bill summary into a RawDoc.

        Optionally fetches the bill detail for summaries.
        """
        bill_type = bill.get("type", "")
        number = bill.get("number", "")
        congress = bill.get("congress", "")
        title = bill.get("title", "")
        url = bill.get("url", "")

        identifier = f"{bill_type}{number}-{congress}"

        # Build raw text
        raw_text = f"{identifier}: {title}"

        policy_area = bill.get("policyArea", {})
        if policy_area:
            raw_text += f"\n\nPolicy Area: {policy_area.get('name', '')}"

        latest_action = bill.get("latestAction", {})
        if latest_action:
            raw_text += f"\n\nLatest Action ({latest_action.get('actionDate', '')}): {latest_action.get('text', '')}"

        # Try to fetch the bill summary for more text
        if url:
            try:
                detail_resp = await self.client.get(
                    url, params=self._params(), timeout=15.0
                )
                if detail_resp.status_code == 200:
                    detail = detail_resp.json().get("bill", {})
                    summaries = detail.get("summaries", {})
                    if isinstance(summaries, dict):
                        summary_url = summaries.get("url")
                        if summary_url:
                            sum_resp = await self.client.get(
                                summary_url, params=self._params(), timeout=15.0
                            )
                            if sum_resp.status_code == 200:
                                sum_list = sum_resp.json().get("summaries", [])
                                if sum_list:
                                    raw_text += f"\n\nSummary: {sum_list[0].get('text', '')}"
            except (httpx.HTTPError, KeyError, TypeError):
                pass  # Non-critical — we still have the title

        # Parse dates
        update_date = bill.get("updateDate") or bill.get("updateDateIncludingText")
        published = None
        if update_date:
            try:
                published = datetime.fromisoformat(update_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        congress_url = f"https://www.congress.gov/bill/{congress}th-congress/{bill_type.lower()}-bill/{number}"

        return RawDoc(
            external_id=identifier,
            source_name=self.source_name,
            title=f"[US] {identifier}: {title}",
            url=congress_url,
            raw_text=raw_text,
            jurisdiction_name="United States",
            jurisdiction_level="federal",
            state_code=None,
            published_at=published,
            extra={
                "congress": congress,
                "bill_type": bill_type,
                "number": number,
                "policy_area": policy_area.get("name", "") if policy_area else "",
            },
        )
