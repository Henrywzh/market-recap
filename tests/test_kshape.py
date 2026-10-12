"""K-SHAPE: ratios of a high-income leg to a low-income leg, on series whose answer is known."""

import json

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import kshape as K
from market_recap.config import load_config
from market_recap.panels import kshape as P


def days(n=700, start="2023-01-02"):
    return pd.bdate_range(start, periods=n)


def test_leg_index_is_equal_weight_rebalanced_daily_and_a_late_listing_starts_at_its_listing():
    idx = days(5)
    closes = pd.DataFrame({"A": [100, 110, 121, 121, 121.0], "B": [50, 50, 50, 55, 55.0], "LATE": [np.nan, np.nan, 10, 10, 12.0]}, index=idx)
    two = K.leg_index(closes, ["A", "B"])
    assert two.iloc[0] == 100 and two.iloc[1] == pytest.approx(100 * (1 + (0.10 + 0.0) / 2))     # day 2: A +10%, B flat
    late = K.leg_index(closes, ["LATE"])
    assert late.index[0] == idx[0] or late.index[0] == idx[2]                                     # nothing before the first close
    assert late.iloc[-1] == pytest.approx(100 * 1.2)
    assert K.leg_index(closes, ["NOPE"]).empty


def test_spread_table_leaves_a_window_longer_than_the_common_history_absent():
    idx = days(300)
    top = pd.Series(np.linspace(100, 130, 300), index=idx)
    bottom = pd.Series(np.linspace(100, 110, 300), index=idx)
    rows = {r["period"]: r for r in K.spread_table(top, bottom, {"1M": 21, "1Y": 252, "5Y": 1260})}
    assert rows["1M"]["spread"] == pytest.approx(rows["1M"]["top"] - rows["1M"]["bottom"]) and rows["1M"]["spread"] > 0
    assert rows["5Y"] == {"period": "5Y", "top": None, "bottom": None, "spread": None}           # 300 sessions do not make five years


def test_percentile_is_the_share_of_the_series_at_or_below_and_needs_enough_weeks():
    s = pd.Series(np.arange(100.0))
    assert K.percentile(s, 89.0) == pytest.approx(90.0)
    assert K.percentile(s, -5.0) == 0.0 and K.percentile(s, 1e9) == 100.0
    assert K.percentile(s.iloc[:20], 5.0) is None and K.percentile(s, None) is None


def test_median_multiple_counts_only_meaningful_pes_and_blanks_a_week_most_names_lost_their_earnings():
    idx = days(8)
    pe = {"A": pd.Series([10, 12, -5, -5, 20, 20, 900, 20.0], index=idx),
          "B": pd.Series([20, 22, -9, 15, 15, 30, 30, 30.0], index=idx),
          "C": pd.Series([30, 32, -3, -3, -3, 40, 40, 40.0], index=idx)}
    m = K.median_multiple(pe, ["A", "B", "C"], min_share=0.5, cap=60.0)
    assert m.loc[idx[0]] == 20 and m.loc[idx[5]] == 30                       # the median of three
    assert idx[2] not in m.index                                             # all three had losses
    assert idx[3] not in m.index                                             # one of three earning is under half: blank, not that one's P/E
    assert m.loc[idx[4]] == pytest.approx(17.5)                              # two of three: the median of those two
    assert m.loc[idx[6]] == pytest.approx(35.0)                              # 900x is a profit near zero: left out, two of three remain
    assert K.median_multiple(pe, ["NOPE"]).empty


def test_ratio_needs_both_legs_and_a_positive_bottom():
    idx = days(4)
    top = pd.Series([10, 20, 30, np.nan], index=idx)
    bottom = pd.Series([5, 0, 10, 10.0], index=idx)
    r = K.ratio(top, bottom)
    assert list(r.index) == [idx[0], idx[2]] and list(r) == [2.0, 3.0]


def test_eps_growth_is_drawn_off_a_positive_year_ago_and_within_the_cap():
    rows = [{"period_end": f"{y}-12-31", "operating": v} for y, v in [(2020, 1.0), (2021, 1.5), (2022, -0.5), (2023, 0.1), (2024, 0.5), (2025, 1.0)]]
    g = K.eps_growth(rows, cap=150.0)
    assert g.loc[pd.Timestamp("2021-12-31")] == pytest.approx(50.0)
    assert g.loc[pd.Timestamp("2022-12-31")] == pytest.approx(-133.333, abs=0.01)   # a fall into loss, off a positive year, within the cap: drawn
    # 2023: prior year was a loss -> absent; 2024: 0.5 off 0.1 is +400%: past the cap -> absent; 2025: 1.0 off 0.5 is +100%
    assert pd.Timestamp("2023-12-31") not in g.index and pd.Timestamp("2024-12-31") not in g.index
    assert g.loc[pd.Timestamp("2025-12-31")] == pytest.approx(100.0)
    assert K.eps_growth([]).empty


