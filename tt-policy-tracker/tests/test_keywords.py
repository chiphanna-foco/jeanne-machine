"""Tests for the curated housing-subject override signal."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.keywords import has_housing_subject_tag, passes_keyword_prescreen

def test_housing_subject_tag_fires_on_subjects_line():
    # HB26-1196's actual shape: thin title/desc but a curated Housing subject.
    text = ("HB26-1196: Tenant Data Information\n"
            "Concerning tenant data information.\n"
            "Subjects: Housing\n"
            "Latest action (2026-06-02): Governor Signed")
    assert has_housing_subject_tag(text) is True

def test_housing_subject_tag_requires_the_subjects_line_not_body_mention():
    # "housing" in the body but NO Subjects: line → not a curated tag.
    assert has_housing_subject_tag("A bill mentioning housing in passing.") is False
    # A Subjects line with an unrelated subject → no override.
    assert has_housing_subject_tag("Title\nSubjects: Transportation, Energy") is False

def test_housing_subject_tag_matches_various_subjects():
    assert has_housing_subject_tag("x\nSubjects: Landlord And Tenant") is True
    assert has_housing_subject_tag("x\nSubjects: Real Estate, Taxes") is True
    assert has_housing_subject_tag("x\nSubjects: Eviction") is True

def test_prescreen_still_works():
    assert passes_keyword_prescreen("Tenant Data Information") is True
    assert passes_keyword_prescreen("Wildfire grant funding") is False
