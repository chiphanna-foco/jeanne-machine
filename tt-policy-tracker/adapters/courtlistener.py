"""CourtListener API adapter — federal + state court rulings on landlord-tenant matters.

API docs: https://www.courtlistener.com/help/api/rest/
Free, API key required (via auth token).
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.courtlistener.com/api/rest/v4"

SEARCH_QUERIES = [
    "landlord tenant eviction",
    "security deposit return",
    "fair housing discrimination rental",
    "rent control stabilization",
    "source of income discrimination housing",
    "tenant screening background check",
    "habitability warranty rental",
    "rental registration ordinance",
]

# Map CourtListener court types to our jurisdiction levels
COURT_LEVEL_MAP = {
    "F": "federal",   # Federal
    "FB": "federal",  # Federal Bankruptcy
    "FD": "federal",  # Federal District
    "S": "state",     # State Supreme
    "SA": "state",    # State Appellate
    "ST": "state",    # State Trial
    "SS": "state",    # State Special
}


class CourtListenerAdapter(BaseAdapter):
    """Fetches court opinions on landlord-tenant matters from CourtListener."""

    @property
    def source_name(self) -> str:
        return "courtlistener"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        self.api_token = settings.courtlistener_api_token

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Token {self.api_token}"
        return headers

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {
                "name": "Federal and State Courts",
                "level": "court",
                "state_code": None,
                "external_id": "courtlistener",
            }
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Search for recent court opinions matching our topic keywords."""
        docs = []
        since_str = since.strftime("%Y-%m-%d")

        for query in SEARCH_QUERIES:
            try:
                page_docs = await self._search_opinions(query, since_str)
                docs.extend(page_docs)
            except Exception as e:
                logger.error(f"CourtListener search '{query}' failed: {type(e).__name__}: {e}")

        # Deduplicate by external_id
        seen = set()
        unique = []
        for doc in docs:
            if doc.external_id not in seen:
                seen.add(doc.external_id)
                unique.append(doc)

        logger.info(f"CourtListener: fetched {len(unique)} unique opinions since {since_str}")
        return unique

    async def _search_opinions(self, query: str, since_str: str) -> list[RawDoc]:
        """Search opinions endpoint for a single query."""
        docs = []

        resp = await self.client.get(
            f"{BASE_URL}/search/",
            params={
                "q": query,
                "type": "o",  # opinions
                "filed_after": since_str,
                "order_by": "dateFiled desc",
                "page_size": 20,
            },
            headers=self._headers(),
        )

        if resp.status_code != 200:
            body = resp.text[:300]
            raise Exception(f"CourtListener API {resp.status_code}: {body}")

        data = resp.json()
        results = data.get("results", [])

        for item in results:
            doc = self._normalize_opinion(item)
            if doc:
                docs.append(doc)

        return docs

    def _normalize_opinion(self, item: dict) -> RawDoc | None:
        """Convert a CourtListener search result into a RawDoc."""
        case_name = item.get("caseName", "") or item.get("case_name", "")
        court = item.get("court", "") or ""
        court_id = item.get("court_id", "") or ""
        date_filed = item.get("dateFiled", "") or item.get("date_filed", "")
        absolute_url = item.get("absolute_url", "")
        snippet = item.get("snippet", "") or ""
        docket_number = item.get("docketNumber", "") or item.get("docket_number", "")
        opinion_id = item.get("id", "") or item.get("cluster_id", "")

        if not case_name:
            return None

        # Build raw text for the classifier
        raw_text = f"Court Opinion: {case_name}"
        if docket_number:
            raw_text += f"\nDocket: {docket_number}"
        if court:
            raw_text += f"\nCourt: {court}"
        if date_filed:
            raw_text += f"\nFiled: {date_filed}"
        if snippet:
            # CourtListener returns HTML snippets — strip basic tags
            clean_snippet = snippet.replace("<mark>", "").replace("</mark>", "")
            clean_snippet = clean_snippet.replace("<em>", "").replace("</em>", "")
            raw_text += f"\n\nExcerpt: {clean_snippet}"

        # Determine jurisdiction level
        court_type = item.get("court_type", "") or ""
        level = COURT_LEVEL_MAP.get(court_type, "court")

        # Determine state code from court_id (e.g. "coloctapp" → CO)
        state_code = self._extract_state_code(court_id)

        published = None
        if date_filed:
            try:
                published = datetime.strptime(date_filed, "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else ""

        return RawDoc(
            external_id=f"cl-{opinion_id}",
            source_name=self.source_name,
            title=f"[Court] {case_name}",
            url=url,
            raw_text=raw_text,
            jurisdiction_name=court or "Unknown Court",
            jurisdiction_level=level,
            state_code=state_code,
            published_at=published,
            extra={
                "court": court,
                "court_id": court_id,
                "docket_number": docket_number,
            },
        )

    def _extract_state_code(self, court_id: str) -> str | None:
        """Try to extract a 2-letter state code from a CourtListener court_id."""
        state_prefixes = {
            "ala": "AL", "alaska": "AK", "ariz": "AZ", "ark": "AR", "cal": "CA",
            "colo": "CO", "conn": "CT", "del": "DE", "fla": "FL", "ga": "GA",
            "haw": "HI", "idaho": "ID", "ill": "IL", "ind": "IN", "iowa": "IA",
            "kan": "KS", "ky": "KY", "la": "LA", "me": "ME", "md": "MD",
            "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO",
            "mont": "MT", "neb": "NE", "nev": "NV", "nh": "NH", "nj": "NJ",
            "nm": "NM", "ny": "NY", "nc": "NC", "nd": "ND", "ohio": "OH",
            "okla": "OK", "or": "OR", "pa": "PA", "ri": "RI", "sc": "SC",
            "sd": "SD", "tenn": "TN", "tex": "TX", "utah": "UT", "vt": "VT",
            "va": "VA", "wash": "WA", "wva": "WV", "wis": "WI", "wyo": "WY",
            "dc": "DC",
        }
        court_lower = court_id.lower()
        for prefix, code in state_prefixes.items():
            if court_lower.startswith(prefix):
                return code
        return None
