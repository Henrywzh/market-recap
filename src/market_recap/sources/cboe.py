"""Cboe's published index histories, VIX futures settlements and put/call ratios.

All three are files Cboe serves from its CDN without a key (probed 2026-09-26,
docs/risk_sources.md). The index histories are the official closes, but most
of these indices were launched years after the first row: the earlier part is
Cboe's own back-calculation from the option prices of the day. A reading from
that stretch is a back-calculated history, not a record of what was published
then, and the risk panel labels it so.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from io import StringIO
import json

import pandas as pd

from .. import cache
from .http import FetchError, get_text

NAMESPACE = "cboe"
INDEX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
VX_URL = "https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{expiry}.csv"
PUT_CALL_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{day}_daily_options"
HOME_URL = "https://www.cboe.com/us/indices/"


# Cboe adds a session to these files some hours after it ends -- after the
# 18:35 evening build on 2026-10-09 -- and a daily file is otherwise kept until
# the next rollover, so VIX stood a session behind all weekend. A cached file
# that ends before the build's session is asked for again, once per build.
_asked: set[str] = set()


def _daily_text(name: str, url: str, *, session: date | None, ends: Callable[[str], date | None],
                use_cache: bool, **http) -> str:
    path = cache.path_for(NAMESPACE, name, ".csv")
    from_cache = use_cache and cache.is_fresh(path, "daily_file")
    fetch = lambda: get_text(url, **http)  # noqa: E731
    text = cache.fetch_text(NAMESPACE, name, fetch, kind="daily_file", suffix=".csv", use_cache=use_cache)
    if not from_cache or session is None or name in _asked:
        _asked.add(name)
        return text
    _asked.add(name)
    last = ends(text)
    if last is not None and last >= session:
        return text
    try:
        return cache.fetch_text(NAMESPACE, name, fetch, kind="daily_file", suffix=".csv", use_cache=False)
    except Exception:  # noqa: BLE001 - the cached file stands, and the tile shows its date
        return text


def _last(index) -> date | None:
    return None if len(index) == 0 else pd.Timestamp(index.max()).date()


def fetch_index(symbol: str, *, use_cache: bool = True, session: date | None = None) -> pd.Series:
    """Daily closes of one Cboe index, oldest first.

    Most files are DATE,OPEN,HIGH,LOW,CLOSE; a few (VVIX, SKEW) are DATE,VALUE.
    ``session``: the build's session; a cached file ending before it is asked
    for again (once per build).
    """
    text = _daily_text(f"index-{symbol}", INDEX_URL.format(symbol=symbol), session=session,
                       ends=lambda t: _last(_parse_index(t, symbol).index), use_cache=use_cache, timeout=45.0)
    return _parse_index(text, symbol)


def _parse_index(text: str, symbol: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
    frame.columns = [str(c).strip().upper() for c in frame.columns]
    value = "CLOSE" if "CLOSE" in frame.columns else frame.columns[-1]
    series = pd.Series(
        pd.to_numeric(frame[value], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame["DATE"], format="%m/%d/%Y", errors="coerce"),
        name=symbol,
    )
    series = series[series.index.notna()].dropna()
    # A zero close is a placeholder row, not a reading.
    return series[series > 0].sort_index()


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def vx_expiry(year: int, month: int) -> date:
    """Monthly VIX future for ``month``: 30 days before the third Friday of the
    following month (a Wednesday)."""
    following = (year + 1, 1) if month == 12 else (year, month + 1)
    return _third_friday(*following) - timedelta(days=30)


def vx_expiries(today: date, count: int) -> list[date]:
    out: list[date] = []
    year, month = today.year, today.month
    while len(out) < count:
        expiry = vx_expiry(year, month)
        if expiry >= today:
            out.append(expiry)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def fetch_vx(expiry: date, *, use_cache: bool = True, session: date | None = None) -> pd.DataFrame:
    """Daily settlements of one monthly VIX future (trade_date, settle, open_interest).

    An exchange holiday moves an expiry a day earlier; the day before is tried
    when the scheduled date has no file. ``session`` as for
    :func:`fetch_index`, for a contract still trading.
    """
    last_error: Exception | None = None
    for candidate in (expiry, expiry - timedelta(days=1)):
        try:
            text = _daily_text(
                f"vx-{candidate.isoformat()}", VX_URL.format(expiry=candidate.isoformat()),
                session=session if session and candidate >= session else None,
                ends=lambda t, c=candidate: _last(_parse_vx(t, c)["trade_date"]),
                use_cache=use_cache, timeout=30.0, retries=1,
            )
        except FetchError as exc:
            last_error = exc
            continue
        return _parse_vx(text, candidate)
    raise last_error or FetchError(f"no VX file for {expiry}")


def _parse_vx(text: str, candidate: date) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text))
    frame = frame.rename(columns={"Trade Date": "trade_date", "Settle": "settle", "Open Interest": "open_interest"})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["settle"] = pd.to_numeric(frame["settle"], errors="coerce")
    frame["open_interest"] = pd.to_numeric(frame.get("open_interest"), errors="coerce")
    frame = frame.dropna(subset=["trade_date", "settle"])
    frame = frame[frame["settle"] > 0]
    frame["expiry"] = candidate.isoformat()
    return frame[["trade_date", "expiry", "settle", "open_interest"]].sort_values("trade_date")


def fetch_put_call(day: date, *, today: date, use_cache: bool = True) -> dict[str, float] | None:
    """Cboe's put/call ratios for one session, or None for a day with no file.

    A past session's file never changes, so it is kept for a year; today's is
    refetched each session.
    """
    kind = "daily_file" if day >= today else "archive"
    try:
        text = cache.fetch_text(
            NAMESPACE, f"putcall-{day.isoformat()}",
            lambda: get_text(PUT_CALL_URL.format(day=day.isoformat()), timeout=20.0, retries=1),
            kind=kind, suffix=".json", use_cache=use_cache,
        )
        payload = json.loads(text)
    except (FetchError, ValueError):
        return None
    out: dict[str, float] = {}
    for item in payload.get("ratios") or []:
        try:
            out[str(item["name"]).strip().upper()] = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
    return out or None
