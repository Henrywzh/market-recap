"""Guard the context's time boundary, asset-specific scale and unknowns."""
import copy

import numpy as np
import pandas as pd
import pytest

from market_recap.compute.risk_context import assemble
from market_recap.config import load_config


def inputs():
    cfg = copy.deepcopy(load_config()["risk"]["context"])
    dates = pd.bdate_range("2023-01-02", periods=600)
    rng = np.random.default_rng(9)
    noise = rng.normal(0, 0.01, len(dates))
    prices = pd.DataFrame({a["symbol"]: 100 * np.exp(np.cumsum(noise * (i + 1)))
                           for i, a in enumerate(cfg["assets"])}, index=dates)
    prices["one"] = np.linspace(100, 200, len(dates))
    prices["two"] = np.linspace(200, 100, len(dates))
    return prices, cfg


def build(prices, cfg, as_of=None):
    return assemble(prices, as_of=as_of or prices.index[-1].strftime("%Y-%m-%d"),
                    cfg=cfg, sector_roster=["one", "two"])


def test_scale_uses_only_prior_returns_and_is_asset_specific():
    prices, cfg = inputs()
    result = build(prices, cfg)
    a, b = result["assets"][:2]
    expected = np.log(prices[a["symbol"]] / prices[a["symbol"]].shift(1)).iloc[-253:-1].std() * np.sqrt(21) * 100
    assert a["latest"]["monthly_sigma_pct"] == pytest.approx(expected, abs=0.0001)
    assert b["latest"]["monthly_sigma_pct"] == pytest.approx(2 * expected, abs=0.0001)
    prices.loc[prices.index[-1], a["symbol"]] *= 0.5
    shocked = build(prices, cfg)["assets"][0]
    assert shocked["latest"]["monthly_sigma_pct"] == a["latest"]["monthly_sigma_pct"]
    assert shocked["latest"]["drawdown_sigma"] > a["latest"]["drawdown_sigma"]


def test_future_closes_cannot_change_a_dated_context():
    prices, cfg = inputs()
    cutoff = prices.index[-25].strftime("%Y-%m-%d")
    assert build(prices, cfg, cutoff) == build(prices.loc[:cutoff], cfg, cutoff)


def test_missing_sector_does_not_become_below_average_or_smaller_denominator():
    prices, cfg = inputs()
    complete = build(prices, cfg)["breadth"]
    assert complete["latest"]["above_20d_pct"] == 50
    prices = prices.drop(columns="two")
    missing = build(prices, cfg)["breadth"]
    assert missing["latest"]["above_20d_pct"] is None
    assert missing["members"][1]["above"]["20"] is None
    assert missing["roster"] == ["one", "two"]


def test_missing_asset_and_short_history_stay_unknown():
    prices, cfg = inputs()
    prices = prices.drop(columns=cfg["assets"][0]["symbol"]).tail(30)
    missing, short = build(prices, cfg)["assets"][:2]
    assert missing["date"] is None and missing["stale"]
    assert all(v is None for v in missing["latest"].values())
    assert short["latest"]["drawdown_sigma"] is None


def test_stale_asset_keeps_its_own_date_without_forward_filling():
    prices, cfg = inputs()
    prices.loc[prices.index[-3]:, cfg["assets"][0]["symbol"]] = np.nan
    asset = build(prices, cfg)["assets"][0]
    assert asset["date"] == prices.index[-4].strftime("%Y-%m-%d")
    assert asset["stale"]


def test_constituent_breadth_excludes_unknown_members_and_reports_coverage():
    prices, cfg = inputs()
    result = assemble(prices, as_of=prices.index[-1].strftime('%Y-%m-%d'), cfg=cfg,
                      sector_roster=['one', 'two'], constituents=['one', 'two', 'missing'],
                      universe_label='Example index')['constituent_breadth']
    assert result['latest']['above_20d_count'] == 1
    assert result['latest']['eligible_20d'] == 2
    assert result['latest']['above_20d_pct'] == 50
    assert len(result['roster']) == 3
    assert result['history']['above_200d_pct'][0] is None
    prices.loc[prices.index[-1], ['one', 'two']] = np.nan
    missing = assemble(prices, as_of=prices.index[-1].strftime('%Y-%m-%d'), cfg=cfg,
                       sector_roster=[], constituents=['one', 'two'])['constituent_breadth']
    assert missing['latest']['above_20d_pct'] is None
    assert missing['latest']['eligible_20d'] == 0


def test_a_holiday_row_one_source_dated_does_not_blank_the_long_averages():
    prices, cfg = inputs()
    clean = build(prices, cfg)
    # Holidays that only one series carries a value on: every other column is empty there.
    holidays = pd.DatetimeIndex(["2024-07-04", "2024-11-28", "2024-12-25"]) + pd.Timedelta(hours=1)
    extra = pd.DataFrame(np.nan, index=holidays, columns=prices.columns)
    extra[prices.columns[-1]] = 150.0
    gapped = build(pd.concat([prices, extra]).sort_index(), cfg)
    for before, after in zip(clean["assets"], gapped["assets"]):
        assert after["latest"]["ma200"] is not None
        assert after["latest"]["ma200"] == pytest.approx(before["latest"]["ma200"])
        assert after["latest"]["drawdown_sigma"] == pytest.approx(before["latest"]["drawdown_sigma"])
    # A missing close on a real session is still a gap, not bridged.
    lone = prices.copy()
    lone.iloc[-5, 0] = np.nan
    assert build(lone, cfg)["assets"][0]["latest"]["ma20"] is None


def test_validation_flags_a_year_of_closes_with_no_long_average():
    from market_recap.validate import _check_risk_context
    prices, cfg = inputs()
    good = {"context": build(prices, cfg)}
    assert _check_risk_context(good) == []
    broken = copy.deepcopy(good)
    broken["context"]["assets"][0]["latest"]["ma200"] = None
    broken["context"]["constituent_breadth"] = {"latest": {"eligible_20d": 502, "eligible_200d": 0}}
    findings = _check_risk_context(broken)
    assert [f.severity for f in findings] == ["warning", "warning"]
    assert _check_risk_context(None) == []
