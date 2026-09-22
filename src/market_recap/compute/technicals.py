"""Moving averages, z-score regime, MACD and forward-return statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd

# Bands are labels for a distance, not predictions. The wording stays
# descriptive ("deeply extended") rather than directional ("sell").
ZSCORE_BANDS = (
    (-np.inf, -2.0, "< -2.0", "DEEPLY OVERSOLD"),
    (-2.0, -1.5, "-2.0 to -1.5", "OVERSOLD"),
    (-1.5, -0.5, "-1.5 to -0.5", "BELOW TREND"),
    (-0.5, 0.5, "-0.5 to 0.5", "AT TREND"),
    (0.5, 1.5, "0.5 to 1.5", "ABOVE TREND"),
    (1.5, 2.0, "1.5 to 2.0", "DEEPLY OVERBOUGHT"),
    (2.0, np.inf, "> 2.0", "EXTREMELY OVERBOUGHT"),
)


def moving_averages(closes: pd.Series, windows: list[int]) -> dict[int, pd.Series]:
    return {w: closes.rolling(w, min_periods=w).mean() for w in windows}


def zscore_vs_ma(closes: pd.Series, window: int = 200) -> pd.Series:
    """Distance from the long average measured in that average's own noise."""
    sma = closes.rolling(window, min_periods=window).mean()
    sigma = closes.rolling(window, min_periods=window).std()
    return ((closes - sma) / sigma.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def band_for(value: float | None) -> tuple[str | None, str | None]:
    if value is None or not np.isfinite(value):
        return None, None
    for low, high, label, verdict in ZSCORE_BANDS:
        if low <= value < high:
            return label, verdict
    return None, None


def annualised_ma_slope(closes: pd.Series, window: int = 200, lookback: int = 5) -> float | None:
    """Slope of the SMA over ``lookback`` sessions, annualised to a percent."""
    sma = closes.rolling(window, min_periods=window).mean().dropna()
    if len(sma) < lookback + 1:
        return None
    start, end = float(sma.iloc[-(lookback + 1)]), float(sma.iloc[-1])
    if start <= 0:
        return None
    daily = (end / start) ** (1.0 / lookback) - 1.0
    return float(((1.0 + daily) ** 252 - 1.0) * 100.0)


def sma_slope_series(closes: pd.Series, windows: list[int], lookback: int = 5) -> pd.DataFrame:
    """Per-day percent change of each SMA, the panel's 'is the trend turning' view."""
    out = {}
    for window in windows:
        sma = closes.rolling(window, min_periods=window).mean()
        out[window] = (sma / sma.shift(lookback) - 1.0) / lookback * 100.0
    return pd.DataFrame(out)


def macd(series: pd.Series, fast: int = 8, slow: int = 17, signal: int = 9) -> pd.DataFrame:
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    line = fast_ema - slow_ema
    signal_line = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": signal_line, "histogram": line - signal_line})


def forward_return_by_band(
    closes: pd.Series, *, zscore_window: int = 200, horizon: int = 40
) -> list[dict]:
    """Historical forward return grouped by the z-score band it started in.

    This is a description of what has happened in this sample, not a
    probability of what will happen. The row count is reported alongside every
    statistic precisely so a band with eleven observations cannot be read as
    evidence. The final ``horizon`` sessions are excluded because their forward
    window has not finished yet.
    """
    clean = closes.dropna()
    z = zscore_vs_ma(clean, zscore_window)
    forward = clean.shift(-horizon) / clean - 1.0
    frame = pd.DataFrame({"z": z, "fwd": forward * 100.0}).dropna()
    if frame.empty:
        return []

    rows = []
    for low, high, label, _verdict in ZSCORE_BANDS:
        bucket = frame[(frame["z"] >= low) & (frame["z"] < high)]
        if bucket.empty:
            rows.append({"band": label, "count": 0, "mean": None, "median": None, "hit_rate": None})
            continue
        rows.append(
            {
                "band": label,
                "count": int(len(bucket)),
                "mean": float(bucket["fwd"].mean()),
                "median": float(bucket["fwd"].median()),
                "hit_rate": float((bucket["fwd"] > 0).mean() * 100.0),
            }
        )
    return rows


def relative_strength(numerator: pd.Series, denominator: pd.Series, windows: list[int]) -> pd.DataFrame:
    """Ratio of two price series plus its own moving averages."""
    pair = pd.concat([numerator, denominator], axis=1, keys=["num", "den"]).dropna()
    if pair.empty:
        return pd.DataFrame()
    ratio = pair["num"] / pair["den"]
    out = pd.DataFrame({"ratio": ratio})
    for window in windows:
        out[f"ma{window}"] = ratio.rolling(window, min_periods=window).mean()
    return out
