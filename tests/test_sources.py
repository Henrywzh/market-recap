"""Parsing rules that protect the page from a malformed upstream file."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.sources import sec, ssga
from market_recap.util import clean_float, freshness_status


def test_class_shares_are_translated_for_the_price_feed():
    assert ssga.to_yahoo_symbol("BRK.B") == "BRK-B"
    assert ssga.to_yahoo_symbol("AAPL") == "AAPL"


def test_annual_values_falls_back_per_year_not_per_company():
    """A filer that switches revenue tags mid-history must keep both years."""
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2023, "start": "2023-01-01",
                     "end": "2023-12-31", "val": 100, "filed": "2024-02-01"},
                ]}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
                     "end": "2024-12-31", "val": 120, "filed": "2025-02-01"},
                ]}},
            }
        }
    }
    picked = sec._annual_values(facts, sec.LINE_ITEMS["revenue"])
    assert picked[2023]["value"] == 100
    assert picked[2024]["value"] == 120


def test_quarterly_durations_are_rejected():
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-10-01",
                     "end": "2024-12-31", "val": 30, "filed": "2025-02-01"},
                ]}}
            }
        }
    }
    assert sec._annual_values(facts, ("Revenues",)) == {}


def test_a_restatement_wins_over_the_original_filing():
    rows = [
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
         "end": "2024-12-31", "val": 100, "filed": "2025-02-01"},
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
         "end": "2024-12-31", "val": 97, "filed": "2026-02-01"},
    ]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    picked = sec._annual_values(facts, ("Revenues",))
    assert picked[2024]["value"] == 97
    assert picked[2024]["filed"] == "2026-02-01"


def test_clean_float_treats_non_finite_as_absent():
    assert clean_float(float("nan")) is None
    assert clean_float(float("inf")) is None
    assert clean_float("nope") is None
    assert clean_float(1.23456, 2) == 1.23


def test_missing_observation_date_is_unknown_not_current():
    assert freshness_status(None, "daily_close") == "unknown"
    assert freshness_status(pd.Timestamp.today(), "daily_close") == "current"
