"""The systematic anchor (compute.anchor) as its own artifact.

BRIEF shows today's reading and why; the decision log compares each logged
decision with what the anchor held that day. Its history is therefore kept
here rather than recomputed by each reader.
"""

from __future__ import annotations

import pandas as pd

from ..compute import anchor as A
from ..sources import yahoo
from ..util import SourceRecord, to_iso_date

SYMBOLS = ("SPY", "HG=F", "CL=F")
HISTORY_SESSIONS = 252 * 5


def _values(series: pd.Series, digits: int) -> list:
    return [None if pd.isna(v) else round(float(v), digits) for v in series]


def build(ctx) -> dict:
    closes = yahoo.fetch_closes(SYMBOLS, period="max")
    missing = [s for s in SYMBOLS if s not in closes.columns or closes[s].dropna().empty]
    if missing:
        raise RuntimeError(f"no closes for {', '.join(missing)}")
    if ctx.as_of:
        closes = closes.loc[: pd.Timestamp(ctx.as_of)]
    spy = closes["SPY"].dropna()
    result = A.anchor(spy, closes["HG=F"].dropna(), closes["CL=F"].dropna())
    whole = result["path"]
    path = whole.tail(HISTORY_SESSIONS)
    core = result["core"].reindex(path.index)
    gate = result["gate"].reindex(path.index)

    exposure = path["exposure"].round(3)
    changes = exposure[exposure.diff().fillna(0).abs() > 1e-9]
    ctx.log.add(SourceRecord("yahoo_anchor", "SPY, copper and oil closes for the systematic anchor",
                             "https://finance.yahoo.com", to_iso_date(spy.index[-1]), rows=len(spy)))
    return {
        "as_of": ctx.as_of,
        "rule": "quantamental-lab frozen v1 friend-plus-joint control (recession gate not ported: neutral)",
        "held": result["held"],
        "next": result["next"],
        "components": result["components"],
        "parameters": {
            "vol_target": A.VOL_TARGET, "vol_window": A.VOL_WINDOW, "trend_ma_window": A.TREND_MA_WINDOW,
            "trend_risk_off": A.TREND_RISK_OFF, "copper_z_window": A.COPPER_Z_WINDOW,
            "copper_bounds": [A.COPPER_LOWER, A.COPPER_UPPER], "copper_risk_off": A.COPPER_RISK_OFF,
            "ladder_thresholds": list(A.LADDER_THRESHOLDS), "ladder_multipliers": list(A.LADDER_MULTIPLIERS),
        },
        "history": {
            "dates": [d.strftime("%Y-%m-%d") for d in path.index],
            "exposure": _values(exposure, 3),
            "spy": _values(spy.reindex(path.index), 2),
            "overlay_drawdown": _values(path["drawdown"], 4),
            "vol_scaled": _values(core["vol_scaled"], 3),
            "trend_on": [bool(v) for v in core["trend_on"].fillna(False)],
            "copper_oil_cap": _values(gate["cap"], 2),
            "copper_oil_z": _values(gate["z"], 3),
        },
        "changes": [{"date": d.strftime("%Y-%m-%d"), "exposure": float(v)} for d, v in changes.tail(12).items()],
        # Every session since the copper series allows, daily: the RISK chart's
        # longer ranges and the Trade Desk scorecard both need the whole path.
        "full": {
            "dates": [d.strftime("%Y-%m-%d") for d in whole.index],
            "exposure": _values(whole["exposure"], 3),
            "spy": _values(spy.reindex(whole.index), 2),
        },
    }
