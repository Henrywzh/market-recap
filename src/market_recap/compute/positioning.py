"""Who is forced to trade: a trend-follower proxy and short interest.

Trend followers (CTAs, vol-control and risk-parity books that run trend
rules) buy or sell on rules, not views, so the levels at which their rules
flip are knowable in advance. Their exact models are private; this is the
textbook stand-in: the sign of the index's return over several lookbacks,
averaged. +1 means every lookback is up (fully long), -1 every lookback
down. A lookback's sign flips tomorrow if tomorrow's close crosses the close
it will be compared with -- the close ``n - 1`` sessions before today -- so
each flip level is a known price, not a forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACKS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}


def trend_score(close: pd.Series, lookbacks: dict[str, int] = LOOKBACKS) -> pd.Series:
    """Mean sign of the return over each lookback, in [-1, 1]."""
    close = close.dropna()
    signs = pd.concat({label: np.sign(close / close.shift(n) - 1) for label, n in lookbacks.items()}, axis=1)
    return signs.dropna().mean(axis=1)


def flip_levels(close: pd.Series, lookbacks: dict[str, int] = LOOKBACKS) -> list[dict]:
    """For each lookback: today's return and sign, and the close tomorrow must
    cross to flip it. Tomorrow's n-session return compares with the close n
    sessions before tomorrow, which is ``close.iloc[-n]`` today."""
    close = close.dropna()
    last = float(close.iloc[-1])
    rows = []
    for label, n in lookbacks.items():
        if len(close) <= n:
            continue
        today_base = float(close.iloc[-1 - n])
        tomorrow_base = float(close.iloc[-n])
        ret = last / today_base - 1
        rows.append({
            "lookback": label,
            "sessions": n,
            "return_pct": ret * 100,
            "signal": 1 if ret > 0 else -1 if ret < 0 else 0,
            "flip_level": tomorrow_base,
            "distance_pct": (tomorrow_base / last - 1) * 100,
        })
    return rows


def ma_levels(close: pd.Series, windows=(50, 100, 200)) -> list[dict]:
    """The moving averages trend rules also watch, and the distance to each."""
    close = close.dropna()
    last = float(close.iloc[-1])
    out = []
    for w in windows:
        if len(close) < w:
            continue
        level = float(close.tail(w).mean())
        out.append({"window": w, "level": level, "distance_pct": (level / last - 1) * 100, "above": last > level})
    return out


def label(score: float | None) -> str | None:
    """LONG / SHORT when three of four lookbacks agree, else MIXED."""
    if score is None or not np.isfinite(score):
        return None
    return "LONG" if score >= 0.5 else "SHORT" if score <= -0.5 else "MIXED"


# --- vol-scaled model position ------------------------------------------------
# The trend book scales its exposure to a target volatility, so a calm market
# lets it lever up even when the trend has not changed. These constants are the
# textbook stand-in, not any fund's settings.
TARGET_VOL = 0.15      # annualised volatility the trend book scales its position to
LEVERAGE_CAP = 2.0     # leverage at which the model reads 100, its maximum long
CTA_VOL_WINDOW = 60    # sessions of daily returns behind the trend book's volatility
VC_VOL_WINDOW = 20     # shorter window for the volatility-control book
VC_TARGET = 0.10       # annualised volatility the volatility-control book targets
VC_CAP = 1.5           # its exposure ceiling, as a multiple of notional
SCENARIO_SD_WINDOW = 20  # sessions behind the daily sigma used for scenarios

# Assumed notional range (low, high, $bn) of trend-follower futures at a full
# model long. A round-number range in line with published estimates; not observed.
MAX_NOTIONAL_BN = {"^GSPC": (80, 160), "^NDX": (20, 60)}


def realised_vol(close: pd.Series, window: int) -> pd.Series:
    """Annualised stdev of daily log returns over the trailing ``window`` sessions."""
    returns = np.log(close.dropna()).diff()
    return returns.rolling(window).std() * np.sqrt(252)


def trend_strength(close: pd.Series, lookbacks: dict[str, int] = LOOKBACKS) -> pd.Series:
    """Mean of each lookback's return in its own volatility units, each clipped to [-1, 1].

    A continuous signal, as trend books run: a lookback one sigma up (the
    60-session daily sigma scaled by the square root of its length) is fully
    long, and a lookback near zero is near flat, so crossing a flip level
    moves the position a little, not all at once.
    """
    close = close.dropna()
    sigma = np.log(close).diff().rolling(CTA_VOL_WINDOW).std()
    parts = {label: (np.log(close / close.shift(n)) / (sigma * np.sqrt(n))).clip(-1, 1)
             for label, n in lookbacks.items()}
    return pd.concat(parts, axis=1).dropna().mean(axis=1)


def model_position(close: pd.Series) -> pd.Series:
    """Trend strength scaled to the volatility target, in [-100, 100]: % of the model's maximum long."""
    close = close.dropna()
    scale = (TARGET_VOL / realised_vol(close, CTA_VOL_WINDOW)).clip(upper=LEVERAGE_CAP)
    return (100 * trend_strength(close) * scale / LEVERAGE_CAP).dropna()


