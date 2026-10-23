"""RSI(6) oversold readings for TODAY's watch list of indices and sector ETFs.

Wilder's RSI, SMA-seeded, on closes. The TECHNICALS chart computes the same number in
``web/js/technicals-math.js``; ``tests/test_technicals_parity.py`` holds the two equal.

A description, not a signal: quantamental-lab docs/rsi6_below20_v1.md found that a
close below 20 is rarer than one below 30 but was not followed by clearly different
returns, and the further fall within 20 sessions was about the same.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Checked deepest first: the first line the reading is under names it.
LINES = ((20, "deeply oversold"), (30, "oversold"))


def wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder RSI with an SMA seed: the first value needs ``period`` price changes."""
    values = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) <= period:
        return pd.Series(out, index=close.index)
    changes = np.diff(values)
    gains, losses = np.clip(changes, 0, None), np.clip(-changes, 0, None)
    gain, loss = gains[:period].mean(), losses[:period].mean()

    def level(g: float, l: float) -> float:
        if l == 0:
            return 50.0 if g == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[period] = level(gain, loss)
    for i in range(period + 1, len(values)):
        gain = ((period - 1) * gain + gains[i - 1]) / period
        loss = ((period - 1) * loss + losses[i - 1]) / period
        out[i] = level(gain, loss)
    return pd.Series(out, index=close.index)


def wilder_state(close: pd.Series, period: int) -> tuple[float, float] | None:
    """The smoothed average gain and loss after the last close: with tomorrow's
    price, ``((period - 1) * gain + up) / period`` gives tomorrow's RSI -- which
    is how TODAY's page reads the RSI from a live quote. None when not formed."""
    values = pd.to_numeric(close.dropna(), errors="coerce").to_numpy(dtype=float)
    if len(values) <= period:
        return None
    changes = np.diff(values)
    gains, losses = np.clip(changes, 0, None), np.clip(-changes, 0, None)
    gain, loss = gains[:period].mean(), losses[:period].mean()
    for i in range(period + 1, len(values)):
        gain = ((period - 1) * gain + gains[i - 1]) / period
        loss = ((period - 1) * loss + losses[i - 1]) / period
    return float(gain), float(loss)


def reading(close: pd.Series, period: int, lines=LINES) -> dict | None:
    """Today's RSI and, when under a line, which one and for how many closes in a row.

    ``days`` counts consecutive closes under the deepest line the latest close is under;
    ``days_30`` counts them under the shallowest. None when the RSI is not formed.
    """
    rsi = wilder_rsi(close.dropna(), period).dropna()
    if rsi.empty:
        return None
    now = float(rsi.iloc[-1])
    out = {"rsi": now, "date": rsi.index[-1].strftime("%Y-%m-%d"), "line": None, "verdict": None, "days": 0}
    for line, verdict in sorted(lines):
        if now < line:
            out.update(line=line, verdict=verdict, days=run_below(rsi, line))
            break
    shallow = max(line for line, _ in lines)
    out["days_shallow"] = run_below(rsi, shallow)
    return out


def run_below(rsi: pd.Series, line: float) -> int:
    below = (rsi < line).to_numpy()[::-1]
    return int(np.argmin(below)) if not below.all() else int(len(below))
