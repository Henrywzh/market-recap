"""SIZE K: the large arm against the equal-weight or smaller arm, on series whose answer is known."""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import sizek as S
from market_recap.config import load_config
from market_recap.panels import sizek as P
from market_recap.sources import french
from market_recap.sources.http import FetchError


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


def test_a_pair_names_its_arms_and_one_without_names_defaults_to_large_and_small(monkeypatch):
    ctx, _ = _ctx(monkeypatch, ["BIG", "SMALL"])
    ctx.config["sizek"]["pairs"] = [
        {"key": "v", "label": "V", "big": "BIG", "small": "SMALL", "big_arm": "VALUE", "small_arm": "GROWTH"},
        {"key": "s", "label": "S", "big": "BIG", "small": "SMALL"}]
    styled, sized = P.build(ctx)["views"]
    assert (styled["big_arm"], styled["small_arm"]) == ("VALUE", "GROWTH")
    assert (sized["big_arm"], sized["small_arm"]) == ("LARGE", "SMALL")


# --- Kenneth French's daily portfolios -------------------------------------

FRENCH_CSV = "\r\n".join([
    "This file was created by using the 202608 CRSP database.",
    "Missing data are indicated by -99.99 or -999.",
    "",
    "  Average Value Weighted Returns -- Daily",
    ",SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM",
    "19260701,   0.10,  -0.09,  -0.37,   0.16,   0.11,   0.07",
    "19260702,   0.14,  -0.19,  -99.99,   0.52,   0.47,   0.30",
    "",
    "",
    "  Average Equal Weighted Returns -- Daily",
    ",SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM",
    "19260701,   9.99,   9.99,   9.99,   9.99,   9.99,   9.99",
    "",
    "Copyright 2026 Eugene F. Fama and Kenneth R. French",
    "",
])


def test_the_french_parser_reads_only_the_value_weighted_section_as_decimals_with_missing_as_nan():
    frame = french.parse_value_weighted_daily(FRENCH_CSV)
    assert list(frame.columns) == list(french.PORTFOLIOS) and len(frame) == 2   # the equal-weighted rows are not read
    assert frame.index[0] == pd.Timestamp("1926-07-01") and frame.index.is_monotonic_increasing
    assert frame.loc["1926-07-01", "BIG HiBM"] == pytest.approx(0.0007)           # 0.07 percent, as a decimal
    assert frame.loc["1926-07-01", "SMALL LoBM"] == pytest.approx(0.0010)
    assert pd.isna(frame.loc["1926-07-02", "SMALL HiBM"])                          # the file's own -99.99 marker


def test_the_french_parser_refuses_a_file_without_the_section_or_with_a_portfolio_missing():
    with pytest.raises(ValueError, match="Value Weighted"):
        french.parse_value_weighted_daily(FRENCH_CSV.replace("Value Weighted", "Equal Weighted"))
    with pytest.raises(ValueError, match="lacks BIG HiBM"):
        french.parse_value_weighted_daily(FRENCH_CSV.replace(",BIG HiBM", ",BIG XXX"))


