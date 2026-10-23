"""Hedge-fund leverage and equity exposure from quarterly Form PF aggregates.

Every input is a quarter-end series from the OFR dataset. Quarters are
compared by calendar quarter, not by day count: Form PF quarter ends are not
evenly spaced in days (March 31 against June 30), so "three months earlier"
means the previous quarter, and "a year earlier" means four quarters back.

A figure that cannot be formed is None. A missing quarter never becomes a
zero, and a change against a zero base has no percentage.
"""

from __future__ import annotations

import pandas as pd

# A percentile of fewer observations says little about how unusual a value is.
MIN_HISTORY = 8


def points(dataset: dict, mnemonic: str) -> pd.Series:
    """One series from the OFR dataset as a sorted float Series on quarter-end dates.

    OFR withholds a figure where a filer could be identified; those quarters are
    dropped, not read as zero.
    """
    entry = dataset.get("timeseries", {}).get(mnemonic)
    if entry is None:
        raise KeyError(f"OFR dataset has no series {mnemonic}")
    rows = [(d, v) for d, v in (entry.get("timeseries", {}).get("aggregation") or []) if v is not None]
    index = pd.to_datetime([d for d, _ in rows])
    return pd.Series([float(v) for _, v in rows], index=index, dtype=float).sort_index()


def metadata(dataset: dict, mnemonic: str) -> dict:
    """OFR's own description of a series: its name, unit and last update."""
    meta = dataset["timeseries"][mnemonic]["metadata"]
    return {
        "name": meta["description"]["name"],
        "unit": meta["unit"]["name"],
        "last_update": meta["schedule"]["last_update"],
    }


def ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Quarter-by-quarter ratio over the quarters both series share. A zero denominator is dropped."""
    joined = pd.concat([numerator, denominator], axis=1, join="inner").dropna()
    joined = joined[joined.iloc[:, 1] != 0]
    return (joined.iloc[:, 0] / joined.iloc[:, 1]).rename(None)


def net_share_of_base(long: pd.Series, short: pd.Series, base: pd.Series) -> pd.Series:
    """(long - short) as a percentage of a base such as net assets, over shared quarters."""
    joined = pd.concat([long, short, base], axis=1, join="inner").dropna()
    joined = joined[joined.iloc[:, 2] != 0]
    return (100.0 * (joined.iloc[:, 0] - joined.iloc[:, 1]) / joined.iloc[:, 2]).rename(None)


def _lagged(series: pd.Series, quarters: int) -> float | None:
    """The value `quarters` calendar quarters before the latest one, or None if that quarter is absent."""
    if series.empty:
        return None
    periods = series.index.to_period("Q")
    hit = series[periods == periods[-1] - quarters]
    return None if hit.empty else float(hit.iloc[0])


def change(series: pd.Series, quarters: int, *, relative: bool) -> tuple[float | None, float | None]:
    """(absolute change, percentage change) of the latest value against `quarters` quarters earlier.

    The percentage is None for a series in percent units (a percentage of a
    percentage is not a useful reading) and when the base is zero or absent.
    """
    if series.empty:
        return None, None
    latest = float(series.iloc[-1])
    base = _lagged(series, quarters)
    if base is None:
        return None, None
    absolute = latest - base
    if not relative or base == 0:
        return absolute, None
    return absolute, 100.0 * (latest / base - 1.0)


def percentile(series: pd.Series) -> float | None:
    """Where the latest value sits in the series' own history, 0 to 100 (share of quarters at or below it)."""
    if len(series) < MIN_HISTORY:
        return None
    return 100.0 * float((series <= series.iloc[-1]).mean())


def latest_row(series: pd.Series, *, relative: bool) -> dict:
    """The newest quarter with its q/q and y/y changes and its percentile."""
    if series.empty:
        return {"period": None, "value": None, "q_change": None, "q_change_pct": None,
                "y_change": None, "y_change_pct": None, "percentile": None, "n_obs": 0}
    q_abs, q_pct = change(series, 1, relative=relative)
    y_abs, y_pct = change(series, 4, relative=relative)
    return {
        "period": series.index[-1].strftime("%Y-%m-%d"),
        "value": float(series.iloc[-1]),
        "q_change": q_abs,
        "q_change_pct": q_pct,
        "y_change": y_abs,
        "y_change_pct": y_pct,
        "percentile": percentile(series),
        "n_obs": int(len(series)),
    }
