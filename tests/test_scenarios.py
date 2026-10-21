"""SCENARIOS: the measurements, on synthetic data whose answer is known."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import scenarios as S
from market_recap.config import load_config
from market_recap.panels import scenarios as P


def tv(title, day, actual, forecast, *, hour=13, minute=30, previous=None):
    return {"title": title, "date": f"{day}T{hour:02d}:{minute:02d}:00.000Z", "actual": actual, "forecast": forecast, "previous": previous}


def sessions(start="2016-01-04", end="2026-10-09"):
    return pd.bdate_range(start, end)


def test_robust_scale_resists_an_outlier_and_falls_back_when_most_miss_by_nothing():
    spread = [-2, -1, 0, 1, 2, -2, -1, 0, 1, 2]
    assert S.robust_scale(spread + [10_000]) == pytest.approx(S.robust_scale(spread), rel=0.6)
    assert S.robust_scale(spread + [10_000]) < 5
    mostly_zero = [0.0] * 30 + [0.1, -0.1, 0.1, 0.2, -0.2, 0.1]
    assert S.robust_scale(mostly_zero) > 0       # MAD is 0: the trimmed standard deviation stands in
    assert S.robust_scale([1.0, 2.0, 3.0]) is None   # too few releases
    assert S.robust_scale([0.0] * 20) is None        # no spread at all


def test_release_table_classes_exclusions_and_trading_days():
    days = sessions("2019-01-02", "2022-12-30")
    rows = []
    for i, d in enumerate(pd.date_range("2019-01-15", periods=30, freq="MS") + pd.Timedelta(days=14)):
        d = d if d.weekday() < 5 else d + pd.Timedelta(days=2)
        rows.append(tv("Core Inflation Rate MoM", d.date().isoformat(), 0.3 + 0.1 * (i % 3 - 1), 0.3))
    table, scale = S.release_table(rows, "Core Inflation Rate MoM", start="2019-01-01", exclude=[("2020-03-01", "2020-08-31")],
                                   days=days, threshold_sd=0.7, clip_sd=4, miss_threshold=0.05)
    assert scale is not None and set(table["cls"]) == {"above", "inline", "below"}
    assert table.index.min() >= pd.Timestamp("2019-01-01")
    assert not ((table.index >= "2020-03-01") & (table.index <= "2020-08-31")).any()
    # a 0.1 miss is a miss when the line sets half a tick; on the sd rule a 0.1 miss is within 0.7 sd of a wide series
    assert (table.loc[table["surprise"].round(2) == 0.1, "cls"] == "above").all()
    assert (table.loc[table["surprise"].round(2) == 0.0, "cls"] == "inline").all()
    # a release on a day the market did not trade is left out
    weekend = [tv("X", "2021-01-02", 1.0, 0.0)] * 1
    empty, none_scale = S.release_table(weekend, "X", start="2019-01-01", exclude=[], days=days, threshold_sd=0.7, clip_sd=4)
    assert len(empty) == 0 and none_scale is None


def test_surprise_clipped_so_one_release_cannot_set_a_class():
    days = sessions("2019-01-02", "2019-12-31")
    rows = [tv("L", d.date().isoformat(), 100 + (i % 5), 100) for i, d in enumerate(days[::5][:40])]
    rows.append(tv("L", days[3].date().isoformat(), 100_000, 100))
    table, _ = S.release_table(rows, "L", start="2019-01-01", exclude=[], days=days, threshold_sd=0.7, clip_sd=4)
    assert table["z"].max() == 4


def test_slope_t_recovers_a_line_and_withholds_a_short_sample():
    x = pd.Series(np.linspace(-2, 2, 40))
    y = 3 * x + np.random.default_rng(0).normal(0, 0.1, 40)
    got = S.slope_t(x, y)
    assert got["slope"] == pytest.approx(3, abs=0.05) and got["t"] > 20 and got["n"] == 40
    short = S.slope_t(x[:5], y[:5])
    assert short["slope"] is None and short["n"] == 5
    assert S.slope_t(pd.Series([1.0] * 20), pd.Series(range(20)))["slope"] is None   # no spread in x


def test_class_means_hide_a_class_with_too_few_releases():
    idx = pd.date_range("2021-01-04", periods=12, freq="B")
    table = pd.DataFrame({"cls": ["above"] * 2 + ["below"] * 6 + ["inline"] * 4}, index=idx)
    out = pd.DataFrame({"SPY": np.arange(12, dtype=float)}, index=idx)
    got = S.class_means(table, out, min_n=5)
    assert got["above"] == {"n": 2}                       # count, no figure
    assert got["below"]["SPY"]["mean"] == pytest.approx(np.mean(range(2, 8)))
    assert got["below"]["SPY"]["se"] > 0


def test_era_slopes_label_each_era_and_withhold_thin_ones():
    idx = pd.date_range("2017-01-02", "2025-12-31", freq="W")
    x = pd.Series(np.random.default_rng(1).normal(size=len(idx)), index=idx)
    y = pd.Series(2 * x.to_numpy() + np.random.default_rng(2).normal(0, 0.1, len(idx)), index=idx)
    eras = S.era_slopes(x, y, ["2020-01-01", "2024-01-01"], min_n=8)
    assert [e["era"] for e in eras] == ["2017-2019", "2020-2023", "2024-now"]
    assert all(e["slope"] == pytest.approx(2, abs=0.1) for e in eras)
    thin = S.era_slopes(x, y, ["2020-01-01", "2025-12-01"], min_n=8)
    assert thin[-1]["slope"] is None


def test_rolling_betas_recover_loadings_from_the_last_window_only():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2023-01-02", periods=600)
    f = pd.DataFrame(rng.normal(size=(600, 2)), index=idx, columns=["a", "b"])
    y = pd.Series(np.where(np.arange(600) < 300, 5.0, 1.0) * f["a"] - 2 * f["b"] + rng.normal(0, 0.2, 600), index=idx)
    fit = S.rolling_betas(y, f, window=252)
    assert fit["betas"]["a"] == pytest.approx(1.0, abs=0.1) and fit["betas"]["b"] == pytest.approx(-2.0, abs=0.1)
    assert fit["r2"] > 0.95 and fit["n"] == 252
    assert S.rolling_betas(y.iloc[:100], f.iloc[:100], window=252) is None   # too few days


def test_walk_forward_scores_loadings_that_hold_and_not_ones_that_do_not():
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2018-01-01", periods=1200)
    f = pd.DataFrame(rng.normal(size=(1200, 2)), index=idx, columns=["a", "b"])
    steady = pd.Series(1.5 * f["a"] - 0.5 * f["b"] + rng.normal(0, 0.5, 1200), index=idx)
    held = S.walk_forward_r2(steady, f, window=252, step=21)
    assert held["r2"] > 0.8 and held["n"] == 1200 - 252
    noise = pd.Series(rng.normal(size=1200), index=idx)
    assert S.walk_forward_r2(noise, f, window=252, step=21)["r2"] < 0.02       # nothing to find, nothing claimed
    # loadings that flip sign every year fit the past year perfectly and score badly after it
    sign = np.where((np.arange(1200) // 252) % 2 == 0, 1.0, -1.0)
    flipping = pd.Series(sign * f["a"] + rng.normal(0, 0.1, 1200), index=idx)
    assert S.walk_forward_r2(flipping, f, window=252, step=21)["r2"] < 0
    assert S.walk_forward_r2(steady.iloc[:300], f.iloc[:300], window=252, step=21) is None   # too few days to score


def _days(n=900, seed=0, flip=True, effect=0.5):
    """Release days where a hawkish surprise lifts stocks in a growth-driven market
    and (when ``flip``) drops them in a rates-driven one."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=n)
    z = pd.Series(rng.normal(size=n), index=idx)
    rates = pd.Series(rng.random(n) < 0.4, index=idx)
    sign = np.where(rates, -1.0 if flip else 1.0, 1.0)
    spy = pd.Series(effect * sign * z + rng.normal(0, 0.8, n), index=idx)
    dy2 = pd.Series(2 * z + rng.normal(0, 1, n), index=idx)
    return pd.DataFrame({"z": z, "spy": spy, "dy2": dy2, "rates": rates})


