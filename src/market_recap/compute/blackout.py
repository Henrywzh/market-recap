"""Finite differences of the calendar-day blackout proxy, never actual flow."""

import pandas as pd

from ..util import clean_float


def calendar_momentum(dates, shares, as_of, windows) -> dict:
    """Backward-looking velocity/acceleration at every date, plus a separately
    labelled forward schedule change. Missing days/values invalidate a window.
    Velocity = (B[t]-B[t-h])/h; acceleration = (B[t]-2B[t-h]+B[t-2h])/h².
    Units are percentage points/calendar-day and pp/calendar-day².
    """
    index = pd.to_datetime(dates)
    if len(dates) != len(shares) or index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("blackout dates must be unique, ascending and aligned with shares")
    if not len(index):
        return {"windows": [], "default_window": None, "as_of": as_of}
    curve = pd.Series(shares, index=index, dtype=float).replace([float("inf"), -float("inf")], float("nan")).asfreq("D")
    day = pd.Timestamp(as_of)
    variants = []
    for h in windows:
        if not isinstance(h, int) or isinstance(h, bool) or h < 1:
            raise ValueError("blackout difference windows must be positive integer calendar days")
        valid = curve.rolling(h + 1).count().eq(h + 1)
        delta = (curve - curve.shift(h)).where(valid)
        velocity = delta / h
        acceleration = ((curve - 2 * curve.shift(h) + curve.shift(2 * h)) / h**2).where(
            curve.rolling(2 * h + 1).count().eq(2 * h + 1))
        future_day = day + pd.Timedelta(days=h)
        future_window = curve.loc[day:future_day]
        forward = (curve.get(future_day) - curve.get(day)) if (
            len(future_window) == h + 1 and future_window.notna().all()) else None
        variants.append({
            "key": f"{h}D", "calendar_days": h,
            "delta_pp": [clean_float(v, 4) for v in delta.reindex(index)],
            "velocity_pp_per_day": [clean_float(v, 4) for v in velocity.reindex(index)],
            "acceleration_pp_per_day2": [clean_float(v, 4) for v in acceleration.reindex(index)],
            "now_delta_pp": clean_float(delta.get(day), 4),
            "now_velocity_pp_per_day": clean_float(velocity.get(day), 4),
            "now_acceleration_pp_per_day2": clean_float(acceleration.get(day), 4),
            "ahead_delta_pp": clean_float(forward, 4),
        })
    return {"as_of": as_of, "windows": variants, "default_window": variants[-1]["key"] if variants else None}
