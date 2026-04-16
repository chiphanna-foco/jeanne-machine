"""Legistar API adapter — local municipal meeting agendas and legislation.

Legistar (owned by Granicus) hosts council meeting agendas, ordinances, and
legislation for thousands of US municipalities. Their API is unauthenticated
and returns JSON.

API docs: https://webapi.legistar.com/Help
Base URL pattern: https://webapi.legistar.com/v1/{client}/

Phase 2 scope: prioritize top metros with high TT user concentrations.
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc

logger = logging.getLogger(__name__)

BASE_URL = "https://webapi.legistar.com/v1"

# Legistar client slugs for priority cities.
# Each entry: (client_slug, city_name, state_code)
# These are the top metros by TT user concentration + major rental markets.
PRIORITY_CITIES = [
    ("denver", "Denver", "CO"),
    ("austintx", "Austin", "TX"),
    ("phoenix", "Phoenix", "AZ"),
    ("tampa", "Tampa", "FL"),
    ("columbus", "Columbus", "OH"),
    ("portland", "Portland", "OR"),
    ("seattle", "Seattle", "WA"),
    ("nashville", "Nashville", "TN"),
    ("atlanta", "Atlanta", "GA"),
    ("minneapolis", "Minneapolis", "MN"),
    ("stpaul", "St. Paul", "MN"),
    ("saltlakecity", "Salt Lake City", "UT"),
    ("lasvegas", "Las Vegas", "NV"),
    ("raleigh", "Raleigh", "NC"),
    ("charlottenc", "Charlotte", "NC"),
    ("sanantonio", "San Antonio", "TX"),
    ("jacksonville", "Jacksonville", "FL"),
    ("kansascity", "Kansas City", "MO"),
    ("mesa", "Mesa", "AZ"),
    ("tucson", "Tucson", "AZ"),
    ("oakland", "Oakland", "CA"),
    ("sacramento", "Sacramento", "CA"),
    ("sanfrancisco", "San Francisco", "CA"),
    ("losangeles", "Los Angeles", "CA"),
    ("chicago", "Chicago", "IL"),
    ("newyork", "New York City", "NY"),
    ("boston", "Boston", "MA"),
    ("philadelphia", "Philadelphia", "PA"),
    ("dc", "Washington DC", "DC"),
    ("baltimore", "Baltimore", "MD"),
]

# Keywords to filter legislation titles — Legistar returns ALL legislation
# for a city, most of which is about potholes and parks.
HOUSING_KEYWORDS = [
    "landlord", "tenant", "rental", "eviction", "security deposit",
    "rent control", "rent stabilization", "fair housing", "habitability",
    "housing code", "rental registration", "rental license", "rental inspection",
    "application fee", "screening", "source of income", "section 8",
    "voucher", "lease", "renter", "dwelling unit", "residential rental",
    "just cause", "relocation assistance", "rent increase",
]


class LegistarAdapter(BaseAdapter):
    """Fetches municipal legislation from Legistar/Granicus for priority cities."""

    @property
    def source_name(self) -> str:
        return "legistar"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        cities: list[tuple[str, str, str]] | None = None,
    ):
        super().__init__(client or httpx.AsyncClient(timeout=30.0))
        self.cities = cities or PRIORITY_CITIES

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {
                "name": city_name,
                "level": "city",
                "state_code": state_code,
                "external_id": f"legistar-{slug}",
            }
            for slug, city_name, state_code in self.cities
        ]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Fetch recent legislation from all configured cities."""
        docs = []
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")

        for slug, city_name, state_code in self.cities:
            try:
                city_docs = await self._fetch_city_legislation(
                    slug, city_name, state_code, since_str
                )
                docs.extend(city_docs)
                if city_docs:
                    logger.info(f"Legistar: {len(city_docs)} items from {city_name}")
            except Exception as e:
                logger.warning(
                    f"Legistar: {city_name} ({slug}) failed: {type(e).__name__}: {str(e)[:200]}"
                )

        logger.info(f"Legistar: {len(docs)} total items from {len(self.cities)} cities")
        return docs

    async def _fetch_city_legislation(
        self, slug: str, city_name: str, state_code: str, since_str: str
    ) -> list[RawDoc]:
        """Fetch legislation for a single city, pre-filtered by housing keywords."""
        docs = []

        resp = await self.client.get(
            f"{BASE_URL}/{slug}/matters",
            params={
                "$filter": f"MatterIntroDate ge datetime'{since_str}'",
                "$orderby": "MatterIntroDate desc",
                "$top": 100,
            },
        )

        if resp.status_code == 404:
            logger.debug(f"Legistar: {slug} returned 404 — client may not exist")
            return []
        if resp.status_code != 200:
            raise Exception(f"Legistar API {resp.status_code} for {slug}: {resp.text[:200]}")

        matters = resp.json()
        if not isinstance(matters, list):
            return []

        for matter in matters:
            title = (matter.get("MatterTitle") or matter.get("MatterName") or "").strip()
            if not title:
                continue

            # Pre-filter: only include matters with housing-related keywords in the title
            title_lower = title.lower()
            if not any(kw in title_lower for kw in HOUSING_KEYWORDS):
                continue

            doc = self._normalize_matter(matter, slug, city_name, state_code)
            if doc:
                docs.append(doc)

        return docs

    def _normalize_matter(
        self, matter: dict, slug: str, city_name: str, state_code: str
    ) -> RawDoc | None:
        """Convert a Legistar matter into a RawDoc."""
        matter_id = matter.get("MatterId", "")
        title = (matter.get("MatterTitle") or matter.get("MatterName") or "").strip()
        body_name = matter.get("MatterBodyName", "") or ""
        matter_type = matter.get("MatterTypeName", "") or ""
        file_number = matter.get("MatterFile", "") or ""
        status = matter.get("MatterStatusName", "") or ""
        intro_date = matter.get("MatterIntroDate", "") or ""

        raw_text = f"[{city_name}, {state_code}] {title}"
        if file_number:
            raw_text += f"\nFile: {file_number}"
        if matter_type:
            raw_text += f"\nType: {matter_type}"
        if body_name:
            raw_text += f"\nBody: {body_name}"
        if status:
            raw_text += f"\nStatus: {status}"

        published = None
        if intro_date:
            try:
                published = datetime.fromisoformat(intro_date.replace("T", " ").split(".")[0])
            except (ValueError, TypeError):
                pass

        url = f"https://{slug}.legistar.com/LegislationDetail.aspx?ID={matter_id}"

        return RawDoc(
            external_id=f"legistar-{slug}-{matter_id}",
            source_name=self.source_name,
            title=f"[{city_name}] {title}",
            url=url,
            raw_text=raw_text,
            jurisdiction_name=city_name,
            jurisdiction_level="city",
            state_code=state_code,
            published_at=published,
            extra={
                "legistar_client": slug,
                "matter_type": matter_type,
                "file_number": file_number,
                "status": status,
                "body": body_name,
            },
        )