def test_median_growth_and_median_of_skip_what_is_missing():
    idx = pd.to_datetime(["2024-12-31", "2025-12-31"])
    by = {"A": pd.Series([10.0, 20.0], index=idx), "B": pd.Series([30.0], index=idx[:1]), "C": pd.Series(dtype=float)}
    m = K.median_growth(by, ["A", "B", "C"])
    assert list(m) == [20.0, 20.0]
    assert K.median_of([None, 3.0, float("nan"), 5.0]) == 4.0 and K.median_of([None]) is None


# --- the panel ----------------------------------------------------------------------

def _cfg(**over):
    cfg = dict(load_config()["kshape"])
    cfg.update(pairs=[{"key": "air", "label": "AIR", "top": ["T1", "T2"], "bottom": ["B1", "NEW"], "note": "n"}], bottom_only=["LOW"], **over)
    return cfg


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def fail(self, *a):
        raise AssertionError(a)


def _ctx(monkeypatch, histories, trends):
    rng = np.random.default_rng(3)
    idx = days(800)
    cols = ["T1", "T2", "B1", "LOW"]
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, (len(idx), len(cols))), axis=0)), index=idx, columns=cols)
    cfg = load_config()
    cfg = {**cfg, "kshape": _cfg()}
    ctx = type("C", (), {"config": cfg, "as_of": idx[-1].date().isoformat(), "closes": closes, "log": _Log()})()
    monkeypatch.setattr(P, "_read_history", lambda t: histories.get(t))
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda syms, **kw: pd.DataFrame({s: 50 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))) for s in syms}, index=idx[-300:]))
    monkeypatch.setattr(P.estimates, "fetch_trends", lambda syms, **kw: ({s: trends[s] for s in syms if s in trends}, {}))
    return ctx, idx


def _history(idx, pes, eps):
    weekly = idx[::5]
    return {"dates": [d.strftime("%Y-%m-%d") for d in weekly], "pe": pes[: len(weekly)] + [pes[-1]] * max(0, len(weekly) - len(pes)),
            "eps": [{"period_end": d, "operating": v} for d, v in eps]}


def test_panel_builds_pairs_and_the_overall_view_and_gives_a_name_outside_valuation_a_consensus_multiple(monkeypatch):
    idx = days(800)
    flat = lambda v: _history(idx, [v], [("2023-12-31", 0.9), ("2024-12-31", 1.0), ("2025-12-31", 1.2)])        # noqa: E731
    histories = {"T1": flat(20.0), "T2": flat(24.0), "B1": flat(10.0)}
    trends = {"NEW": {"0y": {"eps": 5.0, "end": "2026-12-31", "year_ago_eps": 4.0}, "+1y": {"eps": 6.0, "end": "2027-12-31"}}}
    ctx, idx = _ctx(monkeypatch, histories, trends)
    valuation = {"rows": [{"ticker": t, "pe_forward": pf, "pe_percentile": 50, "eps_fy_prev": 1.0, "eps_fy0": 1.2, "revenue_growth": 5.0}
                          for t, pf in (("T1", 22.0), ("T2", 26.0), ("B1", 11.0), ("LOW", 12.0))], "as_of": ctx.as_of}
    p = P.build(ctx, inputs={"valuation": valuation})
    json.dumps(p, allow_nan=False)
    assert [v["key"] for v in p["views"]] == ["overall", "air"]
    air = p["views"][1]
    assert air["price"]["since"] and len(air["price"]["ratio"]) == len(air["price"]["dates"])
    assert air["pe"]["now"]["top"] == 22.0 and air["pe"]["now"]["bottom"] == 10.0 and air["pe"]["now"]["ratio"] == 2.2
    assert air["pe"]["covered"] == {"top": ["T1", "T2"], "bottom": ["B1"]}                  # NEW has no filings history
    assert air["eps"]["top"][-1] == pytest.approx(20.0)
    rows = {n["ticker"]: n for n in air["names"]}
    assert rows["NEW"]["forward_source"] == "consensus" and rows["NEW"]["pe_forward"] and rows["NEW"]["eps_growth_this_year"] == 25.0
    assert rows["T1"]["forward_source"] == "valuation" and rows["T1"]["eps_growth_this_year"] == pytest.approx(20.0)
    assert air["now"]["pe_forward_top"] == 24.0 and air["now"]["pe_forward_ratio"] is not None
    assert "LOW" in p["views"][0]["bottom"] and p["inputs"]["valuation_built"] and p["inputs"]["no_prices"] == []


def test_without_valuation_the_panel_shows_prices_only_and_says_so(monkeypatch):
    ctx, _ = _ctx(monkeypatch, {}, {})
    p = P.build(ctx, inputs={})
    air = p["views"][1]
    assert air["price"] is not None and air["pe"] is None and air["eps"] is None
    assert not p["inputs"]["valuation_built"]
    assert all(n["pe_forward"] is None or n["forward_source"] == "consensus" for n in air["names"])
    json.dumps(p, allow_nan=False)
