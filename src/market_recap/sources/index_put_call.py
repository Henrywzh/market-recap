"""Index-option volume inputs, never substituted by ETF or total P/C.

Cboe reuses RISK's daily cache and makes no HTTP requests. The second adapter
accepts an authorized, normalized daily CSV only; it does not scrape OCC.
"""

from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path

import pandas as pd

from .. import cache
from ..config import REPO_ROOT


def ratio(puts, calls) -> float | None:
    try:
        p, c = float(puts), float(calls)
    except (TypeError, ValueError):
        return None
    return p / c if math.isfinite(p) and math.isfinite(c) and p >= 0 and c > 0 else None


def display_permitted(spec: dict) -> bool:
    """Publishing needs an explicit yes and a recorded permission reference."""
    return spec.get("publish_allowed") is True and bool(str(spec.get("permission_reference", "")).strip())


def cached_cboe(spec: dict, days: list[date]) -> pd.Series:
    values = {}
    for day in days:
        path = cache.path_for("cboe", f"putcall-{day.isoformat()}", ".json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get(spec["volume_key"], [])
            volume = [r for r in rows if r.get("name") == "VOLUME"]
            # Do not confuse open interest with volume, or accept duplicate rows.
            values[pd.Timestamp(day)] = ratio(volume[0].get("put"), volume[0].get("call")) if len(volume) == 1 else None
        except (OSError, ValueError, AttributeError, TypeError):
            values[pd.Timestamp(day)] = None
    return pd.Series(values, dtype=float)


def licensed_csv(spec: dict, *, as_of: date) -> pd.Series:
    """One daily row per underlying: date,underlying,put_volume,call_volume.

    Duplicates and invalid volumes fail the import; they are not silently
    aggregated. Future rows are excluded. The import must already include
    all roots/accounts/exchanges stated in the configured scope.
    """
    if not display_permitted(spec):
        raise PermissionError("Public display permission not recorded; no NDX data exported")
    path = Path(spec["csv_path"])
    path = path if path.is_absolute() else REPO_ROOT / path
    frame = pd.read_csv(path, dtype={"underlying": str})
    columns = {"date", "underlying", "put_volume", "call_volume"}
    if not columns.issubset(frame.columns):
        raise ValueError(f"Authorized CSV requires {sorted(columns)}")
    frame = frame[frame["underlying"] == spec["underlying"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError("Duplicate daily underlying rows in authorized CSV")
    frame = frame[frame["date"] <= pd.Timestamp(as_of)]
    values = [ratio(p, c) for p, c in zip(frame["put_volume"], frame["call_volume"])]
    if any(v is None for v in values):
        raise ValueError("Invalid put/call volume in authorized CSV")
    return pd.Series(values, index=pd.DatetimeIndex(frame["date"]), dtype=float).sort_index()
