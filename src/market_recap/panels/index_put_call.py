"""Positioning's index-specific put/call component and explicit coverage."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..compute.catalysts import sessions
from ..config import PERIOD_TRADING_DAYS
from ..sources import index_put_call as source
from ..util import SourceRecord, clean_float

PERMISSION_REASON = "public display permission not recorded"


def readings(raw: pd.Series, days: list[date], windows: list[str]) -> dict:
    """Keep missing sessions in rolling means; never bridge a hole.

    The artifact carries daily values and coverage only. The page computes
    latest, median and percentile for the range it shows, so they cannot
    disagree with the chart.
    """
    series = raw.reindex(pd.DatetimeIndex(days))
    series = series.where(series.ge(0) & series.lt(float("inf")))
    out = {}
    for label in windows:
        n = PERIOD_TRADING_DAYS[label]
        if n is None or n < 1:
            raise ValueError(f"Not a fixed trading-session window: {label}")
        smooth = series.rolling(n, min_periods=n).mean()
        out[label] = {
            "sessions": n,
            "values": [clean_float(v, 4) for v in smooth],
            "observations": int(smooth.notna().sum()),
        }
    valid = series.dropna()
    return {
        "dates": [d.isoformat() for d in days], "windows": out,
        "coverage": {"observed": int(len(valid)), "expected": len(days),
                     "missing": int(series.isna().sum()),
                     "first": valid.index[0].date().isoformat() if len(valid) else None,
                     "last": valid.index[-1].date().isoformat() if len(valid) else None},
    }


def build_component(as_of: str, settings: dict, log=None) -> dict:
    """Index put/call rows for POSITIONING.

    Cboe series read the daily files RISK caches. POSITIONING does not declare
    RISK as an input, so a POSITIONING-only build uses whatever RISK last cached
    and missing sessions stay blank. A licensed series without recorded display
    permission is listed under "disabled" with its reason: no row, no source record.
    """
    end = date.fromisoformat(as_of)
    count = int(settings.get("sessions", 400))
    if count < 1:
        raise ValueError("Index P/C sessions must be positive")
    days = sessions(end - timedelta(days=count * 2 + 30), end)[-count:]
    windows = settings["windows"]
    if settings["default_window"] not in windows:
        raise ValueError("Index P/C default window must be offered")
    series, disabled = [], []
    for spec in settings["series"]:
        if spec.get("provider") == "licensed_csv" and not source.display_permitted(spec):
            disabled.append({"key": spec["key"], "label": spec["label"], "reason": PERMISSION_REASON})
            continue
        note, status = None, "ok"
        try:
            if spec["provider"] == "cboe_cache":
                raw = source.cached_cboe(spec, days)
            elif spec["provider"] == "licensed_csv":
                raw = source.licensed_csv(spec, as_of=end)
            else:
                raise ValueError(f"Unknown P/C provider: {spec['provider']}")
        except Exception as exc:
            raw, note, status = pd.Series(dtype=float), str(exc)[:300], "unavailable"
        result = readings(raw, days, windows)
        if not note and result["coverage"]["missing"]:
            status = "partial"
            note = "Missing sessions stay blank; Cboe uses the daily cache collected by RISK."
        row = {"key": spec["key"], "label": spec["label"], "source_label": spec["source_label"],
               "source_url": spec["source_url"], "scope": spec["scope"],
               "status": status, "note": note, **result}
        series.append(row)
        if log is not None:
            log.add(SourceRecord(f"index_put_call_{spec['key']}", spec["source_label"], spec["source_url"],
                                 result["coverage"]["last"], rows=result["coverage"]["observed"],
                                 status="partial" if status != "ok" else "ok", error=note))
    return {"as_of": as_of, "default_window": settings["default_window"], "series": series, "disabled": disabled,
            "method": "Daily traded put contracts / call contracts, not open interest. Rolling windows are arithmetic means of daily ratios over consecutive NYSE sessions (1W=5, 1M=21); missing sessions break the window. Latest, median and percentile are computed by the page for the selected range from these daily values, not a shared history or a forecast probability. Volume does not identify buyers, opening positions or market-maker exposure."}
