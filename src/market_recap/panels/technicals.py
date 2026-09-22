"""TECHNICALS tab: relative strength, single-ticker regime, forward statistics.

Every ticker the tab can load is baked to its own small artifact at build
time. The alternative -- calling a price API from the browser -- would put a
key in the page and break the moment the provider changed its CORS policy.
"""

from __future__ import annotations

import pandas as pd

from ..compute import technicals as T
from ..config import TICKER_ARTIFACT_DIR
from ..util import clean_float, write_json


def _series(values: pd.Series, digits: int = 4) -> list:
    return [clean_float(v, digits) for v in values.to_numpy()]


def bake_ticker(symbol: str, closes: pd.Series, config: dict) -> dict | None:
    """Write one ticker's technical payload; return its index entry."""
    clean = closes.dropna()
    if len(clean) < 250:
        return None

    windows = list(config["technicals"]["ma_periods"])
    zwindow = int(config["technicals"]["zscore_window"])
    horizon = int(config["technicals"]["forward_return_days"])

    mas = T.moving_averages(clean, windows)
    sma_long = clean.rolling(zwindow, min_periods=zwindow).mean()
    sigma = clean.rolling(zwindow, min_periods=zwindow).std()
    z = T.zscore_vs_ma(clean, zwindow)
    last_z = clean_float(z.dropna().iloc[-1], 2) if not z.dropna().empty else None
    band, verdict = T.band_for(last_z)

    slopes = T.sma_slope_series(clean, windows)
    macd_frame = T.macd(clean)

    tail = 504  # two years of chart, the longest window the tab offers
    view = clean.tail(tail)
    payload = {
        "ticker": symbol,
        "as_of": view.index[-1].strftime("%Y-%m-%d"),
        "dates": [d.strftime("%Y-%m-%d") for d in view.index],
        "close": _series(view, 2),
        "moving_averages": {str(w): _series(mas[w].tail(tail), 2) for w in windows},
        "band_upper": _series((sma_long + 1.5 * sigma).tail(tail), 2),
        "band_lower": _series((sma_long - 1.5 * sigma).tail(tail), 2),
        "zscore": _series(z.tail(tail), 3),
        "sma_slope": {str(w): _series(slopes[w].tail(tail), 4) for w in windows},
        "macd": {
            "macd": _series(macd_frame["macd"].tail(tail), 4),
            "signal": _series(macd_frame["signal"].tail(tail), 4),
            "histogram": _series(macd_frame["histogram"].tail(tail), 4),
        },
        "summary": {
            "price": clean_float(clean.iloc[-1], 2),
            "sma_long": clean_float(sma_long.iloc[-1], 2),
            "distance_pct": clean_float((clean.iloc[-1] / sma_long.iloc[-1] - 1) * 100, 2)
            if pd.notna(sma_long.iloc[-1]) and sma_long.iloc[-1]
            else None,
            "zscore": last_z,
            "zscore_band": band,
            "verdict": verdict,
            "slope_annualised": clean_float(T.annualised_ma_slope(clean, zwindow), 1),
        },
        "forward_returns": {
            "horizon": horizon,
            "sessions": int(len(clean)),
            "start": clean.index[0].strftime("%Y-%m-%d"),
            "rows": T.forward_return_by_band(clean, zscore_window=zwindow, horizon=horizon),
        },
    }
    write_json(TICKER_ARTIFACT_DIR / f"{symbol}.json", payload)
    return {"ticker": symbol, "as_of": payload["as_of"], "verdict": verdict}


def build(ctx) -> dict:
    config = ctx.config
    all_closes = pd.concat([ctx.closes, ctx.etf_closes, ctx.index_closes], axis=1)
    all_closes = all_closes.loc[:, ~all_closes.columns.duplicated()]

    baked = []
    for symbol in all_closes.columns:
        try:
            entry = bake_ticker(str(symbol), all_closes[symbol], config)
        except Exception as exc:
            ctx.log.fail(f"technicals:{symbol}", exc)
            continue
        if entry:
            baked.append(entry)

    return {
        "as_of": ctx.as_of,
        "presets": list(config["technicals"]["presets"]),
        "ma_periods": list(config["technicals"]["ma_periods"]),
        "zscore_window": config["technicals"]["zscore_window"],
        "forward_return_days": config["technicals"]["forward_return_days"],
        "available": sorted(e["ticker"] for e in baked),
        "note": (
            "Forward-return rows describe what happened in this sample after price sat in a "
            "given band. They are a description of history with its own row count attached, "
            "not a probability of what happens next."
        ),
    }
