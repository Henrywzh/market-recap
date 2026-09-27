"""The systematic anchor: the frozen v1 exposure control, replayed here.

A port of quantamental-lab's frozen v1 "friend-plus-joint" control
(src/medium_horizon/risk_overlay_v1.py and regime_risk_overlay_v1.py,
documented in docs/risk_layer_decision_v1.md there). It is re-implemented,
not imported: this site must not depend on that repository at run time. The
parameters are the frozen ones and are not configurable here -- a different
rule would be a different anchor, not this one.

    friend core   target = min(1, 12% / realised vol(63d, >= 42 obs)),
                  capped at 0.5 while SPY is not above its 200-day average,
                  lagged one session
    copper/oil    log(copper / oil) z-score against the prior 252 sessions,
                  with hysteresis: below -0.25 turns it risk-off (cap 0.5),
                  above +0.25 back on; lagged one session
    recession     quantamental-lab's out-of-sample recession probability.
                  NOT PORTED: it is that repository's model output. Treated
                  as neutral, which is the frozen rule's own policy for a
                  missing input (combine_regime_caps, missing_policy="neutral").
    ladder        the overlay's own drawdown steps exposure down:
                  deeper than -8% -> x0.6, deeper than -12% -> x0.3

The result is the anchor for BRIEF and the decision log: the exposure the
rule would hold, and why. It is a reference, not a recommendation.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

VOL_TARGET = 0.12
VOL_WINDOW = 63
VOL_MIN_OBSERVATIONS = 42
TREND_MA_WINDOW = 200
TREND_RISK_OFF = 0.50
MAX_EXPOSURE = 1.0
SIGNAL_LAG = 1
COPPER_Z_WINDOW = 252
COPPER_UPPER = 0.25
COPPER_LOWER = -0.25
COPPER_RISK_OFF = 0.50
COPPER_LAG = 1
LADDER_THRESHOLDS = (-0.08, -0.12)
LADDER_MULTIPLIERS = (1.0, 0.60, 0.30)


def realised_volatility(returns: pd.Series) -> pd.Series:
    return returns.rolling(VOL_WINDOW, min_periods=VOL_MIN_OBSERVATIONS).std(ddof=1) * math.sqrt(252)


def trend_is_risk_on(close: pd.Series) -> pd.Series:
    average = close.rolling(TREND_MA_WINDOW, min_periods=TREND_MA_WINDOW).mean()
    return (close > average).where(average.notna(), other=False)


def friend_core(close: pd.Series, *, lag: int = SIGNAL_LAG) -> pd.DataFrame:
    """Vol-targeted, trend-gated exposure; ``lag`` = 0 gives the unlagged target."""
    returns = close.pct_change(fill_method=None).fillna(0.0)
    vol = realised_volatility(returns)
    scaled = (VOL_TARGET / vol.where(vol > 0)).clip(upper=MAX_EXPOSURE)
    on = trend_is_risk_on(close)
    gated = scaled.where(on, other=scaled.clip(upper=TREND_RISK_OFF))
    return pd.DataFrame({
        "vol": vol,
        "vol_scaled": scaled,
        "trend_on": on,
        "target": gated.shift(lag).fillna(0.0).clip(0.0, MAX_EXPOSURE),
    })


def copper_oil(copper: pd.Series, oil: pd.Series, index: pd.DatetimeIndex, *, lag: int = COPPER_LAG) -> pd.DataFrame:
    """The copper/oil gate with hysteresis, aligned to ``index``."""
    prices = pd.concat([copper.where(copper > 0), oil.where(oil > 0)], axis=1, keys=["copper", "oil"]).dropna().sort_index()
    log_ratio = np.log(prices["copper"] / prices["oil"])
    mean = log_ratio.rolling(COPPER_Z_WINDOW, min_periods=COPPER_Z_WINDOW).mean().shift(1)
    std = log_ratio.rolling(COPPER_Z_WINDOW, min_periods=COPPER_Z_WINDOW).std(ddof=1).shift(1)
    z = ((log_ratio - mean) / std).replace([np.inf, -np.inf], np.nan)
    states = np.full(len(z), np.nan)
    current = None
    for i, value in enumerate(z.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        if current is None:
            current = 1.0
        if value > COPPER_UPPER:
            current = 1.0
        elif value < COPPER_LOWER:
            current = 0.0
        states[i] = current
    state = pd.Series(states, index=z.index).reindex(index, method="ffill").shift(lag)
    cap = pd.Series(np.where(state.notna(), np.where(state > 0.5, 1.0, COPPER_RISK_OFF), np.nan), index=index)
    return pd.DataFrame({"z": z.reindex(index, method="ffill"), "state": state, "cap": cap})


def ladder_multiplier(drawdown: float) -> float:
    for position, threshold in enumerate(LADDER_THRESHOLDS):
        if drawdown > threshold:
            return LADDER_MULTIPLIERS[position]
    return LADDER_MULTIPLIERS[-1]


def simulate(close: pd.Series, signal: pd.Series) -> pd.DataFrame:
    """The path-dependent overlay: exposure, NAV and drawdown each session,
    with the ladder read from the prior close (no cost, no deadband, zero
    cash return -- as the frozen atlas replays it)."""
    returns = close.pct_change(fill_method=None).fillna(0.0).to_numpy()
    target = signal.reindex(close.index).fillna(0.0).to_numpy()
    nav, peak = 1.0, 1.0
    rows = np.empty((len(close), 4))
    for i in range(len(close)):
        multiplier = ladder_multiplier(nav / peak - 1.0)
        exposure = min(MAX_EXPOSURE, target[i] * multiplier)
        nav *= 1.0 + exposure * returns[i]
        peak = max(peak, nav)
        rows[i] = (exposure, multiplier, nav, nav / peak - 1.0)
    return pd.DataFrame(rows, index=close.index, columns=["exposure", "ladder", "nav", "drawdown"])


def anchor(close: pd.Series, copper: pd.Series, oil: pd.Series) -> dict:
    """Today's anchor and its history.

    ``held`` is the exposure the rule holds in the last session (signals
    lagged, as traded). ``next`` is the target for the next session from
    today's close: the same rule one session on.
    """
    close = close.dropna().sort_index()
    core = friend_core(close)
    gate = copper_oil(copper, oil, close.index)
    signal = core["target"] * gate["cap"].fillna(1.0)
    path = simulate(close, signal)

    # Next session: unlagged core and gate from today's close, ladder from today's NAV.
    core_now = friend_core(close, lag=0).iloc[-1]
    gate_now = copper_oil(copper, oil, close.index, lag=0).iloc[-1]
    gate_cap = gate_now["cap"] if pd.notna(gate_now["cap"]) else 1.0
    ladder_now = ladder_multiplier(float(path["drawdown"].iloc[-1]))
    next_exposure = min(MAX_EXPOSURE, float(core_now["target"]) * gate_cap * ladder_now)

    last = path.iloc[-1]
    return {
        "held": round(float(last["exposure"]), 3),
        "next": round(next_exposure, 3),
        "components": {
            "realised_vol": round(float(core_now["vol"]), 4) if pd.notna(core_now["vol"]) else None,
            "vol_scaled": round(float(core_now["vol_scaled"]), 3) if pd.notna(core_now["vol_scaled"]) else None,
            "trend_on": bool(core_now["trend_on"]),
            "copper_oil_z": round(float(gate_now["z"]), 3) if pd.notna(gate_now["z"]) else None,
            "copper_oil_on": None if pd.isna(gate_now["state"]) else bool(gate_now["state"] > 0.5),
            "copper_oil_cap": round(float(gate_cap), 2),
            "overlay_drawdown": round(float(last["drawdown"]), 4),
            "ladder": ladder_now,
            "recession_cap": None,
        },
        "path": path,
        "signal": signal,
        "core": core,
        "gate": gate,
    }
