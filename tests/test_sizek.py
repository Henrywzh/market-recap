"""SIZE K: the large arm against the equal-weight or smaller arm, on series whose answer is known."""

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import sizek as S
from market_recap.config import load_config
from market_recap.panels import sizek as P


def days(n=700, start="2020-01-02"):
    return pd.bdate_range(start, periods=n)


def test_rolling_gap_is_big_return_less_small_return_in_points_and_needs_a_full_window():
    idx = days(10)
    big = pd.Series([100, 100, 100, 110, 110, 110, 121, 121, 121, 121.0], index=idx)
    small = pd.Series(100.0, index=idx)
    gap = S.rolling_gap(big, small, 3)
    assert len(gap) == 7 and gap.index[0] == idx[3]                       # the first three sessions have no window behind them
    assert gap.iloc[0] == pytest.approx(10.0)                              # 100 -> 110 against flat
    assert S.rolling_gap(big, small, 10).empty                              # ten sessions are not a ten-session window


def test_calendar_years_use_the_prior_close_flag_a_part_year_and_the_year_to_date():
    idx = pd.bdate_range("2022-03-01", "2024-03-15")
    big = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    small = pd.Series(100.0, index=idx)
    rows = S.calendar_years(big, small)
    assert [r["year"] for r in rows] == [2022, 2023, 2024]
    assert rows[0]["partial_start"] is True and rows[1]["partial_start"] is False
    assert rows[2]["to_date"] is True and rows[1]["to_date"] is False
    assert rows[1]["small"] == pytest.approx(0.0) and rows[1]["gap"] == pytest.approx(rows[1]["big"])
    last_2022 = big[big.index.year == 2022].iloc[-1]
    assert rows[1]["big"] == pytest.approx((big[big.index.year == 2023].iloc[-1] / last_2022 - 1) * 100)


def test_ratio_extremes_and_runs():
    idx = days(6)
    ratio = pd.Series([1.0, 1.5, 2.0, 1.0, 0.5, 1.0], index=idx)
    e = S.ratio_extremes(ratio)
    assert e["high"] == 2.0 and e["high_date"] == idx[2] and e["low"] == 0.5 and e["low_date"] == idx[4]
    assert e["from_high_pct"] == pytest.approx(-50.0) and e["from_low_pct"] == pytest.approx(100.0)
    assert S.ratio_extremes(pd.Series(dtype=float)) is None
    gap = pd.Series([1, 2, 3, -1, -2, 1.0])
    assert S.share_of_windows(gap) == pytest.approx(4 / 6 * 100)
    assert S.longest_run(gap) == 3 and S.longest_run(gap, positive=False) == 2
    assert S.share_of_windows(pd.Series(dtype=float)) is None and S.longest_run(pd.Series(dtype=float)) == 0


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)


def _ctx(monkeypatch, columns):
    idx = days(900)
    rng = np.random.default_rng(5)
    closes = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))) for c in columns}, index=idx)
    cfg = {**load_config(), "sizek": {
        "history_years": 5, "price_periods": ["1M", "1Y", "10Y"], "gap_period": "1Y",
        "pairs": [{"key": "a", "label": "A", "big": "BIG", "small": "SMALL", "small_name": "The Rest", "note": "n"},
                  {"key": "b", "label": "B", "big": "BIG", "small": "GONE"}]}}
    ctx = type("C", (), {"config": cfg, "as_of": idx[-1].date().isoformat(), "log": _Log()})()
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda syms, **kw: closes.reindex(columns=[s for s in syms if s in closes.columns]))
    return ctx, idx


def test_panel_builds_a_view_per_pair_and_names_a_pair_with_a_missing_series(monkeypatch):
    ctx, idx = _ctx(monkeypatch, ["BIG", "SMALL"])
    p = P.build(ctx)
    a, b = p["views"]
    assert a["price"]["since"] == idx[0].date().isoformat() and a["price"]["dates"][0] == a["price"]["since"]
    assert a["price"]["ratio"][0] == pytest.approx(1.0)                     # rebased so the ratio starts at one
    assert a["price"]["spreads"][-1] == {"period": "10Y", "top": None, "bottom": None, "spread": None} or a["price"]["spreads"][-1]["spread"] is None
    assert a["gap"]["window"] == "1Y" and a["gap"]["first"] > a["price"]["since"]
    assert 0 <= a["gap"]["share_big_ahead"] <= 100 and a["years"] and a["years"][0]["partial_start"] in (True, False)
    assert (a["big_name"], a["small_name"]) == ("BIG", "The Rest")           # a name defaults to its symbol
    assert b["price"] is None and b["no_prices"] == ["GONE"]               # a gap with a name, never a made-up line
    assert p["inputs"]["no_prices"] == ["GONE"]
    assert ctx.log.records[0].status == "partial"
    assert len(p["notes"]) >= 2