def test_the_french_fetch_reads_the_one_csv_inside_the_zip(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("6_Portfolios_2x3_Daily.csv", FRENCH_CSV)
    monkeypatch.setattr(french.cache, "fetch_bytes", lambda *a, **k: buffer.getvalue())
    assert len(french.fetch_value_weighted_daily()) == 2


def _french_frame(daily: dict[str, float], index) -> pd.DataFrame:
    """Six portfolios with a constant daily return each (zero unless named)."""
    return pd.DataFrame({c: np.full(len(index), daily.get(c, 0.0)) for c in french.PORTFOLIOS}, index=index)


def _french_ctx(monkeypatch, fetch):
    ctx, _ = _ctx(monkeypatch, ["BIG", "SMALL"])
    ctx.config["sizek"]["pairs"] = [
        {"key": "a", "label": "A", "big": "BIG", "small": "SMALL"},
        {"key": "ff", "label": "FF", "big": "FF_VALUE", "small": "FF_GROWTH", "big_arm": "VALUE", "small_arm": "GROWTH",
         "small_name": "FF growth", "source": "french"},
        {"key": "ffb", "label": "FFB", "big": "FF_BIG_VALUE", "small": "FF_BIG_GROWTH", "source": "french"},
    ]
    monkeypatch.setattr(P.french, "fetch_value_weighted_daily", fetch)
    return ctx


def test_a_french_pair_is_the_ratio_of_its_equal_mixed_legs_compounded_from_one(monkeypatch):
    idx = days(900)
    returns = _french_frame({"SMALL HiBM": 0.001, "BIG HiBM": 0.001}, idx)     # value legs +0.1% a day, growth legs flat
    ctx = _french_ctx(monkeypatch, lambda *a, **k: returns)
    ff, ffb = P.build(ctx)["views"][1:]
    assert ff["no_prices"] == [] and ffb["no_prices"] == []
    assert ff["price"]["since"] == idx[0].date().isoformat() and ff["price"]["through"] == idx[-1].date().isoformat()
    assert ff["price"]["ratio"][0] == pytest.approx(1.0)
    assert ff["price"]["ratio_now"] == pytest.approx(1.001 ** 899, abs=1e-3)   # ratio after 899 days of 0.1% over flat
    assert ffb["price"]["ratio_now"] == pytest.approx(1.001 ** 899, abs=1e-3)  # the large-only pair has the same legs here
    assert ff["big_arm"] == "VALUE" and ff["small_name"] == "FF growth"
    record = [r for r in ctx.log.records if r.source_id == "french_portfolios"][0]
    assert record.status == "ok" and record.policy == "monthly_release" and record.observed_date == idx[-1].date().isoformat()


def test_a_french_pair_is_cut_to_the_same_window_as_the_yahoo_pairs(monkeypatch):
    ctx = _french_ctx(monkeypatch, lambda *a, **k: _french_frame({"SMALL HiBM": 0.001}, pd.bdate_range("1990-01-01", "2023-08-31")))
    ff = P.build(ctx)["views"][1]
    as_of = pd.Timestamp(ctx.as_of)
    assert pd.Timestamp(ff["price"]["since"]) >= as_of - pd.DateOffset(years=5)   # history_years is 5 in this config
    assert pd.Timestamp(ff["price"]["since"]) <= as_of - pd.DateOffset(years=5) + pd.Timedelta(days=5)


def test_a_failing_french_fetch_leaves_its_pairs_without_prices_and_the_yahoo_pair_still_builds(monkeypatch):
    def down(*a, **k):
        raise FetchError("mba.tuck.dartmouth.edu: timed out")

    ctx = _french_ctx(monkeypatch, down)
    a, ff, ffb = P.build(ctx)["views"]
    assert a["price"] is not None and a["no_prices"] == []
    assert ff["price"] is None and ff["no_prices"] == ["FF_VALUE", "FF_GROWTH"]
    assert ffb["price"] is None and ffb["no_prices"] == ["FF_BIG_VALUE", "FF_BIG_GROWTH"]
    record = [r for r in ctx.log.records if r.source_id == "french_portfolios"][0]
    assert record.status == "error" and "timed out" in record.error and record.observed_date is None
    assert [r for r in ctx.log.records if r.source_id == "sizek_prices"][0].status == "ok"   # Yahoo's own record is untouched


def test_a_french_leg_with_a_missing_day_is_refused_rather_than_averaged_away(monkeypatch):
    idx = days(900)
    returns = _french_frame({}, idx)
    returns.iloc[10, returns.columns.get_loc("SMALL HiBM")] = np.nan
    ctx = _french_ctx(monkeypatch, lambda *a, **k: returns)
    ff = P.build(ctx)["views"][1]
    assert ff["price"] is None
    record = [r for r in ctx.log.records if r.source_id == "french_portfolios"][0]
    assert record.status == "error" and "missing daily returns" in record.error
