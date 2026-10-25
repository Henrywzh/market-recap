"""TECHNICALS tab: the close history every indicator is computed from.

The build bakes one small artifact per ticker holding its full close history,
and nothing derived from it. Every indicator -- moving averages, sigma band,
z-score, slope, MACD, forward returns by band -- is computed in the browser by
``web/js/technicals-math.js``, because the reader chooses the windows: a
Python copy for the defaults and a JavaScript copy for the controls would be
two definitions of the same number. ``tests/test_technicals_parity.py`` holds
the JavaScript to the pandas definitions.

Calling a price API from the browser instead would put a key in the page and
break the moment the provider changed its CORS policy.
"""

from __future__ import annotations

import pandas as pd

from .. import corporate_actions
from ..compute.oversold import LINES as OVERSOLD_LINES
from ..config import PERIOD_TRADING_DAYS, TICKER_ARTIFACT_DIR
from ..sources import yahoo
from ..util import clean_float, prune_stale, write_json

# Decimal places kept on a baked close: enough for a sub-dollar ETF, and every
# extra digit is paid for once per session per ticker.
CLOSE_DIGITS = 4
# Two years of traded bars: a 200-session average then spans the Trade Desk's
# whole one-year chart, and the 252-session extremes have room.
OHLCV_SESSIONS = 520
# The bars the volume profile and cost distribution read (web/js/chip-math.js):
# open, high, low, close and volume since BARS_START, in a file of their own so the
# two-year price artifact every ticker page loads does not grow.
BARS_START = "2020-01-01"
BARS_ARTIFACT_DIR = TICKER_ARTIFACT_DIR.parent / "bars"


def _price_digits(values: pd.Series) -> int:
    """Two decimals for a stock priced in dollars, four for one below a dollar."""
    low = values.min()
    return 4 if pd.notna(low) and low < 1 else 2


def bake_bars(symbol: str, raw_prices: pd.DataFrame, ohlcv: dict[str, pd.DataFrame]) -> bool:
    """Write one ticker's daily bars since BARS_START; False when it has none."""
    if symbol not in raw_prices.columns:
        return False
    close = raw_prices[symbol].loc[BARS_START:].dropna()
    if close.empty:
        return False
    frames = {kind: (ohlcv.get(kind, pd.DataFrame())[symbol].reindex(close.index)
                     if symbol in ohlcv.get(kind, pd.DataFrame()).columns else pd.Series(index=close.index, dtype=float))
              for kind in ("open", "high", "low", "volume")}
    if frames["volume"].isna().all():
        return False
    digits = _price_digits(close)
    write_json(BARS_ARTIFACT_DIR / f"{symbol}.json", {
        "ticker": symbol,
        "dates": [d.strftime("%Y-%m-%d") for d in close.index],
        "open": [clean_float(v, digits) for v in frames["open"].to_numpy()],
        "high": [clean_float(v, digits) for v in frames["high"].to_numpy()],
        "low": [clean_float(v, digits) for v in frames["low"].to_numpy()],
        "close": [clean_float(v, digits) for v in close.to_numpy()],
        "volume": [int(v) if pd.notna(v) else None for v in frames["volume"].to_numpy()],
    })
    return True


def bake_ticker(symbol: str, closes: pd.Series, *, min_sessions: int,
                ohlcv: dict[str, pd.DataFrame] | None = None,
                raw_prices: pd.DataFrame | None = None) -> dict | None:
    """Write one ticker's close history; return its index entry.

    A ticker below ``min_sessions`` carries no technical reading at all. Above
    it, the page computes what the history supports and names the rest with
    what it would need ("needs 200 sessions, has 51").
    """
    clean = closes.dropna()
    if len(clean) < min_sessions:
        return None
    payload = {
        "ticker": symbol,
        "as_of": clean.index[-1].strftime("%Y-%m-%d"),
        "first_session": clean.index[0].strftime("%Y-%m-%d"),
        "sessions": int(len(clean)),
        "dates": [d.strftime("%Y-%m-%d") for d in clean.index],
        "close": [clean_float(v, CLOSE_DIGITS) for v in clean.to_numpy()],
    }
    # Same Yahoo batch and dates as the total-return close artifact. Keep
    # tradeable OHLC on Yahoo's split-adjusted (not dividend-adjusted) price
    # basis; the ATR and dollar-volume estimates must not use a total-return
    # price that was never traded. Missing bars remain null.
    if ohlcv and raw_prices is not None and symbol in raw_prices.columns:
        dates = clean.index[-OHLCV_SESSIONS:]
        raw = raw_prices[symbol].reindex(dates)
        vectors = {"close": [clean_float(v, CLOSE_DIGITS) for v in raw.to_numpy()]}
        for kind in ("open", "high", "low", "volume"):
            frame = ohlcv.get(kind, pd.DataFrame())
            values = frame[symbol].reindex(dates) if symbol in frame.columns else pd.Series(index=dates, dtype=float)
            vectors[kind] = [clean_float(v, CLOSE_DIGITS if kind != "volume" else 0) for v in values.to_numpy()]
        payload["ohlcv"] = {"dates": [d.strftime("%Y-%m-%d") for d in dates], **vectors}
    write_json(TICKER_ARTIFACT_DIR / f"{symbol}.json", payload)
    return {"ticker": symbol, "sessions": payload["sessions"]}


