"""Unit tests for the geotagger module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.geotagger import geotag_from_adapter


def test_geotag_state_code_passthrough():
    result = geotag_from_adapter("Colorado", "state", "CO")
    assert result["state_code"] == "CO"
    assert result["level"] == "state"


def test_geotag_state_name_lookup():
    result = geotag_from_adapter("ohio", "state", None)
    assert result["state_code"] == "OH"


def test_geotag_federal():
    result = geotag_from_adapter("United States", "federal", None)
    assert result["state_code"] is None
    assert result["level"] == "federal"


def test_geotag_invalid_level_normalized():
    result = geotag_from_adapter("Denver", "CITY", "CO")
    assert result["level"] == "city"


def test_geotag_unknown_level_defaults_to_state():
    result = geotag_from_adapter("Somewhere", "unknown", "TX")
    assert result["level"] == "state"


def test_geotag_code_as_name():
    result = geotag_from_adapter("CO", "state", None)
    assert result["state_code"] == "CO"