def vol_control_exposure(close: pd.Series) -> pd.Series:
    """Long-only volatility-control exposure in [0, 100]: buys when volatility falls, whatever the trend."""
    close = close.dropna()
    scale = (VC_TARGET / realised_vol(close, VC_VOL_WINDOW)).clip(upper=VC_CAP)
    return (100 * scale / VC_CAP).dropna()


def scenario_flows(close: pd.Series, *, sessions=(1, 5), moves=(-2, -1, 0, 1, 2)) -> list[dict]:
    """Model position and volatility-control change after an assumed price path.

    Each path steps the close by ``move`` daily sigmas per session (sigma from
    the last 20 daily log returns; 0 leaves the price unchanged). It captures
    both channels: a sign flip, and the volatility the path itself leaves behind.
    """
    close = close.dropna()
    sd = float(np.log(close).diff().tail(SCENARIO_SD_WINDOW).std())
    now = float(close.iloc[-1])
    position_now = float(model_position(close).iloc[-1])
    vc_now = float(vol_control_exposure(close).iloc[-1])
    rows = []
    for n in sessions:
        for m in moves:
            path = now * np.exp(m * sd * np.arange(1, n + 1))
            extended = pd.Series(np.concatenate([close.to_numpy(), path]))
            position = float(model_position(extended).iloc[-1])
            vc = float(vol_control_exposure(extended).iloc[-1])
            rows.append({
                "sessions": n, "move_sd": m,
                "move_pct": float(100 * (path[-1] / now - 1)),
                "close": float(path[-1]),
                "position": position, "position_change": position - position_now,
                "vc_change": vc - vc_now,
            })
    return rows


def room(position: float | None) -> dict:
    """Distance to the model's maximum long and maximum short, in position points."""
    if position is None or not np.isfinite(position):
        return {"to_max_long": None, "to_max_short": None}
    return {"to_max_long": 100 - position, "to_max_short": position + 100}


def flow_range_bn(position_change: float | None, symbol: str) -> tuple[float | None, float | None]:
    """Dollar flow implied by a position change, under the assumed notional range."""
    if position_change is None or not np.isfinite(position_change) or symbol not in MAX_NOTIONAL_BN:
        return None, None
    low, high = MAX_NOTIONAL_BN[symbol]
    return position_change / 100 * low, position_change / 100 * high


# --- checks against listed prices ----------------------------------------------

def implied_equity_beta(etf: pd.Series, factors: pd.DataFrame, window: int = 63) -> pd.Series:
    """Rolling OLS of the ETF's daily returns on the factor returns; the SPY coefficient.

    Each window needs at least 90% of its rows with every series present.
    Intercept included; coefficients are returned at the window's last date.
    """
    frame = pd.concat([etf.rename("etf"), factors], axis=1).sort_index()
    values = frame.to_numpy(dtype=float)
    k = list(factors.columns).index("SPY")
    out = np.full(len(frame), np.nan)
    need = 0.9 * window
    for end in range(window - 1, len(frame)):
        block = values[end - window + 1: end + 1]
        ok = np.isfinite(block).all(axis=1)
        if ok.sum() < need:
            continue
        y = block[ok, 0]
        design = np.column_stack([np.ones(ok.sum()), block[ok, 1:]])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        out[end] = coef[1 + k]
    return pd.Series(out, index=frame.index).dropna()


def change_correlation(a: pd.Series, b: pd.Series, *, step: int = 21, min_samples: int = 24) -> float | None:
    """Correlation of the ``step``-session changes of two series, sampled every ``step`` sessions over their overlap."""
    both = pd.concat([a, b], axis=1, join="inner").dropna().iloc[::step]
    changes = both.diff().dropna()
    if len(changes) < min_samples:
        return None
    corr = changes.iloc[:, 0].corr(changes.iloc[:, 1])
    return float(corr) if np.isfinite(corr) else None


def level_correlation(a: pd.Series, b: pd.Series, *, min_samples: int = 252) -> float | None:
    """Correlation of two series' levels over their overlap; None below ``min_samples`` shared sessions."""
    both = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(both) < min_samples:
        return None
    corr = both.iloc[:, 0].corr(both.iloc[:, 1])
    return float(corr) if np.isfinite(corr) else None
