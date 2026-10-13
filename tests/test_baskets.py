import pandas as pd
import pytest

from market_recap.compute import baskets as B
from market_recap.compute import series as S


def _history(dates, closes, yields):
    return {"dates": dates, "close": closes, "ey": yields}


DATES = ["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"]


def test_frames_skip_artifacts_without_the_new_fields():
    closes, yields = B.frames({"A": _history(DATES, [10, 11, 12, 13], [5, 5, 5, 5]), "B": {"dates": DATES, "pe": [1, 2, 3, 4]}})
    assert list(closes.columns) == ["A"]
    assert yields["A"].tolist() == [5, 5, 5, 5]


def test_cap_basket_totals_value_over_earnings_and_splits_exactly():
    closes, yields = B.frames({
        "A": _history(DATES, [10, 11, 12, 12], [5, 5, 4, 4]),
        "B": _history(DATES, [20, 20, 20, 22], [10, 10, 10, -2]),
    })
    out = B.basket(closes, yields, {"A": 300, "B": 100}, min_coverage=0.5)
    # Today's values 300 and 100: A holds 25 shares, B 100/22.
    value_a = 25 * 10
    value_b = 100 / 22 * 20
    expected_pe = (value_a + value_b) / (value_a * 0.05 + value_b * 0.10)
    assert out["pe"].iloc[0] == pytest.approx(expected_pe)
    assert out["price"].iloc[0] == 100
    assert (out["price"] / out["pe"] / (out["price"].iloc[0] / out["pe"].iloc[0]) * 100).tolist() == pytest.approx(out["earnings"].tolist())
    # A loss counts: the last week's earnings include B's negative yield.
    last_a, last_b = 25 * 12, 100.0
    assert out["pe"].iloc[-1] == pytest.approx((last_a + last_b) / (last_a * 0.04 + last_b * -0.02))


def test_equal_basket_is_count_over_summed_yields():
    closes, yields = B.frames({"A": _history(DATES, [10, 11, 12, 13], [5, 5, 5, 5]), "B": _history(DATES, [10, 10, 10, 10], [10, 10, 10, 10])})
    out = B.basket(closes, yields, None)
    assert out["pe"].iloc[0] == pytest.approx(2 / 0.15)
    assert out["price"].iloc[1] == pytest.approx(105)


def test_too_little_coverage_or_negative_total_leaves_the_week_blank():
    closes, yields = B.frames({"A": _history(DATES, [10, 10, 10, 10], [None, None, 5, -50]), "B": _history(DATES, [10, 10, 10, 10], [5, 5, 5, 5])})
    out = B.basket(closes, yields, {"A": 1, "B": 1}, min_coverage=0.8)
    assert out["pe"].isna().tolist() == [True, True, False, True]
    assert out["earnings"].iloc[2] == 100


def test_stats_and_payload():
    pe = pd.Series(range(1, 201), index=pd.date_range("2020-01-03", periods=200, freq="W-FRI"), dtype=float)
    st = B.stats(pe)
    assert st["percentile"] == 100 and st["median"] == pytest.approx(100.5)
    assert B.stats(pe.iloc[:50]) is None
    frame = pd.DataFrame({"price": 100.0, "pe": pe, "earnings": 100.0, "coverage": 1.0, "names": 3}, index=pe.index)
    body = B.payload(frame, years=1)
    assert len(body["dates"]) <= 53 and body["names"] == 3 and body["stats"] is None


def test_thin_keeps_recent_days_and_older_weeks():
    days = pd.bdate_range("2023-01-02", "2026-01-02")
    frame = pd.DataFrame({"v": range(len(days))}, index=days, dtype=float)
    out = S.thin(frame)
    recent = out[out.index > days[-1] - pd.Timedelta(days=365)]
    assert len(recent) > 240 and out.index[0] == days[0]
    assert len(out) < 262 + 110
