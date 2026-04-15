"""Geotagger — Stage 4 of the enrichment pipeline.

Assigns jurisdiction metadata (state code, jurisdiction level) to documents.
Uses a lookup table for known jurisdictions and falls back to Haiku for ambiguous cases.
"""

import logging

logger = logging.getLogger(__name__)

# US state name → code lookup
STATE_CODES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# Reverse mapping: code → name
CODE_TO_STATE = {v: k.title() for k, v in STATE_CODES.items()}


def geotag_from_adapter(
    jurisdiction_name: str,
    jurisdiction_level: str,
    state_code: str | None,
) -> dict:
    """Derive geotag from adapter-provided jurisdiction info.

    Most adapters already provide structured jurisdiction data (state code,
    level). This function normalizes it and fills in gaps.

    Returns: {"state_code": str|None, "level": str, "jurisdiction_name": str}
    """
    # Normalize state code
    if state_code and len(state_code) == 2:
        state_code = state_code.upper()
    elif jurisdiction_name.lower() in STATE_CODES:
        state_code = STATE_CODES[jurisdiction_name.lower()]
    elif jurisdiction_name.upper() in CODE_TO_STATE:
        state_code = jurisdiction_name.upper()

    # Normalize level
    valid_levels = {"federal", "state", "county", "city", "court"}
    level = jurisdiction_level.lower() if jurisdiction_level.lower() in valid_levels else "state"

    return {
        "state_code": state_code,
        "level": level,
        "jurisdiction_name": jurisdiction_name,
    }
