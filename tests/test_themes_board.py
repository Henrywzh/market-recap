"""THEMES board: the pure measurements and the label rules."""

import numpy as np
import pandas as pd

from market_recap.compute import themes as T


def _closes(spec: dict[str, list[float]], n=120) -> pd.DataFrame:
    idx = pd.bdate_range("2026-04-01", periods=n)
    return pd.DataFrame({k: v for k, v in spec.items()}, index=idx)


def test_breadth_counts_names_above_their_average_and_up_over_the_month():
    n = 120
    up = list(np.linspace(100, 150, n))
    down = list(np.linspace(150, 100, n))
    flat_then_jump = [100.0] * (n - 1) + [130.0]
    closes = _closes({"UP": up, "DOWN": down, "JUMP": flat_then_jump})
    got = T.breadth(closes, ["UP", "DOWN", "JUMP", "MISSING", "UP"], ma_sessions=50, month=21)
    assert got["of"] == 3                              # a name with no prices and a repeat are not counted
    assert sorted(got["above"]) == ["JUMP", "UP"]
    assert got["above_ma"] == 2 and got["up_month"] == 2


def test_breadth_skips_a_name_with_too_little_history():
    closes = _closes({"SHORT": [np.nan] * 90 + list(range(100, 130))})
    assert T.breadth(closes, ["SHORT"], ma_sessions=50, month=21)["of"] == 0


def test_revision_is_the_median_change_of_names_with_both_readings():
    trends = {
        "A": {"0y": {"eps": 10.5, "eps_30d": 10.0}},     # +5%
        "B": {"0y": {"eps": 9.9, "eps_30d": 10.0}},      # -1%
        "C": {"0y": {"eps": 10.0, "eps_30d": 10.0}},     # 0
        "D": {"0y": {"eps": 5.0, "eps_30d": -1.0}},      # a loss then: no percentage
        "E": {},                                          # no estimates
    }
    got = T.revision(trends, ["A", "B", "C", "D", "E"], "0y", "30d", 0.5)
    assert got == {"of": 3, "median_pct": 0.0, "rising": 1, "falling": 1}
    assert T.revision({}, ["A"], "0y", "30d", 0.5) == {"of": 0, "median_pct": None, "rising": 0, "falling": 0}


def test_valuation_position_needs_enough_names():
    rows = {"A": {"pe_percentile": 10.0}, "B": {"pe_percentile": 30.0}, "C": {"pe_percentile": 80.0}, "D": {"pe_percentile": None}}
    assert T.valuation_position(rows, ["A", "B", "C", "D"]) == {"of": 3, "median_percentile": 30.0}
    assert T.valuation_position(rows, ["A", "B"])["median_percentile"] is None      # two names are not a median


def test_state_crosses_price_with_revisions_and_is_absent_when_either_is():
    kw = dict(relative_pp=2.0, revision_move_pct=0.5)
    assert T.state(4.0, 1.0, **kw) == "strong_rising"
    assert T.state(4.0, -1.0, **kw) == "strong_falling"
    assert T.state(2.0, 0.0, **kw) == "strong_steady"      # the line itself is strong
    assert T.state(-2.5, 0.2, **kw) == "weak_steady"
    assert T.state(-2.5, 0.5, **kw) == "weak_rising"
    assert T.state(0.5, -0.5, **kw) == "flat_falling"
    assert T.state(0.5, 0.0, **kw) == "flat_steady"
    assert T.state(None, 1.0, **kw) is None
    assert T.state(3.0, None, **kw) is None


def test_every_state_has_a_label_in_the_config():
    from market_recap.config import load_config

    labels = load_config()["themes"]["board"]["labels"]
    keys = {f"{p}_{e}" for p in ("strong", "flat", "weak") for e in ("rising", "steady", "falling")}
    assert set(labels) == keys


def test_rs_history_rebases_to_100_and_is_absent_without_history():
    idx = pd.bdate_range("2026-01-02", periods=200)
    proxy = pd.Series(np.linspace(100, 120, 200), index=idx)
    market = pd.Series(100.0, index=idx)
    got = T.rs_history(proxy, market, 126)
    assert len(got["values"]) == 126 and got["values"][0] == 100.0 and got["values"][-1] > 100
    assert T.rs_history(proxy.iloc[:30], market.iloc[:30], 126) is None


def test_board_assembles_from_closes_trends_and_valuation_without_inventing_a_reading():
    import types

    from market_recap.config import load_config
    from market_recap.panels import themes as P

    n = 300
    idx = pd.bdate_range("2025-07-01", periods=n)
    rng = np.random.default_rng(7)
    closes = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n))) for s in ("A", "B", "C")}, index=idx)
    market = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.008, n))), index=idx)
    proxy = closes.mean(axis=1)
    settings = dict(load_config()["themes"])
    ctx = types.SimpleNamespace(closes=closes)
    trends = {"A": {"0y": {"eps": 11.0, "eps_30d": 10.0}}, "B": {"0y": {"eps": 10.0, "eps_30d": 10.0}}}
    rows = {"A": {"pe_percentile": 20.0}, "B": {"pe_percentile": 40.0}, "C": {"pe_percentile": 60.0}}
    board = P._board(ctx, settings, proxy, market, ["A", "B", "C", "NOT_PRICED"], {"vs_spx_3m": 3.0}, trends, rows)
    assert board["breadth"]["of"] == 3 and board["breadth"]["ma_sessions"] == 50
    assert board["revision"]["of"] == 2 and board["revision"]["median_pct"] == 5.0
    assert board["valuation"] == {"of": 3, "median_percentile": 40.0}
    assert board["state"]["key"] == "strong_rising" and board["state"]["label"] == settings["board"]["labels"]["strong_rising"]
    assert board["rrg"]["quadrant"] in {"leading", "weakening", "lagging", "improving"}
    assert len(board["rs"]["values"]) == 126
    # no estimates and no 3M reading: the label is absent, not a guess
    bare = P._board(ctx, settings, proxy, market, ["A"], {}, {}, {})
    assert bare["state"]["key"] is None and bare["state"]["label"] is None
    assert bare["revision"]["median_pct"] is None and bare["valuation"]["median_percentile"] is None
