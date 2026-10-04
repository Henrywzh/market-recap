"""The FactSet sector probe reads numbers beside sector names and judges weeks.

It is research tooling, but its verdict decides whether a sector reader gets
written, so the parts that decide it are checked: which numbers count, which
Friday is asked for, and what a misread looks like.
"""

from __future__ import annotations

from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import probe_factset_sector as probe


def test_read_pairs_takes_decimals_after_the_sector_name_only():
    text = ("Forward 12-Month P/E Ratio, 2026 (page 14)\n"
            "Information Technology   27.4   24.9   21.0\n"
            "Real Estate              35.1   36.2\n"
            "Energy and nothing else\n")
    pairs = probe.read_pairs(text)
    assert pairs == {"Information Technology": [27.4, 24.9, 21.0], "Real Estate": [35.1, 36.2]}
    assert "Energy" not in pairs                          # a name with no number is not a reading


def test_fridays_start_at_the_latest_friday_and_step_back_a_week():
    days = probe.fridays(1, date(2026, 10, 4))            # a Sunday
    assert days[0] == date(2026, 10, 2) and days[1] == date(2026, 9, 25)
    assert all(d.weekday() == 4 for d in days)
    assert len(days) in (52, 53)


def test_a_thirty_percent_weekly_move_is_a_misread_not_a_market():
    weeks = [{"friday": "2026-09-18", "sector_pages": [{"text_pairs": {"Energy": [15.0]}}]},
             {"friday": "2026-09-25", "sector_pages": [{"text_pairs": {"Energy": [15.5]}}]},
             {"friday": "2026-10-02", "sector_pages": [{"text_pairs": {"Energy": [5.5]}}]}]
    assert probe.implausible_moves(weeks) == ["Energy 2026-09-25->2026-10-02: 15.5 -> 5.5"]
    assert probe.implausible_moves(weeks[:2]) == []


def test_sector_names_match_regardless_of_case():
    assert probe.sectors_named("ENERGY and utilities and Real estate") == ["Energy", "Real Estate", "Utilities"]