def test_release_days_sign_a_dovish_line_and_flag_the_regime_known_before_the_day():
    idx = pd.bdate_range("2020-01-01", periods=6)
    hot = pd.DataFrame({"z": [1.0, 2.0, np.nan]}, index=idx[:3])
    jobless = pd.DataFrame({"z": [1.0, -1.0, 1.0]}, index=idx[1:4])
    spy = pd.Series(range(6), index=idx, dtype=float)
    corr = pd.Series([-0.5, -0.5, 0.3, 0.3, np.nan, -0.1], index=idx)
    d = S.release_days({"cpi": hot, "claims": jobless}, {"cpi": 1, "claims": -1}, spy, spy * 2, corr)
    # day 1: cpi +2 and claims +1 read as -1 -> mean 0.5; day 2: claims -1 reads as +1 (corr 0.3: growth)
    assert d["z"].loc[idx[1]] == pytest.approx(0.5) and d["z"].loc[idx[2]] == pytest.approx(1.0)
    assert d["rates"].loc[idx[1]] and not d["rates"].loc[idx[2]]
    assert idx[4] not in d.index and idx[0] in d.index                      # a day without a regime reading is left out


def test_regime_response_finds_a_sign_flip_and_not_one_that_is_absent():
    flipped = S.regime_response(_days(flip=True), _days(seed=5), split="2021-01-01", min_n=8, permutations=300, seed=1)
    allrow = flipped["surprise"]["all"]
    assert allrow["by_regime"]["rates"]["slope"] < -0.3 and allrow["by_regime"]["growth"]["slope"] > 0.3
    assert allrow["interaction"]["coef"] < -0.6 and allrow["interaction"]["t"] < -5 and allrow["p_perm"] < 0.02
    same = S.regime_response(_days(flip=False), _days(seed=5), split="2021-01-01", min_n=8, permutations=300, seed=1)
    assert abs(same["surprise"]["all"]["interaction"]["t"]) < 2.5 and same["surprise"]["all"]["p_perm"] > 0.05
    assert flipped["out_of_sample"]["by_regime"] > flipped["out_of_sample"]["pooled"]   # the regime-specific line scores better
    assert flipped["after_the_move"]["release_days"]["rates"]["n"] > 100 and flipped["status"] == "ok"
    thin = S.regime_response(_days(n=10), _days(seed=5), split="2018-01-10", min_n=8, permutations=50, seed=1)
    assert thin["status"] == "insufficient"


