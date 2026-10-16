"""Today's move in each stock's own terms: how many of its own standard
deviations, how much of it the market and the sector explain, whether it came
at the open or during the session, and the range its own history implies for
the next few sessions.

Everything is causal: the volatility and betas a day is measured against are
estimated from the sessions before it, never from a sample that includes it
or anything after it. Descriptive only -- a large move is not a signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clean_float

EWMA_LAMBDA = 0.94  # RiskMetrics daily decay


def _ewma_sigma(returns: pd.Series) -> pd.Series:
    """Volatility known at each close, including that day's return."""
    variance = (returns ** 2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean()
    return np.sqrt(variance)


def decompose(stock: pd.Series, market: pd.Series, sector: pd.Series | None, *,
              beta_sessions: int, vol_sessions: int) -> dict | None:
    """Split the last session's return into market, sector and own parts.

    Betas: OLS of the stock on the market and on the sector's return over the
    market, over the ``beta_sessions`` before the last one. The own part's
    volatility is the residuals' over the ``vol_sessions`` before the last one.
    """
    frame = pd.concat({"r": stock, "m": market, "s": sector if sector is not None else market * np.nan},
                      axis=1).dropna(subset=["r", "m"])
    if len(frame) < vol_sessions + 2:
        return None
    today, past = frame.iloc[-1], frame.iloc[:-1].tail(beta_sessions)
    use_sector = sector is not None and past["s"].notna().all() and pd.notna(today["s"])
    columns = [np.ones(len(past)), past["m"].to_numpy()]
    if use_sector:
        columns.append((past["s"] - past["m"]).to_numpy())
    X = np.column_stack(columns)
    coef, *_ = np.linalg.lstsq(X, past["r"].to_numpy(), rcond=None)
    beta_m = float(coef[1])
    beta_s = float(coef[2]) if use_sector else 0.0
    residuals = past["r"] - X @ coef + coef[0]  # the intercept stays in the own part
    sigma_raw = float(past["r"].tail(vol_sessions).std())
    sigma_own = float(residuals.tail(vol_sessions).std())
    market_part = beta_m * today["m"]
    sector_part = beta_s * (today["s"] - today["m"]) if use_sector else 0.0
    own_part = today["r"] - market_part - sector_part
    return {
        "ret": today["r"], "market": market_part, "sector": sector_part, "own": own_part,
        "beta_market": beta_m, "beta_sector": beta_s if use_sector else None,
        "sigma": sigma_raw, "sigma_own": sigma_own,
        "z": today["r"] / sigma_raw if sigma_raw > 0 else None,
        "z_own": own_part / sigma_own if sigma_own > 0 else None,
    }


def forward_range(closes: pd.Series, *, horizon: int, history_sessions: int,
                  quantiles: tuple[float, ...]) -> dict | None:
    """The next ``horizon`` sessions' range, from the stock's own history.

    Filtered historical simulation: each past ``horizon``-session return is
    divided by the EWMA volatility known when it started, which removes the
    volatility regime and keeps the shape (fat tails, skew). Today's EWMA
    volatility scales those quantiles back. No normal distribution assumed.
    The past average is removed: a long rally would otherwise come back as
    an expected drift, and this is a range, not a forecast of direction.
    """
    closes = closes.dropna()
    returns = closes.pct_change()
    sigma = _ewma_sigma(returns.dropna())
    if len(sigma) < history_sessions // 2:
        return None
    ahead = closes.shift(-horizon) / closes - 1
    scaled = (ahead / (sigma * np.sqrt(horizon))).dropna().tail(history_sessions)
    if len(scaled) < 250:
        return None
    scaled = scaled - scaled.mean()
    now = float(sigma.iloc[-1]) * np.sqrt(horizon)
    last = float(closes.iloc[-1])
    out = {"horizon": horizon, "observations": int(len(scaled)), "sigma_pct": clean_float(100 * now, 2), "bands": []}
    for q in quantiles:
        move = float(scaled.quantile(q)) * now
        out["bands"].append({"q": q, "pct": clean_float(100 * move, 2), "price": clean_float(last * (1 + move), 2)})
    return out


def session_split(prices: pd.Series, opens: pd.Series) -> dict | None:
    """Close-to-open and open-to-close parts of the last session.

    On split-adjusted (not dividend-adjusted) prices, the same basis as the
    opens, so an ex-dividend morning shows the dividend in the gap.
    """
    frame = pd.concat({"p": prices, "o": opens}, axis=1).dropna()
    if len(frame) < 2 or frame.index[-1] != prices.dropna().index[-1]:
        return None
    previous, today = frame["p"].iloc[-2], frame.iloc[-1]
    if previous <= 0 or today["o"] <= 0:
        return None
    return {"gap": today["o"] / previous - 1, "intraday": today["p"] / today["o"] - 1}


def volume_ratio(volume: pd.Series, sessions: int) -> float | None:
    clean = volume.dropna()
    if len(clean) < sessions + 1:
        return None
    typical = clean.iloc[-sessions - 1:-1].median()
    return float(clean.iloc[-1] / typical) if typical > 0 else None
