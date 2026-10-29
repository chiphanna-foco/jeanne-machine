"""Unit tests for the session-ended check behind the digest's Worth watching list."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.sessions import session_end_year, session_over

OCT = datetime(2026, 10, 29)


def test_parses_openstates_session_shapes():
    assert session_end_year("https://openstates.org/ia/bills/2025-2026/SF2225/") == ("IA", 2026)
    assert session_end_year("https://openstates.org/hi/bills/2026/SB416/") == ("HI", 2026)
    assert session_end_year("https://openstates.org/co/bills/2025A/HB25-1196/") == ("CO", 2025)
    assert session_end_year("https://openstates.org/me/bills/132/LD1927/") == ("ME", 2026)


def test_unknown_urls_are_never_called_over():
    for url in (
        None,
        "",
        "https://lims.dccouncil.gov/Legislation/B26-0829",
        "https://legiscan.com/CO/bill/HB1045/2026",
        "https://openstates.org/nj/bills/222/S4817/",  # numbered, no mapping
        "https://www.bls.gov/cpi/",
    ):
        assert session_over(url, OCT) is False


def test_adjourned_part_time_sessions_are_over():
    assert session_over("https://openstates.org/ia/bills/2025-2026/SF2225/", OCT)
    assert session_over("https://openstates.org/hi/bills/2026/SB416/", OCT)
    assert session_over("https://openstates.org/me/bills/132/LD1927/", OCT)
    assert session_over("https://openstates.org/mn/bills/2025-2026/SF4102/", OCT)


def test_future_and_year_round_sessions_stay_open():
    # 2027 prefiles
    assert not session_over("https://openstates.org/va/bills/2027/HB79/", OCT)
    # full-time legislatures can still pass bills this fall
    assert not session_over("https://openstates.org/pa/bills/2025-2026/HB1705/", OCT)
    # ...but not once the session's last year is behind us
    assert session_over("https://openstates.org/pa/bills/2023-2024/HB1/", OCT)


def test_cutoff_dates():
    hi = "https://openstates.org/hi/bills/2026/SB416/"
    assert not session_over(hi, datetime(2026, 6, 30))
    assert session_over(hi, datetime(2026, 7, 1))
    ca = "https://openstates.org/ca/bills/20252026/AB1/"
    assert not session_over(ca, datetime(2026, 9, 30))
    assert session_over(ca, datetime(2026, 10, 1))
