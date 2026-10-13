"""SECTORS pages: the relative line against the S&P 500, the ten-year P/E band, the aggregate multiples, and the page files."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import validate
from market_recap.compute import sectors as S
from market_recap.config import load_config
from market_recap.panels import sectors as panel
from market_recap.util import BuildLog

WEEKS = pd.date_range(end="2026-10-09", periods=120, freq="W-FRI")
CONFIG = {
    "universe": {"sectors": {"Consumer Staples": "XLP", "Energy": "XLE"}},
    "industries": {"thin_below": 99, "no_pe_sectors": ["Real Estate"]},
    "sectors": {"valuation_min_members": 2},
}


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "SECTORS_ARTIFACT_DIR", tmp_path / "sectors")
    monkeypatch.setattr(panel, "VALUATION_ARTIFACT_DIR", tmp_path / "valuation")
    (tmp_path / "valuation").mkdir()
    return tmp_path


def _index(names_prices: dict[str, list[float]], weights: dict[str, float]):
    days = pd.bdate_range("2026-01-05", periods=len(next(iter(names_prices.values()))))
    closes = pd.DataFrame(names_prices, index=days, dtype=float)
    return closes, S.index_basket(closes, weights)


# --- the whole index and a page's line against it ----------------------------

def test_a_page_line_is_its_basket_over_the_index_on_the_index_sessions():
    # Today's weights 60/40 held as units: the index ends at 100/94.44 of where it began (buy and hold).
    closes, index = _index({"A": [10, 11, 12], "B": [20, 20, 18]}, {"A": 60.0, "B": 40.0})
    assert index["level"].iloc[-1] == pytest.approx(100 / 94.4444444444)
    ratio_a = S.page_ratio(index, ["A"])
    # A alone rose 10% then 9.1%: 1.2. The index rose to 100/94.44 = 1.0588. Ratio 1.2 / 1.0588.
    assert ratio_a.iloc[-1] == pytest.approx(1.2 / (100 / 94.4444444444), rel=1e-6)
    ratio_b = S.page_ratio(index, ["B"])
    assert ratio_b.iloc[-1] == pytest.approx(0.9 / (100 / 94.4444444444), rel=1e-6)


def test_a_member_with_no_price_is_left_out_and_none_when_no_member_has_one():
    closes, index = _index({"A": [10, 11, 12], "B": [20, 20, 18]}, {"A": 60.0, "B": 40.0, "Z": 5.0})
    assert "Z" not in index["sessions"].columns                  # weighted but not priced: not in the index either
    assert S.page_ratio(index, ["A", "Q"]).iloc[-1] == pytest.approx(S.page_ratio(index, ["A"]).iloc[-1])
    assert S.page_ratio(index, ["Q"]) is None
    assert S.index_basket(closes, {"Q": 1.0}) is None and S.index_basket(closes, {}) is None


def test_the_relative_payload_is_the_last_ten_years_each_line_x100_at_its_first_value():
    dates = pd.date_range("2015-01-02", "2026-10-09", freq="W-FRI")
    values = np.arange(1, len(dates) + 1, dtype=float)
    frame = pd.DataFrame({"basket": values, "fund": values * 2}, index=dates)
    body = S.relative_payload(frame)
    cut = dates[dates > dates[-1] - pd.DateOffset(years=10)]
    first = values[dates.get_loc(cut[0])]
    assert body["dates"][0] == cut[0].strftime("%Y-%m-%d")
    assert body["basket"][0] == pytest.approx(100.0)
    assert body["basket"][-1] == pytest.approx(round(100 * values[-1] / first, 2))
    assert body["fund"][0] == pytest.approx(100.0)                # a line of the same ratio starts at 100 too


def test_a_fund_line_that_starts_later_is_rebased_where_it_starts_and_is_null_before():
    dates = pd.bdate_range("2026-01-05", periods=5)
    frame = pd.DataFrame({"basket": [1.0, 1.0, 1.0, 1.0, 1.0],
                          "fund": [np.nan, np.nan, 2.0, 4.0, 6.0]}, index=dates)
    body = S.relative_payload(frame)
    assert body["fund"][:2] == [None, None]
    assert body["fund"][2:] == [100.0, 200.0, 300.0]
    assert body["basket"] == [100.0] * 5


def test_fund_ratio_is_none_without_both_closes():
    etf = pd.DataFrame({"XLP": [1.0, 2.0], "SPY": [2.0, 2.0]})
    assert S.fund_ratio(etf, "XLP", "SPY").tolist() == [0.5, 1.0]
    assert S.fund_ratio(etf, "XLE", "SPY") is None and S.fund_ratio(etf, None, "SPY") is None
    assert S.fund_ratio(pd.DataFrame(), "XLP", "SPY") is None


# --- the ten-year P/E band --------------------------------------------------

def _write_history(directory: Path, ticker: str, price: float, earnings_yield: float, weeks=WEEKS) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    body = {"dates": [d.strftime("%Y-%m-%d") for d in weeks], "close": [price] * len(weeks),
            "ey": [earnings_yield] * len(weeks)}
    (directory / f"{ticker}.json").write_text(json.dumps(body))


def _histories(directory: Path, names: dict[str, tuple[float, float]]) -> dict:
    for ticker, (price, ey) in names.items():
        _write_history(directory, ticker, price, ey)
    return {ticker: json.loads((directory / f"{ticker}.json").read_text()) for ticker in names}


def test_the_band_is_the_weighted_pe_when_enough_names_have_a_history(tmp_path):
    histories = _histories(tmp_path / "v", {"KO": (100.0, 4.0), "PEP": (100.0, 5.0), "PM": (100.0, 2.0)})
    band, usable = S.valuation_band(histories, {"KO": 4.0, "PEP": 2.0, "PM": 1.0}, min_names=2)
    assert usable == 3
    # Today's weights are the values: P/E = 7 / (4 x 4% + 2 x 5% + 1 x 2%) = 25.
    assert band["pe"][-1] == pytest.approx(25.0)
    assert band["stats"]["current"] == pytest.approx(25.0) and band["stats"]["median"] == pytest.approx(25.0)
    assert band["names"] == 3


def test_a_band_needs_the_minimum_usable_names_and_names_without_a_weight_do_not_count(tmp_path):
    histories = _histories(tmp_path / "v", {"KO": (100.0, 4.0), "PEP": (100.0, 5.0)})
    assert S.valuation_band(histories, {"KO": 4.0, "PEP": 2.0}, min_names=3) == (None, 2)
    assert S.valuation_band(histories, {"KO": 4.0}, min_names=2) == (None, 1)   # PEP has no weight here
    assert S.valuation_band({"KO": None}, {"KO": 4.0}, min_names=1) == (None, 0)


def test_no_week_with_positive_earnings_means_no_band(tmp_path):
    histories = _histories(tmp_path / "v", {"KO": (100.0, -4.0), "PEP": (100.0, -5.0)})
    assert S.valuation_band(histories, {"KO": 4.0, "PEP": 2.0}, min_names=2) == (None, 2)


# --- the aggregate forward P/E ----------------------------------------------

def _member(ticker, cap, eps, price=100.0):
    return {"ticker": ticker, "market_cap": cap, "price": price, "eps_ntm": eps}


def test_the_aggregate_forward_pe_is_total_cap_over_total_earnings():
    members = [_member("KO", 4000.0, 4.0), _member("PEP", 2000.0, 5.0), _member("PM", 1000.0, 2.0)]
    # 7000 over (40 x 4 + 20 x 5 + 10 x 2) = 280.
    assert S.forward_pe(members, min_names=2) == 25.0


def test_the_forward_pe_is_blank_below_the_coverage_the_minimum_or_with_a_loss():
    no_estimate = [_member("KO", 4000.0, 4.0), _member("PEP", 2000.0, None), _member("PM", 1000.0, 2.0)]
    # Names with an estimate hold 5/7 of the cap, short of the 80% that AGGREGATE_MIN_COVERAGE asks for.
    assert S.forward_pe(no_estimate, min_names=2) is None
    assert S.forward_pe([_member("KO", 4000.0, 4.0), _member("PEP", 2000.0, 5.0)], min_names=3) is None
    assert S.forward_pe([_member("KO", 4000.0, -4.0), _member("PEP", 2000.0, -5.0)], min_names=2) is None


# --- the page files, from one build with fake inputs ------------------------

def _heatmaps():
    # Index weights 4, 2, 1 (staples, one a tobacco name) and 6, 3 (energy): energy is the heavier sector.
    rows = [("KO", "Consumer Staples", "Soft Drinks & Non-alcoholic Beverages", 4.0),
            ("PEP", "Consumer Staples", "Soft Drinks & Non-alcoholic Beverages", 2.0),
            ("PM", "Consumer Staples", "Tobacco", 1.0),
            ("XOM", "Energy", "Oil & Gas Exploration & Production", 6.0),
            ("CVX", "Energy", "Oil & Gas Exploration & Production", 3.0)]
    return {"periods": ["1M", "3M"],
            "constituents": [{"ticker": t, "name": f"{t} Co", "sector": s, "sub_sector": sub, "weight": w,
                              "price": 100.0, "returns": {"1M": 1.0, "3M": 2.0}} for t, s, sub, w in rows],
            "etfs": [{"ticker": "SPY", "returns": {"1M": 1.0, "3M": 3.0}},
                     {"ticker": "XLP", "returns": {"1M": 0.5, "3M": 1.0}}]}


def _valuation_rows():
    # Per-share EPS at four stages, price 100, so each name's earnings = eps x cap / 100.
    table = [("KO", 4000.0, 3.6, 3.8, 4.0, 4.4), ("PEP", 2000.0, 4.5, 4.8, 5.0, 5.5),
             ("PM", 1000.0, 1.8, 1.9, 2.0, 2.2), ("XOM", 3000.0, 9.0, 9.5, 10.0, 11.0)]
    return {"rows": [{"ticker": t, "market_cap": cap, "price": 100.0, "eps_fy_prev": prev, "eps_fy0": fy0,
                      "eps_ntm": ntm, "eps_fy1": fy1} for t, cap, prev, fy0, ntm, fy1 in table],
            "aggregates": {"series": []}}


def _ctx(config, closes, etf_closes):
    return SimpleNamespace(config=config, as_of="2026-10-12", log=BuildLog(), closes=closes, etf_closes=etf_closes)


def _read(directory: Path, key: str) -> dict:
    return json.loads((directory / f"{key}.json").read_text())


def _prices():
    days = pd.bdate_range("2016-10-10", "2026-10-09")
    closes = pd.DataFrame({t: 100.0 for t in ["KO", "PEP", "PM", "CVX"]}, index=days)
    closes["XOM"] = np.linspace(100.0, 150.0, len(days))          # the only name that moves
    etf = pd.DataFrame({"SPY": np.linspace(100.0, 200.0, len(days)),
                        "XLP": [np.nan] * 100 + [100.0] * (len(days) - 100)}, index=days)   # XLP priced from day 101
    return closes, etf


def test_one_build_writes_a_file_per_page_and_the_hub_reads_the_same_figures(_isolated_artifacts):
    pages = _isolated_artifacts / "sectors"
    pages.mkdir()
    (pages / "OLD.json").write_text("{}")                          # a page no longer built: removed
    histories = _isolated_artifacts / "valuation"
    _histories(histories, {"KO": (100.0, 4.0), "PEP": (100.0, 5.0), "PM": (100.0, 2.0),
                           "XOM": (100.0, 10.0), "CVX": (100.0, 8.0)})
    closes, etf = _prices()
    config = {**CONFIG, "sectors": {"valuation_min_members": 2}}
    out = panel.build(_ctx(config, closes, etf), {"heatmaps": _heatmaps(), "valuation": _valuation_rows(),
                                                  "industries": None, "rotation": None, "monitor": None, "themes": None})

    assert sorted(p.name for p in pages.glob("*.json")) == sorted(
        ["MARKET.json", "XLP.json", "XLP-SDNB.json", "XLP-T.json", "XLE.json", "XLE-OGEP.json"])
    assert findings_of_errors(out) == []

    market = _read(pages, "MARKET")
    assert "relative" not in market and market["level"] == "market" and market["key"] == "MARKET"
    # Market caps 4000/2000/1000/3000 (CVX has none, so it is out) over earnings
    # 160+100+20+300 at yields 4/5/2/10%: 10000 / 580.
    assert market["valuation"]["stats"]["current"] == pytest.approx(17.24, abs=0.01)

    staples = _read(pages, "XLP")
    assert list(staples["relative"]) == ["dates", "basket", "fund"]
    assert staples["relative"]["basket"][0] == pytest.approx(100.0)
    # The staples basket is flat and the S&P 500 fell to 14/16 as XOM rose to 150: the line ends at 100 x 14/16.
    assert staples["relative"]["basket"][-1] == pytest.approx(87.5, abs=0.01)
    # The fund line starts where XLP starts (day 101), rebased there; the thinned page keeps that week's last
    # session, so the first point shown is the Friday after it: 100 x SPY(day 101) / SPY(that Friday).
    fund = staples["relative"]["fund"]
    first = next(i for i, v in enumerate(fund) if v is not None)
    friday = pd.Timestamp(staples["relative"]["dates"][first])
    spy = etf["SPY"]
    assert fund[first] == pytest.approx(100 * spy.iloc[100] / spy.loc[friday], abs=0.01)
    assert fund[first] < 100 and all(v is None for v in fund[:first])
    # Flat at 25: 7 / (4 x 4% + 2 x 5% + 1 x 2%).
    assert staples["valuation"]["stats"]["current"] == pytest.approx(25.0, abs=0.01)
    assert staples["valuation"]["stats"]["percentile"] == pytest.approx(100.0)

    soft = _read(pages, "XLP-SDNB")
    assert list(soft["relative"]) == ["dates", "basket"]          # a sub-industry has no fund line
    assert soft["valuation"]["stats"]["current"] == pytest.approx(23.08, abs=0.01)

    tobacco = _read(pages, "XLP-T")
    assert tobacco["valuation"] is None
    assert any("needed for a band" in note for note in tobacco["notes"])

    energy = _read(pages, "XLE")
    assert energy["relative"]["fund"] == [None] * len(energy["relative"]["dates"])
    assert any("XLE or SPY has no price history" in note for note in energy["notes"])
    # The P/E is weighted by VALUATION's market caps, and CVX has no row: one name is too few.
    assert energy["valuation"] is None

    sectors = {s["label"]: s for s in out["sectors"]}
    xlp = sectors["Consumer Staples"]
    # Aggregate NTM: 7000 cap over 40 x 4 + 20 x 5 + 10 x 2 = 280.
    assert xlp["forward_pe"] == 25.0
    assert xlp["trailing_pe"] == pytest.approx(25.0, abs=0.01) and xlp["pe_percentile"] == pytest.approx(100.0)
    assert xlp["pe_median_10y"] == pytest.approx(25.0, abs=0.01)
    stages = {st["key"]: st for st in xlp["path"]["stages"]}
    assert list(stages) == ["fy_prev", "fy0", "ntm", "fy1"]
    # Per stage: 7000 over 252, 267, 280 and 308.
    assert stages["fy_prev"]["pe"] == pytest.approx(27.78, abs=0.01)
    assert stages["ntm"]["pe"] == pytest.approx(25.0)
    assert stages["fy1"]["growth"] == pytest.approx(10.0, abs=0.01)
    # Energy has one valued name (CVX has no row) against a minimum of two: no forward figure, no path.
    assert sectors["Energy"]["forward_pe"] is None and sectors["Energy"]["path"] is None
    assert sectors["Energy"]["trailing_pe"] is None
    subs = {s["label"]: s for s in out["sub_industries"]}
    assert subs["Soft Drinks & Non-alcoholic Beverages"]["forward_pe"] == pytest.approx(23.1, abs=0.05)
    assert subs["Tobacco"]["forward_pe"] is None and subs["Tobacco"]["trailing_pe"] is None


def findings_of_errors(out) -> list:
    return [f for f in validate._check_sectors(out) if f.severity == "error"]


def test_real_estate_has_no_band_and_no_aggregate_multiple_and_the_page_says_why(_isolated_artifacts):
    histories = _isolated_artifacts / "valuation"
    _histories(histories, {"O": (60.0, 4.0)})
    heatmaps = {"periods": ["1M"], "etfs": [], "constituents": [
        {"ticker": "O", "name": "Realty Co", "sector": "Real Estate", "sub_sector": "Retail REITs", "weight": 1.0,
         "price": 60.0, "returns": {"1M": 1.0}}]}
    valuation = {"rows": [{"ticker": "O", "market_cap": 6000.0, "price": 60.0, "eps_ntm": 3.0,
                           "eps_fy_prev": 2.8, "eps_fy0": 2.9, "eps_fy1": 3.2}], "aggregates": {"series": []}}
    config = {"universe": {"sectors": {"Real Estate": "XLRE"}},
              "industries": {"thin_below": 1, "no_pe_sectors": ["Real Estate"]},
              "sectors": {"valuation_min_members": 1}}
    days = pd.bdate_range("2026-01-05", periods=5)
    closes = pd.DataFrame({"O": [60.0] * 5}, index=days)
    out = panel.build(_ctx(config, closes, pd.DataFrame()), {"heatmaps": heatmaps, "valuation": valuation})
    sector = out["sectors"][0]
    assert sector["forward_pe"] is None and sector["trailing_pe"] is None and sector["path"] is None
    page = _read(_isolated_artifacts / "sectors", "XLRE")
    assert page["valuation"] is None
    assert any("Not valued on earnings" in note for note in page["notes"])
    assert page["relative"]["fund"] == [None] * len(page["relative"]["dates"])   # no SPDR price here: an empty line


def test_the_config_names_the_minimum_members_for_a_band():
    assert load_config()["sectors"]["valuation_min_members"] == 5


def test_the_validator_takes_numbers_and_nulls_and_refuses_strings_and_a_bad_path():
    good = {"missing": [], "sub_industries": [], "sectors": [
        {"key": "XLK", "forward_pe": 25.0, "trailing_pe": None, "pe_percentile": 80, "pe_median_10y": 20.1,
         "forward_pe_median": None, "pe_percentile_median": 50, "path": None},
        {"key": "XLK-SEMI", "path": {"stages": [{"key": "ntm", "pe": 20.0, "growth": None}]}}]}
    assert validate._check_sectors(good) == []
    bad = {"missing": [], "sub_industries": [], "sectors": [
        {"key": "XLK", "forward_pe": "25x", "trailing_pe": True, "path": {"stages": "x"}}]}
    errors = findings_of_errors(bad)
    assert [f.check for f in errors] == ["sectors"] * 3
    assert all(f.severity == "error" for f in errors)
    assert "forward_pe" in errors[0].detail and "trailing_pe" in errors[1].detail and "path" in errors[2].detail
