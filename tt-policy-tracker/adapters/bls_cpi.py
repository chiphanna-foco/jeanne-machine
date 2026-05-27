"""BLS Consumer Price Index adapter.

Pulls CPI-U series from the BLS public API to drive rent-cap math for
jurisdictions that tie allowable rent increases to CPI:

  - Oregon (SB 608 / SB 611): min(7% + West-region CPI annual change, 10%)
  - California (AB 1482): min(5% + regional CPI April-over-April change, 10%)

BLS API: https://api.bls.gov/publicAPI/v2/timeseries/data/
Free tier: 25 queries/day unregistered, 500/day with a registration key.

Dual role:
  - fetch_readings() returns structured CpiReading-shaped dicts for the
    /api/cpi endpoint + cpi_reading table (what Autopilot consumes).
  - fetch_new_items() wraps the latest reading per series as a RawDoc so
    CPI changes also flow through the classifier and show on the dashboard.

NOTE: series IDs and rent-cap formula constants are best-effort and should
be verified against the agencies' published methodology. /admin/refresh-cpi
reports per-series status so a wrong ID surfaces immediately.
"""

import logging
from datetime import datetime

import httpx

from adapters.base import BaseAdapter, RawDoc
from config import settings

logger = logging.getLogger(__name__)

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# CPI-U, not seasonally adjusted (NSA is what rent statutes reference).
# {series_id: (area_name, [rent_cap_programs])}
CPI_SERIES = {
    "CUUR0400SA0": ("West Region", ["oregon"]),
    "CUURS49ASA0": ("Los Angeles-Long Beach-Anaheim", ["ca_ab1482"]),
    "CUURS49BSA0": ("San Francisco-Oakland-Hayward", ["ca_ab1482"]),
    "CUURS49ESA0": ("Riverside-San Bernardino-Ontario", ["ca_ab1482"]),
    "CUURS49DSA0": ("Seattle-Tacoma-Bellevue", []),
}

# Rent-cap formula constants. Verify against agency methodology.
OREGON_BASE_PCT = 7.0
OREGON_MAX_PCT = 10.0
CA_AB1482_BASE_PCT = 5.0
CA_AB1482_MAX_PCT = 10.0


