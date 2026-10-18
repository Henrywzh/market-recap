"""CREDIT: the distance to default from filed debt and the close (compute.credit)."""
import math

import pandas as pd
import pytest

from market_recap.compute import credit as C

DAYS = pd.bdate_range("2025-01-01", "2026-06-30")


def test_a_filed_value_counts_from_its_filing_date_and_goes_stale():
    rows = (("2024-12-31", "2025-02-20", 100.0), ("2025-03-31", "2025-05-01", 120.0))
    s = C.as_of(rows, DAYS, stale_days=450)
    assert pd.isna(s[pd.Timestamp("2025-02-19")]), "not public before its filing"
    assert s[pd.Timestamp("2025-02-20")] == 100.0
    assert s[pd.Timestamp("2025-05-01")] == 120.0
    # The last period ended 2025-03-31: 450 days later the line is treated as dropped.
    assert pd.isna(s[pd.Timestamp("2026-06-29")])


def test_a_later_filing_restating_an_older_period_does_not_replace_a_newer_one():
    rows = (("2025-03-31", "2025-05-01", 120.0), ("2024-12-31", "2025-06-01", 999.0))
    s = C.as_of(rows, DAYS, stale_days=450)
    assert s[pd.Timestamp("2025-06-02")] == 120.0


def test_the_filer_total_of_current_debt_is_not_added_to_its_parts():
    kept = {"DebtCurrent": (("2025-03-31", "2025-05-01", 50.0),),
            "LongTermDebtCurrent": (("2025-03-31", "2025-05-01", 30.0),),
            "CommercialPaper": (("2025-03-31", "2025-05-01", 20.0),),
            "LongTermDebtNoncurrent": (("2025-03-31", "2025-05-01", 400.0),)}
    short, long_ = C.debt_parts(kept, DAYS, 450)
    day = pd.Timestamp("2025-05-02")
    assert short[day] == 50.0 and long_[day] == 400.0
    assert C.default_point(kept, DAYS, 450)[day] == 50.0 + 0.5 * 400.0


def test_debt_filed_with_leases_or_by_instrument_is_counted():
    with_leases = {"LongTermDebtAndCapitalLeaseObligations": (("2025-03-31", "2025-05-01", 67.0),),
                   "LongTermDebtAndCapitalLeaseObligationsCurrent": (("2025-03-31", "2025-05-01", 5.7),)}
    day = pd.Timestamp("2025-05-02")
    short, long_ = C.debt_parts(with_leases, DAYS, 450)
    assert (short[day], long_[day]) == (5.7, 67.0)
    reit = {"SeniorNotes": (("2025-03-31", "2025-05-01", 10.0),), "SecuredDebt": (("2025-03-31", "2025-05-01", 4.0),)}
    assert C.debt_parts(reit, DAYS, 450)[1][day] == 14.0


def test_only_a_total_long_term_figure_counts_less_its_current_part():
    kept = {"LongTermDebt": (("2025-03-31", "2025-05-01", 100.0),),
            "LongTermDebtCurrent": (("2025-03-31", "2025-05-01", 10.0),)}
    short, long_ = C.debt_parts(kept, DAYS, 450)
    day = pd.Timestamp("2025-05-02")
    assert (short[day], long_[day]) == (10.0, 90.0)


def test_shares_come_from_the_freshest_source_and_are_scaled_by_later_splits():
    kept = {"CommonStockSharesOutstanding": (("2017-03-31", "2017-06-06", 0.0), ("2016-12-31", "2017-02-01", 5.0)),
            "WeightedAverageNumberOfDilutedSharesOutstanding": (("2025-03-31", "2025-05-01", 100.0),)}
    split_after = lambda filed: 10.0 if filed < "2025-06-01" else 1.0  # noqa: E731 - a 10:1 split on 2025-06-01
    s = C.shares(kept, DAYS, 450, split_after)
    assert s[pd.Timestamp("2025-05-02")] == 1000.0, "a pre-split count on today's basis"


def test_a_cover_page_lists_share_classes_once_each_and_they_are_summed():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-04-20", "filed": "2025-05-01", "val": 600, "accn": "a", "frame": "x"},
        {"end": "2025-04-20", "filed": "2025-05-01", "val": 400, "accn": "a", "frame": "y"},
        {"end": "2025-04-20", "filed": "2025-05-01", "val": 400, "accn": "a", "frame": "y"},  # listed twice
    ]}}}}}
    kept = C.filed_facts(facts)
    assert kept["EntityCommonStockSharesOutstanding"] == (("2025-04-20", "2025-05-01", 1000.0),)


def test_naive_distance_and_probability():
    # E 100, F 50, sE 40%, r 4%: sD 0.15, V 150, sV = 2/3*0.4 + 1/3*0.15
    sV = 2 / 3 * 0.4 + 1 / 3 * 0.15
    expected = (math.log(3) + 0.04 - 0.5 * sV ** 2) / sV
    assert C.naive_dd(100.0, 50.0, 0.4, 0.04) == pytest.approx(expected)
    assert float(C.default_probability(0.0)) == pytest.approx(0.5)
    assert float(C.default_probability(2.0)) == pytest.approx(0.02275, abs=1e-5)


def test_the_series_is_scaled_to_valuations_market_cap_and_placed_in_its_own_history():
    prices = pd.Series(10.0, index=DAYS) * (1 + 0.01 * (pd.Series(range(len(DAYS)), index=DAYS) % 5))
    kept = {"WeightedAverageNumberOfDilutedSharesOutstanding": (("2024-12-31", "2024-12-31", 50.0),),
            "LongTermDebtNoncurrent": (("2024-12-31", "2024-12-31", 400.0),)}
    rate = pd.Series(0.04, index=DAYS)
    frame = C.distance_series(prices, kept, rate, split_after=lambda d: 1.0, stale_days=900,
                              vol_sessions=60, market_cap_now=2000.0)
    assert frame["E"].iloc[-1] == pytest.approx(2000.0), "every share class, as VALUATION counts it"
    assert frame["F"].iloc[-1] == 200.0
    pct = C.own_percentile(frame["dd"], frame["dd"].iloc[-1])
    assert 0 <= pct <= 100
    assert C.own_percentile(frame["dd"].iloc[:10], 1.0) is None, "too little history to place"


def test_the_path_before_a_tenfold_jump_in_counted_debt_is_left_out():
    prices = pd.Series(10.0, index=DAYS) * (1 + 0.01 * (pd.Series(range(len(DAYS)), index=DAYS) % 5))
    kept = {"WeightedAverageNumberOfDilutedSharesOutstanding": (("2024-12-31", "2024-12-31", 50.0),),
            "LongTermDebtNoncurrent": (("2024-12-31", "2024-12-31", 2.0), ("2026-03-31", "2026-04-30", 400.0))}
    frame = C.distance_series(prices, kept, pd.Series(0.04, index=DAYS), split_after=lambda d: 1.0,
                              stale_days=900, vol_sessions=60)
    assert frame.index[0] == pd.Timestamp("2026-04-30"), "the debt before the first full filing was not read"


def test_debt_the_note_counts_beyond_the_lines_read_is_added_as_long_term():
    kept = {"LongTermDebtNoncurrent": (("2026-03-31", "2026-05-08", 17.0),),
            "LongTermDebtCurrent": (("2026-03-31", "2026-05-08", 7.5),),
            "DebtInstrumentCarryingAmount": (("2026-06-30", "2026-06-15", 35.5),)}
    short, long_ = C.debt_parts(kept, DAYS, 450)
    day = pd.Timestamp("2026-06-29")
    assert short[day] == 7.5 and long_[day] == pytest.approx(28.0)
