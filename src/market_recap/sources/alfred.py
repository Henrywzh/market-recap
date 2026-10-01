"""ALFRED: when each FRED observation was first published, and as what.

The keyless CSV export (``fred.py``) is the current vintage: revised values,
and no record of when a month became public. ALFRED, FRED's vintage archive,
keeps both, behind a free API key: ``FRED_API_KEY`` from the environment (the
GitHub secret in CI), or locally a ``.config`` line ``FRED_API_KEY=...`` in
this repository or the sibling alternative-data checkout. Without a key the
callers keep their approximate release lags.

The key travels only in the request; every URL this module reports, and every
error it raises, has it removed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

import pandas as pd

from .. import cache
from .http import FetchError, get_text

NAMESPACE = "alfred"
API_URL = "https://api.stlouisfed.org/fred/series/observations"
PAGE_URL = "https://alfred.stlouisfed.org/series?seid={series_id}"
KEY_NAME = "FRED_API_KEY"
_KEY_IN_TEXT = re.compile(r"api_key=[^&\s'\"]+")
_REPO = Path(__file__).resolve().parents[3]


def _read_one(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == KEY_NAME:
            return value.strip().strip('"').strip("'")
    return ""


def api_key() -> str:
    value = os.environ.get(KEY_NAME, "").strip()
    if value:
        return value
    for path in (_REPO / ".config", _REPO.parent / "alternative-data" / ".config"):
        value = _read_one(path)
        if value:
            return value
    return ""


def available() -> bool:
    return bool(api_key())


def _get(params: dict) -> str:
    key = api_key()
    if not key:
        raise FetchError(f"ALFRED needs {KEY_NAME}")
    query = "&".join(f"{k}={v}" for k, v in {**params, "api_key": key, "file_type": "json"}.items())
    try:
        return get_text(f"{API_URL}?{query}", timeout=60.0, retries=1)
    except FetchError as exc:
        raise FetchError(_KEY_IN_TEXT.sub("api_key=REDACTED", str(exc)), not_found=exc.not_found) from None
    except Exception as exc:  # noqa: BLE001 -- whatever it is, its message may carry the URL
        raise FetchError(_KEY_IN_TEXT.sub("api_key=REDACTED", f"{type(exc).__name__}: {exc}")) from None


def _observations(series_id: str, params: dict, name: str) -> pd.DataFrame:
    rows: list[dict] = []
    offset = 0
    while True:
        text = cache.fetch_text(NAMESPACE, f"{name}-{offset}", lambda offset=offset: _get({**params, "series_id": series_id, "offset": offset}),
                                kind="macro_series", suffix=".json", compress=True)
        payload = json.loads(text)
        page = payload.get("observations") or []
        rows.extend(page)
        offset += len(page)
        if not page or offset >= int(payload.get("count") or 0):
            break
    frame = pd.DataFrame(rows, columns=["date", "value", "realtime_start", "realtime_end"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    for col in ("date", "realtime_start"):
        frame[col] = pd.to_datetime(frame[col])
    frame["realtime_end"] = pd.to_datetime(frame["realtime_end"].replace("9999-12-31", "2262-04-01"))
    return frame.dropna(subset=["value"]).reset_index(drop=True)


def first_releases(series_id: str, since: str = "2010-01-01") -> pd.DataFrame:
    """date, value as first published, released (the day it was first public).

    ALFRED's archive starts in the 1990s for most series; an observation older
    than that shows the archive's start as its "release", so ``since`` keeps to
    observations whose first vintage is real."""
    frame = _observations(series_id, {"output_type": 4, "observation_start": since, "realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}, f"{series_id}-first-{since}")
    return frame.rename(columns={"realtime_start": "released"})[["date", "value", "released"]]


def vintages(series_id: str, since: str = "2012-01-01") -> pd.DataFrame:
    """Every value each observation has had: date, value, realtime_start,
    realtime_end (inclusive). What was known on day D is the row whose
    window holds D."""
    return _observations(series_id, {"output_type": 1, "observation_start": since, "realtime_start": since,
                                     "realtime_end": "9999-12-31"}, f"{series_id}-all-{since}")


def page_url(series_id: str) -> str:
    return PAGE_URL.format(series_id=series_id)


def releases(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per release day: the newest observation it published, its
    first value and its predecessor's value as known that day -- the headline
    the release itself reported."""
    first = frame.sort_values(["date", "realtime_start"]).groupby("date", as_index=False).first()
    first = first[first["realtime_start"] > first["date"]]            # archive back-fill is not a release
    out = []
    for _, row in first.iterrows():
        day = row["realtime_start"]
        known = frame[(frame["realtime_start"] <= day) & (frame["realtime_end"] >= day) & (frame["date"] < row["date"])]
        prior = known.sort_values("date").iloc[-1] if not known.empty else None
        out.append({"date": row["date"], "released": day, "value": float(row["value"]),
                    "prior_date": None if prior is None else prior["date"],
                    "prior": None if prior is None else float(prior["value"])})
    return pd.DataFrame(out)



def as_published(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    """One row per observation, as its first release said it: date, released,
    value (the first print) and year_ago (the observation a year earlier, as
    known that same day) -- so a year-on-year change is the one the release
    reported, not one rebuilt from later revisions.

    ``freq``: 'weekly' looks 364 days back (the same weekday), anything else
    a calendar year. ``frame`` is ``vintages``' output."""
    frame = frame.sort_values(["date", "realtime_start"])
    first = frame.groupby("date", as_index=False).first()
    back = pd.Timedelta(days=364) if freq == "weekly" else pd.DateOffset(years=1)
    out = []
    for row in first.itertuples(index=False):
        day = row.realtime_start
        if day < row.date:
            continue
        target = row.date - back
        known = frame[(frame["date"] >= target - pd.Timedelta(days=3)) & (frame["date"] <= target + pd.Timedelta(days=3))
                      & (frame["realtime_start"] <= day) & (frame["realtime_end"] >= day)]
        year_ago = None
        if not known.empty:
            year_ago = float(known.loc[(known["date"] - target).abs().idxmin(), "value"])
        out.append({"date": row.date, "released": day, "value": float(row.value), "year_ago": year_ago})
    return pd.DataFrame(out, columns=["date", "released", "value", "year_ago"])