class BlsCpiAdapter(BaseAdapter):
    """Fetches CPI-U series from BLS."""

    @property
    def source_name(self) -> str:
        return "bls_cpi"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(timeout=60.0))
        self.last_run_stats: dict[str, dict] = {}

    async def discover_jurisdictions(self) -> list[dict]:
        return [
            {"name": "United States", "level": "federal", "state_code": None},
        ]

    async def _fetch_series(self, start_year: int, end_year: int) -> dict[str, list[dict]]:
        """Return {series_id: [reading_dict, ...]} for all configured series."""
        payload: dict = {
            "seriesid": list(CPI_SERIES.keys()),
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if settings.bls_api_key:
            payload["registrationkey"] = settings.bls_api_key

        resp = await self.client.post(
            BLS_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise Exception(f"BLS API status={data.get('status')}: {data.get('message')}")

        out: dict[str, list[dict]] = {}
        for series in data.get("Results", {}).get("series", []):
            sid = series.get("seriesID", "")
            area_name = CPI_SERIES.get(sid, (sid, []))[0]
            readings = []
            for row in series.get("data", []):
                try:
                    value = float(row["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                readings.append(
                    {
                        "series_id": sid,
                        "area_name": area_name,
                        "year": int(row["year"]),
                        "period": row["period"],          # M01..M12, M13=annual
                        "period_name": row.get("periodName"),
                        "value": value,
                    }
                )
            out[sid] = readings
        return out

    async def fetch_readings(self, start_year: int, end_year: int) -> dict[str, list[dict]]:
        """Public entry for the refresh endpoint. Records per-series stats."""
        stats: dict[str, dict] = {}
        try:
            series_map = await self._fetch_series(start_year, end_year)
        except Exception as e:
            for sid, (area, _) in CPI_SERIES.items():
                stats[sid] = {"area": area, "count": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            self.last_run_stats = stats
            raise

        for sid, (area, _) in CPI_SERIES.items():
            readings = series_map.get(sid, [])
            stats[sid] = {"area": area, "count": len(readings), "error": None if readings else "no data returned"}
        self.last_run_stats = stats
        return series_map

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Wrap the latest reading per series as a RawDoc for the pipeline."""
        end_year = datetime.utcnow().year
        start_year = end_year - 1
        try:
            series_map = await self.fetch_readings(start_year, end_year)
        except Exception as e:
            logger.error(f"bls_cpi: fetch failed: {e}")
            return []

        docs: list[RawDoc] = []
        for sid, readings in series_map.items():
            if not readings:
                continue
            # BLS returns newest first; latest monthly reading is readings[0]
            latest = readings[0]
            yoy = self._yoy_change(readings, latest)
            doc = self._normalize(latest, yoy)
            if doc:
                docs.append(doc)
        return docs

    @staticmethod
    def _yoy_change(readings: list[dict], latest: dict) -> float | None:
        """Percent change vs the same period one year earlier."""
        target_year = latest["year"] - 1
        for r in readings:
            if r["year"] == target_year and r["period"] == latest["period"]:
                if r["value"]:
                    return round((latest["value"] - r["value"]) / r["value"] * 100, 2)
        return None

    def _normalize(self, reading: dict, yoy: float | None) -> RawDoc | None:
        sid = reading["series_id"]
        area = reading["area_name"]
        period = reading.get("period_name") or reading["period"]
        yoy_str = f"{yoy:+.2f}% YoY" if yoy is not None else "YoY n/a"
        text = (
            f"CPI-U ({area}), {period} {reading['year']}: index {reading['value']}, {yoy_str}. "
            f"Used for rent-stabilization caps (CA AB 1482 / Oregon SB 608)."
        )
        return RawDoc(
            external_id=f"bls-{sid}-{reading['year']}-{reading['period']}",
            source_name=self.source_name,
            title=f"CPI-U {area} {period} {reading['year']}: {yoy_str}",
            url="https://www.bls.gov/cpi/",
            raw_text=text,
            jurisdiction_name=area,
            jurisdiction_level="federal",
            state_code=None,
            published_at=None,
            extra={
                "series_id": sid,
                "value": reading["value"],
                "yoy_change_pct": yoy,
            },
        )


def compute_rent_caps(latest_by_series: dict[str, dict]) -> list[dict]:
    """Given {series_id: latest_reading_with_yoy}, compute allowable rent caps.

    Each latest_reading dict must include 'value' and 'yoy_change_pct'.
    Returns a list of {program, area, cpi_change_pct, cap_pct, formula}.
    """
    caps: list[dict] = []
    for sid, (area, programs) in CPI_SERIES.items():
        reading = latest_by_series.get(sid)
        if not reading:
            continue
        cpi_change = reading.get("yoy_change_pct")
        if cpi_change is None:
            continue
        for program in programs:
            if program == "oregon":
                cap = min(OREGON_BASE_PCT + cpi_change, OREGON_MAX_PCT)
                caps.append({
                    "program": "Oregon SB 608/611",
                    "area": area,
                    "cpi_change_pct": cpi_change,
                    "cap_pct": round(cap, 2),
                    "formula": f"min({OREGON_BASE_PCT}% + CPI, {OREGON_MAX_PCT}%)",
                })
            elif program == "ca_ab1482":
                cap = min(CA_AB1482_BASE_PCT + cpi_change, CA_AB1482_MAX_PCT)
                caps.append({
                    "program": "California AB 1482",
                    "area": area,
                    "cpi_change_pct": cpi_change,
                    "cap_pct": round(cap, 2),
                    "formula": f"min({CA_AB1482_BASE_PCT}% + CPI, {CA_AB1482_MAX_PCT}%)",
                })
    return caps
