"""Federal Register API adapter — for executive orders, HUD rules, proposed regs.

API docs: https://www.federalregister.gov/developers/api/v1
Free, no key required.
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc

logger = logging.getLogger(__name__)

BASE_URL = "https://www.federalregister.gov/api/v1"

# Federal Register agency slugs and CFR references relevant to rental housing
RELEVANT_AGENCIES = [
    "housing-and-urban-development-department",
    "federal-housing-finance-agency",
    "consumer-financial-protection-bureau",
    "justice-department",
]

SEARCH_TERMS = [
    "landlord tenant",
    "rental housing",
    "eviction",
    "fair housing",
    "security deposit",
    "rent control",
    "housing discrimination",
    "tenant screening",
    "source of income",
    "habitability",
]


class FederalRegisterAdapter(BaseAdapter):
    """Fetches federal rules, proposed rules, and notices from the Federal Register."""

    @property
    def source_name(self) -> str:
        return "federal_register"

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {
                "name": "Federal Register",
                "level": "federal",
                "state_code": None,
                "external_id": "federal-register",
            }
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Fetch documents published since `since` from relevant agencies."""
        docs = []
        since_str = since.strftime("%m/%d/%Y")

        # Strategy: search by agency (precise) rather than keyword (noisy).
        # Then do a narrow keyword search for terms unlikely to match unrelated agencies.
        for agency in RELEVANT_AGENCIES:
            page = 1
            while True:
                resp = await self.client.get(
                    f"{BASE_URL}/documents.json",
                    params={
                        "conditions[agencies][]": agency,
                        "conditions[publication_date][gte]": since_str,
                        "conditions[type][]": [
                            "RULE",
                            "PRORULE",
                            "NOTICE",
                            "PRESDOCU",
                        ],
                        "per_page": 50,
                        "page": page,
                        "order": "newest",
                        "fields[]": [
                            "title",
                            "abstract",
                            "document_number",
                            "html_url",
                            "publication_date",
                            "type",
                            "agencies",
                            "raw_text_url",
                        ],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])

                if not results:
                    break

                for item in results:
                    doc = self._normalize_item(item)
                    if doc:
                        docs.append(doc)

                total_pages = data.get("total_pages", 1)
                if page >= total_pages or page >= 3:
                    break
                page += 1

        # Also do targeted keyword searches but cap results heavily
        targeted_terms = ["landlord tenant", "eviction moratorium", "rent control", "tenant screening"]
        for term in targeted_terms:
            resp = await self.client.get(
                f"{BASE_URL}/documents.json",
                params={
                    "conditions[term]": term,
                    "conditions[publication_date][gte]": since_str,
                    "per_page": 10,
                    "page": 1,
                    "order": "newest",
                    "fields[]": [
                        "title",
                        "abstract",
                        "document_number",
                        "html_url",
                        "publication_date",
                        "type",
                        "agencies",
                    ],
                },
            )
            if resp.status_code == 200:
                for item in resp.json().get("results", []):
                    doc = self._normalize_item(item)
                    if doc:
                        docs.append(doc)

        # Deduplicate by external_id (same doc may match multiple search terms)
        seen = set()
        unique_docs = []
        for doc in docs:
            if doc.external_id not in seen:
                seen.add(doc.external_id)
                unique_docs.append(doc)

        logger.info(f"FederalRegister: fetched {len(unique_docs)} unique documents since {since_str}")
        return unique_docs

    def _normalize_item(self, item: dict) -> RawDoc | None:
        """Convert a Federal Register API result into a RawDoc."""
        title = item.get("title", "")
        doc_number = item.get("document_number", "")
        abstract = item.get("abstract", "") or ""
        doc_type = item.get("type", "")
        html_url = item.get("html_url", "")

        raw_text = f"{title}"
        if abstract:
            raw_text += f"\n\n{abstract}"

        agencies = item.get("agencies", [])
        agency_names = [a.get("name", "") for a in agencies if a.get("name")]
        if agency_names:
            raw_text += f"\n\nAgencies: {', '.join(agency_names)}"

        raw_text += f"\n\nDocument Type: {doc_type}"

        pub_date_str = item.get("publication_date")
        published = None
        if pub_date_str:
            try:
                published = datetime.strptime(pub_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        return RawDoc(
            external_id=doc_number,
            source_name=self.source_name,
            title=f"[Federal Register] {title}",
            url=html_url,
            raw_text=raw_text,
            jurisdiction_name="United States",
            jurisdiction_level="federal",
            state_code=None,
            published_at=published,
            extra={
                "document_number": doc_number,
                "type": doc_type,
                "agencies": agency_names,
            },
        )
