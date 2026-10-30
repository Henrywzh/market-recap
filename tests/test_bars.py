import json

import numpy as np
import pandas as pd

from market_recap.panels import technicals


def test_bars_since_bars_start_with_split_adjusted_prices_and_integer_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(technicals, "BARS_ARTIFACT_DIR", tmp_path)
    dates = pd.bdate_range(pd.Timestamp(technicals.BARS_START) - pd.offsets.BDay(3), periods=8)
    prices = pd.DataFrame({"AAA": np.linspace(10, 17, 8), "PENNY": np.linspace(0.5, 0.57, 8)}, index=dates)
    ohlcv = {kind: prices * factor for kind, factor in (("open", 1.0), ("high", 1.01), ("low", 0.99))}
    ohlcv["volume"] = pd.DataFrame({"AAA": [1e6] * 7 + [np.nan], "PENNY": [5e5] * 8}, index=dates)
    assert technicals.bake_bars("AAA", prices, ohlcv)
    out = json.loads((tmp_path / "AAA.json").read_text())
    assert out["dates"][0] >= technicals.BARS_START and len(out["dates"]) == 5
    assert out["volume"][:4] == [1000000] * 4 and out["volume"][-1] is None
    assert out["close"][0] == round(prices["AAA"].loc[technicals.BARS_START:].iloc[0], 2)
    assert technicals.bake_bars("PENNY", prices, ohlcv)
    penny = json.loads((tmp_path / "PENNY.json").read_text())
    assert penny["close"][0] == round(prices["PENNY"].loc[technicals.BARS_START:].iloc[0], 4)
    assert not technicals.bake_bars("MISSING", prices, ohlcv)


def _long_ctx():
    import types
    from market_recap.util import BuildLog
    idx = pd.bdate_range("1999-12-27", "2026-10-30")
    return types.SimpleNamespace(adjustments=[], log=BuildLog(), closes=pd.DataFrame({"SPY": 1.0}, index=idx[:-1])), idx


def test_long_bars_start_in_2000_and_stop_at_the_builds_session(tmp_path, monkeypatch):
    monkeypatch.setattr(technicals, "BARS_ARTIFACT_DIR", tmp_path)
    ctx, idx = _long_ctx()
    frame = pd.DataFrame({"SPY": np.linspace(100, 600, len(idx)), "QQQ": np.linspace(50, 500, len(idx))}, index=idx)
    monkeypatch.setattr(technicals.yahoo, "fetch_closes", lambda *a, **k: frame)
    monkeypatch.setattr(technicals.yahoo, "fetch_prices", lambda period: frame)
    monkeypatch.setattr(technicals.yahoo, "fetch_ohlcv_cache", lambda period: {"open": frame, "high": frame, "low": frame, "volume": frame * 0 + 1e6})
    out = technicals._bake_long_bars(ctx, {"long_bars": ["SPY", "QQQ", "DIA"], "long_bars_start": "2000-01-01", "long_bars_period": "30y"}, {"SPY", "QQQ"})
    assert out == {"symbols": ["SPY", "QQQ"], "start": "2000-01-01", "first": "2000-01-03"}
    spy = json.loads((tmp_path / "SPY.json").read_text())
    assert spy["dates"][0] == "2000-01-03" and spy["dates"][-1] == ctx.closes.index[-1].strftime("%Y-%m-%d")
    assert [r.status for r in ctx.log.sources] == ["ok"]


def test_long_bars_failure_keeps_the_short_bars_and_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(technicals, "BARS_ARTIFACT_DIR", tmp_path)
    ctx, _ = _long_ctx()

    def boom(*a, **k):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(technicals.yahoo, "fetch_closes", boom)
    out = technicals._bake_long_bars(ctx, {"long_bars": ["SPY"]}, {"SPY"})
    assert out["symbols"] == [] and not list(tmp_path.iterdir())
    assert ctx.log.sources[0].status == "partial" and "yahoo down" in ctx.log.sources[0].error