def test_event_size_compares_release_days_with_the_others_in_the_stock_s_own_volatility():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2019-01-01", periods=600)
    spy = pd.Series(rng.normal(0, 1, 600), index=idx)
    dy2 = pd.Series(rng.normal(0, 3, 600), index=idx)
    release = idx[100::20]
    spy[release] *= 3
    dy2[release] *= 2
    e = S.event_size(release, spy, dy2, start="2019-06-01")
    assert e["dy2_release"] > 1.6 * e["dy2_other"] and e["spy_release"] > 2 * e["spy_other"] and e["n"] > 15
    assert S.event_size(idx[:0], spy, dy2, start="2019-06-01")["dy2_release"] is None


def _release_frames(pattern_after=1.0, seed=0, late_sector=False):
    """Releases before and after a split whose sector response to 'above' minus
    'below' is the same pattern (scaled by ``pattern_after``) plus noise."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2017-01-02", "2024-12-31")[::10]       # about 100 releases either side of the split
    cls = np.resize(np.array(["above", "below"]), len(idx))
    rng.shuffle(cls)
    pattern = np.array([1.5, -1.0, 0.5, -0.5, 1.0, -1.5])
    sign = np.where(cls == "above", 0.5, -0.5)[:, None]
    after = (idx >= pd.Timestamp("2021-06-01"))[:, None]
    vals = sign * pattern * np.where(after, pattern_after, 1.0) + rng.normal(0, 0.2, (len(idx), 6))
    excess = pd.DataFrame(vals, index=idx, columns=list("ABCDEF"))
    if late_sector:
        excess.loc[excess.index < "2019-01-01", "F"] = np.nan
    return pd.DataFrame({"cls": cls}, index=idx), excess


def test_persistence_finds_a_pattern_that_holds_and_not_one_that_flips():
    table, excess = _release_frames(1.0)
    held = S.persistence(table, excess, split="2021-06-01", min_n=5, permutations=300, seed=1)
    assert held["status"] == "tested" and held["rho"] > 0.8 and held["p_perm"] < 0.1
    table, excess = _release_frames(-1.0)
    flipped = S.persistence(table, excess, split="2021-06-01", min_n=5, permutations=300, seed=1)
    assert flipped["rho"] < -0.8 and flipped["p_perm"] > 0.9


def test_persistence_keeps_a_sector_that_began_late_and_withholds_when_a_class_is_thin():
    table, excess = _release_frames(1.0, late_sector=True)
    got = S.persistence(table, excess, split="2021-06-01", min_n=5, permutations=100, seed=1)
    assert got["status"] == "tested" and got["train_above"] > 5     # the early releases stay in
    thin = table.copy()
    thin["cls"] = "inline"
    thin.iloc[:3, 0] = "above"
    assert S.persistence(thin, excess, split="2021-06-01", min_n=5, permutations=50, seed=1)["status"] == "insufficient"


def test_regime_names_the_sign_of_the_stock_yield_correlation():
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("2024-01-02", periods=200)
    dy = pd.Series(rng.normal(size=200), index=idx)
    spy = pd.Series(-0.8 * dy.to_numpy() + rng.normal(0, 0.3, 200), index=idx)
    got = S.regime(spy, dy, sessions=60)
    assert got["label"] == "rates" and got["corr"] < -0.5 and got["share_negative"] == pytest.approx(1.0)
    assert S.regime(spy.iloc[:30], dy.iloc[:30], sessions=60)["label"] is None


# --- the panel, end to end, on synthetic series ---------------------------------

def _config(**over):
    cfg = dict(load_config()["scenarios"])
    cfg.update(permutations=60, **over)
    return cfg


def _market():
    rng = np.random.default_rng(5)
    idx = sessions("2016-01-04", "2026-10-09")
    cols = ["SPY", "XLK", "XLF", "IWM", "KRE", "HYG", "LQD", "CL=F", "UUP"]
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.008, (len(idx), len(cols))), axis=0)), index=idx, columns=cols)
    y10 = pd.Series(2 + np.cumsum(rng.normal(0, 0.03, len(idx))), index=idx)
    y2 = pd.Series(1 + np.cumsum(rng.normal(0, 0.03, len(idx))), index=idx)
    return idx, closes, y10, y2


def _calendar(idx):
    rows = []
    for i, d in enumerate(idx[::21][:120]):
        rows.append(tv("Non Farm Payrolls", d.date().isoformat(), 150 + 80 * ((i % 5) - 2), 150))
        rows.append(tv("Fed Interest Rate Decision", d.date().isoformat(), 4.0, 4.0 if i % 20 else 3.75, previous=4.0, hour=19))
    return rows


def test_panel_assembles_measurements_without_inventing_any():
    cfg = _config(drivers=[{"key": "payrolls", "label": "Nonfarm payrolls", "title": "Non Farm Payrolls", "unit": "k"},
                           {"key": "missing", "label": "Not on the calendar", "title": "No Such Line", "unit": "k"}])
    idx, closes, y10, y2 = _market()
    upcoming = [tv("Non Farm Payrolls", "2026-10-16", None, 120, previous=90, hour=12)]
    payload = P.assemble(as_of=date(2026, 10, 9), closes=closes, y10=y10, y2=y2, rows=_calendar(idx), upcoming=upcoming,
                         sectors={"Information Technology": "XLK", "Financials": "XLF", "Energy": "XLE"}, market="SPY", cfg=cfg)
    json.dumps(payload, allow_nan=False)                      # no NaN reaches the page
    by_key = {d["key"]: d for d in payload["drivers"]}
    nfp = by_key["payrolls"]
    assert nfp["status"] == "ok" and nfp["n"] >= 100 and set(nfp["classes"]) == {"above", "inline", "below"}
    assert nfp["next"] == {"date": "2026-10-16", "time": "08:30", "forecast": 120.0, "previous": 90.0, "unit": "k"}
    assert by_key["missing"]["status"] == "insufficient" and by_key["missing"]["n"] == 0 and "classes" not in by_key["missing"]
    assert "XLE" not in {s["etf"] for s in payload["sectors"]}   # a sector with no prices is absent, not zero
    assert "nowcast" not in payload
    assert payload["fomc"]["decisions"] > 50 and payload["fomc"]["decisions_with_surprise"] >= 1
    assert nfp["event_size"]["n"] >= 100 and nfp["event_size"]["dy2_other"] > 0
    assert payload["regime_response"]["status"] in ("ok", "insufficient") and "event_size" not in by_key["missing"]


def test_latest_release_is_the_last_row_of_its_table_and_the_published_tick_is_kept():
    cfg = _config(drivers=[{"key": "payrolls", "label": "Nonfarm payrolls", "title": "Non Farm Payrolls", "unit": "k",
                            "miss_threshold": 5},
                           {"key": "missing", "label": "Not on the calendar", "title": "No Such Line", "unit": "k"}])
    idx, closes, y10, y2 = _market()
    rows = _calendar(idx)
    payload = P.assemble(as_of=date(2026, 10, 9), closes=closes, y10=y10, y2=y2, rows=rows, upcoming=[],
                         sectors={"Information Technology": "XLK"}, market="SPY", cfg=cfg)
    by_key = {d["key"]: d for d in payload["drivers"]}
    nfp, missing = by_key["payrolls"], by_key["missing"]
    last = max((r for r in rows if r["title"] == "Non Farm Payrolls"), key=lambda r: r["date"])
    day = pd.Timestamp(last["date"][:10])
    surprise = last["actual"] - last["forecast"]
    assert nfp["miss_threshold"] == 5 and missing["miss_threshold"] is None
    assert nfp["latest"]["date"] == day.date().isoformat()
    assert nfp["latest"]["actual"] == last["actual"] and nfp["latest"]["forecast"] == 150.0
    assert nfp["latest"]["surprise"] == pytest.approx(surprise)
    assert nfp["latest"]["cls"] == ("above" if surprise > 5 else "below" if surprise < -5 else "inline")
    assert nfp["latest"]["dY2"] == pytest.approx(float(y2.diff().loc[day] * 100), abs=1e-3)
    assert nfp["latest"]["SPY"] == pytest.approx(float(closes["SPY"].pct_change().loc[day] * 100), abs=1e-3)
    assert "latest" not in missing and missing["status"] == "insufficient"


def test_a_session_after_the_last_yield_is_reported_as_one_the_yields_do_not_reach():
    cfg = _config(drivers=[])
    idx, closes, y10, y2 = _market()
    y10, y2 = y10.iloc[:-1], y2.iloc[:-1]                      # FRED has not published the last session
    payload = P.assemble(as_of=date(2026, 10, 9), closes=closes, y10=y10, y2=y2, rows=[], upcoming=[],
                         sectors={"Information Technology": "XLK"}, market="SPY", cfg=cfg)
    assert payload["inputs"]["yields_through"] == idx[-2].date().isoformat()
    assert payload["inputs"]["prices_through"] == idx[-1].date().isoformat()


def test_prices_after_the_as_of_date_are_not_read():
    cfg = _config(drivers=[])
    idx, closes, y10, y2 = _market()
    payload = P.assemble(as_of=date(2026, 6, 30), closes=closes, y10=y10, y2=y2, rows=[], upcoming=[],
                         sectors={"Information Technology": "XLK"}, market="SPY", cfg=cfg)
    assert payload["inputs"]["prices_through"] <= "2026-06-30"


def test_every_configured_driver_names_a_line_and_a_unit():
    drivers = load_config()["scenarios"]["drivers"]
    assert len({d["key"] for d in drivers}) == len(drivers)
    assert all(d["title"] and d["label"] and d["unit"] for d in drivers)
    assert all(d.get("miss_threshold", 1) > 0 for d in drivers)
