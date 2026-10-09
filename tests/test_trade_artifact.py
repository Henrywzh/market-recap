"""Trade Desk's bar diagnostics must come from the existing price batch."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from market_recap.panels import positioning, technicals
from market_recap.sources import yahoo


def test_intraday_price_cache_expires_at_close(monkeypatch, tmp_path):
    ny = ZoneInfo("America/New_York")
    saved = datetime(2026, 9, 29, 9, 33, tzinfo=ny)
    monkeypatch.setattr(yahoo.cache, "is_fresh", lambda *a, **k: True)
    monkeypatch.setattr(yahoo.cache, "modified", lambda path: saved)
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.DataFrame(
        {"SPY": [1]}, index=pd.to_datetime(["2026-09-29"])))
    path = tmp_path / "closes.parquet"
    assert not yahoo._read(path, now=datetime(2026, 9, 29, 12, tzinfo=ny)).empty
    assert yahoo._read(path, now=datetime(2026, 9, 29, 16, 20, tzinfo=ny)).empty


def test_yahoo_batch_extracts_ohlcv_without_a_second_request(monkeypatch):
    dates = pd.date_range("2026-09-01", periods=2)
    raw = pd.DataFrame({("Adj Close", "SPY"): [99, 100], ("Close", "SPY"): [100, 101],
                        ("Open", "SPY"): [99, 100], ("High", "SPY"): [101, 102],
                        ("Low", "SPY"): [98, 99], ("Volume", "SPY"): [10, 20]}, index=dates)
    calls = []
    monkeypatch.setattr(yahoo, "_silent_download", lambda *a, **k: calls.append(a) or raw)
    result = yahoo._download_chunk(["SPY"], "1mo")
    assert len(calls) == 1
    assert result["closes"]["SPY"].iloc[-1] == 100
    assert result["high"]["SPY"].iloc[-1] == 102
    assert result["volume"]["SPY"].iloc[-1] == 20


def test_baked_ohlcv_uses_traded_price_basis_and_preserves_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(technicals, "TICKER_ARTIFACT_DIR", tmp_path)
    dates = pd.date_range("2026-09-01", periods=21)
    closes = pd.Series([100.0] * 21, index=dates)
    raw = pd.DataFrame({"SPY": [200.0] * 21}, index=dates)
    frames = {kind: pd.DataFrame({"SPY": [value] * 21}, index=dates)
              for kind, value in (("open", 204.0), ("high", 208.0), ("low", 198.0), ("volume", 1000.0))}
    frames["low"].loc[dates[-1], "SPY"] = float("nan")
    technicals.bake_ticker("SPY", closes, min_sessions=20, ohlcv=frames, raw_prices=raw)
    payload = json.loads((tmp_path / "SPY.json").read_text())
    assert payload["ohlcv"]["close"][-1] == 200.0
    assert payload["ohlcv"]["open"][-1] == 204.0
    assert payload["ohlcv"]["high"][-1] == 208.0
    assert payload["ohlcv"]["low"][-1] is None
    assert payload["ohlcv"]["volume"][-1] == 1000


def test_trend_scorecard_keeps_daily_rows_when_chart_thins_old_history():
    dates = pd.bdate_range("2024-01-01", periods=420)
    ctx = SimpleNamespace(index_closes=pd.DataFrame({"^GSPC": range(100, 520)}, index=dates))
    spec = SimpleNamespace(key="SPX", label="S&P 500", symbol="^GSPC")
    trend = positioning._trend(ctx, spec, {"history_years": 10})
    assert len(trend["scorecard_history"]["dates"]) == 420
    assert len(trend["history"]["close"]["dates"]) < 420
    assert trend["scorecard_history"]["dates"][-1] == trend["as_of"]
