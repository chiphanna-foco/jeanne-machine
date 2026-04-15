"""Abstract base class for all source adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import httpx


@dataclass
class RawDoc:
    """Normalized document returned by every adapter."""

    external_id: str
    source_name: str
    title: str
    url: str
    raw_text: str
    jurisdiction_name: str
    jurisdiction_level: str  # federal | state | county | city | court
    state_code: str | None = None
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)


class BaseAdapter(ABC):
    """Every source adapter must implement these three methods."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=30.0)

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique name for this adapter (e.g. 'openstates', 'congress')."""

    @abstractmethod
    async def discover_jurisdictions(self) -> list[dict]:
        """Return a list of jurisdictions this adapter can cover.

        Each dict should have at minimum: name, level, state_code (if applicable).
        """

    @abstractmethod
    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Fetch items updated/created since the given datetime.

        Returns normalized RawDoc instances.
        """

    def normalize(self, raw: dict) -> RawDoc:
        """Optional override — transform a source-specific dict into a RawDoc.

        Subclasses may override this if they want a separate normalization step,
        but fetch_new_items can also return RawDoc directly.
        """
        raise NotImplementedError("Override normalize() or return RawDoc from fetch_new_items().")