def build(ctx) -> dict:
    settings = ctx.config["technicals"]
    chart_periods = list(ctx.config["periods"]["technicals_chart"])
    for key in ("single_ticker_period", "ratio_period"):
        if settings[key] not in chart_periods:
            raise ValueError(f"technicals.{key} = {settings[key]!r} is not one of periods.technicals_chart")

    all_closes = pd.concat([ctx.closes, ctx.etf_closes, ctx.index_closes], axis=1)
    all_closes = all_closes.loc[:, ~all_closes.columns.duplicated()]
    # The bars are read from the cache, not from the context, so the same
    # corporate-action adjustment the context applied has to be applied here:
    # a spun-off parent's traded history would otherwise keep the distribution
    # as a gap. Volume is a count of shares that traded and stays as it was.
    companions = yahoo.fetch_ohlcv_cache(ctx.history_period)
    companions = {kind: corporate_actions.adjust(frame, ctx.adjustments) if kind != "volume" else frame
                  for kind, frame in companions.items()}
    raw_prices = corporate_actions.adjust(yahoo.fetch_prices(ctx.history_period), ctx.adjustments)

    baked, barred = [], []
    for symbol in all_closes.columns:
        try:
            entry = bake_ticker(str(symbol), all_closes[symbol], min_sessions=int(settings["min_sessions"]),
                                ohlcv=companions, raw_prices=raw_prices)
            if entry and bake_bars(str(symbol), raw_prices, companions):
                barred.append(str(symbol))
        except Exception as exc:
            ctx.log.fail(f"technicals:{symbol}", exc)
            continue
        if entry:
            baked.append(entry)

    prune_stale(TICKER_ARTIFACT_DIR, (e["ticker"] for e in baked))
    prune_stale(BARS_ARTIFACT_DIR, barred)
    zwindow = int(settings["zscore_window"])
    return {
        "as_of": ctx.as_of,
        "available": sorted(e["ticker"] for e in baked),
        "partial_history": sorted(e["ticker"] for e in baked if e["sessions"] < zwindow),
        # Tickers with daily bars since BARS_START (artifacts/bars), for the chip distribution.
        "bars": sorted(barred),
        "bars_start": BARS_START,
        # Everything the page's controls start from, so the defaults live in
        # the contract and not in a second copy in JavaScript.
        "defaults": {
            "presets": list(settings["presets"]),
            "ma_periods": list(settings["ma_periods"]),
            "zscore_window": zwindow,
            "band_sigma": float(settings["band_sigma"]),
            "forward_return_days": int(settings["forward_return_days"]),
            "slope_window": int(settings["slope_window"]),
            "ratio_ma_periods": list(settings["ratio_ma_periods"]),
            "macd": {
                "fast": int(settings["macd_fast"]),
                "slow": int(settings["macd_slow"]),
                "signal": int(settings["macd_signal"]),
            },
            "rsi": {"period": int(settings["rsi_period"]),
                    "lines": [{"below": line, "verdict": verdict.upper()} for line, verdict in sorted(OVERSOLD_LINES)]},
            "single_ticker_period": settings["single_ticker_period"],
            "ratio_period": settings["ratio_period"],
        },
        "periods": {label: PERIOD_TRADING_DAYS[label] for label in chart_periods},
        "min_sessions": int(settings["min_sessions"]),
        "note": (
            "Forward-return rows describe what happened in this sample after price sat in a "
            "given band. They are a description of history with its own row count attached, "
            "not a probability of what happens next. A recently listed ticker carries only the "
            "readings its history supports; the rest are named with what they would need."
        ),
    }
