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


def test_read_pairs_takes_only_a_bracketed_unsigned_pe_after_the_sector_name():
    # FactSet's own wording (2026-10-02), wrapped mid-name as pdftotext leaves it.
    text = ("At the sector level, the Consumer Discretionary (22.6) and Industrials (22.5) sectors have the highest forward 12-\n"
            "month P/E ratios, while the Energy (13.0) and Financials (14.1) sectors have the lowest forward 12-month P/E ratios.\n"
            "the Consumer Discretionary (+27.6%), Utilities (+26.8%), and Industrials (+26.5%) sectors are expected to see\n"
            "the Communication Services (70%), Information Technology (70%), Energy (64%) sectors have the highest percentages\n")
    assert probe.read_pairs(text) == {"Consumer Discretionary": [22.6], "Industrials": [22.5], "Energy": [13.0], "Financials": [14.1]}


def test_fridays_start_at_the_latest_friday_and_step_back_a_week():
    days = probe.fridays(1, date(2026, 10, 4))            # a Sunday
    assert days[0] == date(2026, 10, 2) and days[1] == date(2026, 9, 25)
    assert all(d.weekday() == 4 for d in days)
    assert len(days) in (52, 53)


def test_a_sector_named_across_a_line_break_is_still_read():
    assert probe.read_pairs("the Information\nTechnology (31.4) sector") == {"Information Technology": [31.4]}


def test_a_thirty_percent_weekly_move_is_a_misread_not_a_market():
    weeks = [{"friday": "2026-09-18", "sector_pages": [{"text_pairs": {"Energy": [15.0]}}]},
             {"friday": "2026-09-25", "sector_pages": [{"text_pairs": {"Energy": [15.5]}}]},
             {"friday": "2026-10-02", "sector_pages": [{"text_pairs": {"Energy": [5.5]}}]}]
    assert probe.implausible_moves(weeks) == ["Energy 2026-09-25->2026-10-02: 15.5 -> 5.5"]
    assert probe.implausible_moves(weeks[:2]) == []


def test_sector_names_match_regardless_of_case():
    assert probe.sectors_named("ENERGY and utilities and Real estate") == ["Energy", "Real Estate", "Utilities"]
