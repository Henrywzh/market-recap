"""TECHNICALS tab: relative strength, single-ticker regime, forward statistics.

Every ticker the tab can load is baked to its own small artifact at build
time. The alternative -- calling a price API from the browser -- would put a
key in the page and break the moment the provider changed its CORS policy.
"""

from __future__ import annotations

import pandas as pd

from ..compute import technicals as T
from ..config import TICKER_ARTIFACT_DIR, period_sessions
from ..util import clean_float, write_json


def _series(values: pd.Series, digits: int = 4) -> list:
    return [clean_float(v, digits) for v in values.to_numpy()]


def bake_ticker(symbol: str, closes: pd.Series, config: dict) -> dict | None:
    """Write one ticker's technical payload; return its index entry.

    Every derived series has its own history requirement, and a recent listing
    satisfies some and not others: SK hynix's US line has fifty sessions, which
    is plenty for a 20-day average and nowhere near a 200-day z-score. Refusing
    the whole ticker for that -- which is what a single 250-session gate did --
    hides a name the user asked to follow. Each series is computed only where
    it can be, and what is missing is named with the reason, so the tab can say
    "needs 200 sessions, has 51" instead of rendering an empty chart.
    """
    settings = config["technicals"]
    clean = closes.dropna()
    sessions = int(len(clean))
    if sessions < int(settings["min_sessions"]):
        return None

    windows = list(settings["ma_periods"])
    zwindow = int(settings["zscore_window"])
    horizon = int(settings["forward_return_days"])
    sigma_multiple = float(settings["band_sigma"])
    unavailable: dict[str, str] = {}

    # The longest window the tab offers, from the same table the charts read.
    tail = period_sessions(config["periods"]["chart_window"])
    view = clean.tail(tail)

    available_windows = [w for w in windows if sessions >= w]
    for window in windows:
        if window not in available_windows:
            unavailable[f"sma_{window}"] = f"needs {window} sessions, has {sessions}"
    mas = T.moving_averages(clean, available_windows)

    if sessions >= zwindow:
        sma_long = clean.rolling(zwindow, min_periods=zwindow).mean()
        sigma = clean.rolling(zwindow, min_periods=zwindow).std()
        z = T.zscore_vs_ma(clean, zwindow)
        last_z = clean_float(z.dropna().iloc[-1], 2) if not z.dropna().empty else None
        band, verdict = T.band_for(last_z)
        band_upper = _series((sma_long + sigma_multiple * sigma).tail(tail), 2)
        band_lower = _series((sma_long - sigma_multiple * sigma).tail(tail), 2)
        zscore = _series(z.tail(tail), 3)
        distance = (
            clean_float((clean.iloc[-1] / sma_long.iloc[-1] - 1) * 100, 2)
            if pd.notna(sma_long.iloc[-1]) and sma_long.iloc[-1]
            else None
        )
        sma_long_last = clean_float(sma_long.iloc[-1], 2)
        slope_ann = clean_float(T.annualised_ma_slope(clean, window=zwindow), 1)
    else:
        reason = f"needs {zwindow} sessions, has {sessions}"
        unavailable |= {
            "zscore": reason,
            "sigma_band": reason,
            "long_average": reason,
            "slope_annualised": reason,
        }
        last_z = band = verdict = distance = sma_long_last = slope_ann = None
        band_upper = band_lower = zscore = []

    slopes = T.sma_slope_series(clean, available_windows) if available_windows else pd.DataFrame()
    macd_frame = T.macd(
        clean,
        fast=int(settings["macd_fast"]),
        slow=int(settings["macd_slow"]),
        signal=int(settings["macd_signal"]),
    )

    if sessions >= zwindow + horizon:
        forward_rows = T.forward_return_by_band(clean, zscore_window=zwindow, horizon=horizon)
    else:
        forward_rows = []
        unavailable["forward_returns"] = (
            f"needs {zwindow + horizon} sessions ({zwindow} to form the z-score plus {horizon} "
            f"for the forward window), has {sessions}"
        )

    payload = {
        "ticker": symbol,
        "as_of": view.index[-1].strftime("%Y-%m-%d"),
        "sessions": sessions,
        "first_session": clean.index[0].strftime("%Y-%m-%d"),
        "zscore_window": zwindow,
        "band_sigma": sigma_multiple,
        "dates": [d.strftime("%Y-%m-%d") for d in view.index],
        "close": _series(view, 2),
        "moving_averages": {str(w): _series(mas[w].tail(tail), 2) for w in available_windows},
        "band_upper": band_upper,
        "band_lower": band_lower,
        "zscore": zscore,
        "sma_slope": {str(w): _series(slopes[w].tail(tail), 4) for w in available_windows},
        "macd": {
            "macd": _series(macd_frame["macd"].tail(tail), 4),
            "signal": _series(macd_frame["signal"].tail(tail), 4),
            "histogram": _series(macd_frame["histogram"].tail(tail), 4),
        },
        "summary": {
            "price": clean_float(clean.iloc[-1], 2),
            "sma_long": sma_long_last,
            "distance_pct": distance,
            "zscore": last_z,
            "zscore_band": band,
            "verdict": verdict,
            "slope_annualised": slope_ann,
        },
        "forward_returns": {
            "horizon": horizon,
            "sessions": sessions,
            "start": clean.index[0].strftime("%Y-%m-%d"),
            "rows": forward_rows,
        },
        "unavailable": unavailable,
    }
    write_json(TICKER_ARTIFACT_DIR / f"{symbol}.json", payload)
    return {"ticker": symbol, "as_of": payload["as_of"], "verdict": verdict, "sessions": sessions}


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

    settings = config["technicals"]
    partial = sorted(e["ticker"] for e in baked if e["sessions"] < int(settings["zscore_window"]))
    return {
        "as_of": ctx.as_of,
        "min_sessions": int(settings["min_sessions"]),
        "partial_history": partial,
        "presets": list(settings["presets"]),
        "ma_periods": list(settings["ma_periods"]),
        "zscore_window": settings["zscore_window"],
        "forward_return_days": settings["forward_return_days"],
        "macd": {
            "fast": settings["macd_fast"],
            "slow": settings["macd_slow"],
            "signal": settings["macd_signal"],
        },
        "available": sorted(e["ticker"] for e in baked),
        "note": (
            "Forward-return rows describe what happened in this sample after price sat in a "
            "given band. They are a description of history with its own row count attached, "
            "not a probability of what happens next. A recently listed ticker carries only the "
            "readings its history supports; the rest are named with what they would need."
        ),
    }
