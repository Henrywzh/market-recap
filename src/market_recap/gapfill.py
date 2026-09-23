"""Check Yahoo's recent sessions against published closes, and fill what fails.

Yahoo has got a session wrong three ways: served it as NaN, dropped the row
outright, and -- on 2026-09-22 -- served dividend-adjusted closes that were
not the closes at all (a stale intraday snapshot: RCL +1.6% on a day it
closed -6.1%, advancers 291 against a true 248) while leaving the split-only
closes blank. The first two leave an empty row once ``mark_missing_sessions``
has run. The third looks complete and passed every check, so it is found by
comparing against a second publisher:

* iShares' IVV holdings file prices every S&P 500 member at the close of the
  day it is dated -- the prices the fund's NAV is struck at. When that day is
  in the frame, Yahoo's closes for it are compared name by name; a median
  disagreement beyond ``VERIFY_TOLERANCE`` marks the whole session suspect,
  and it is rebuilt like a missing one.

Rebuilding uses the same file for S&P 500 members, Nasdaq's historical
quotes for any other stock or ETF, and FRED's S&P 500 and Nasdaq-100 series
for the indices. All are closes as traded, not dividend-adjusted: a filled
close is put on the adjusted basis with that symbol's adjustment factor on
the session before (adjusted close over split-only close). What cannot be
filled stays empty, and the session checks still see it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .compute.xray import ticker_key
from .config import SESSION_COVERAGE_THRESHOLD
from .sources import fred, ishares, nasdaq

HOLDINGS_FUND = "IVV"
# Rows near the end that are checked; matches mark_missing_sessions.
LOOKBACK = 5
# Median disagreement with the issuer's closes, in percent, above which a
# session is not taken as settled closes. The same close agrees to the cent;
# an ex-dividend basis difference moves one name, not the median.
VERIFY_TOLERANCE = 0.1
MIN_VERIFY_NAMES = 100
# Per frame: a gap needing more lookups than this is a source outage, and
# five hundred single-symbol requests to an unofficial endpoint is not a fill.
MAX_NASDAQ_LOOKUPS = 150
# Index closes: FRED first (official daily series), Nasdaq where it lists one.
FRED_INDEX = {"^GSPC": "SP500", "^NDX": "NASDAQ100"}
NASDAQ_INDEX = {"^NDX": "NDX"}


def gaps(frame: pd.DataFrame) -> list[pd.Timestamp]:
    """Recent sessions, before the last, with too few prices to be a session."""
    if frame.empty:
        return []
    tail = frame.index[-(LOOKBACK + 1):-1]
    return [day for day in tail if frame.loc[day].notna().mean() < SESSION_COVERAGE_THRESHOLD]


def _holdings(use_cache: bool) -> tuple[pd.Timestamp | None, dict[str, float]]:
    """(date, {ticker key: close}) from the IVV holdings file."""
    try:
        frame, as_of, _ = ishares.fetch_holdings(HOLDINGS_FUND, use_cache=use_cache)
    except Exception:
        return None, {}
    if not as_of or "price" not in frame:
        return None, {}
    equities = frame[frame["asset_class"].eq("Equity")].dropna(subset=["price"])
    return pd.Timestamp(as_of), {ticker_key(t): float(p) for t, p in zip(equities["ticker"], equities["price"])}


def _factor(frame: pd.DataFrame, raw: pd.DataFrame | None, day: pd.Timestamp, symbol: str) -> float | None:
    """The adjusted/split-only ratio on the session before ``day``."""
    if raw is None or symbol not in raw.columns:
        return None
    position = frame.index.get_loc(day)
    if position == 0:
        return None
    previous = frame.index[position - 1]
    adjusted = frame.at[previous, symbol]
    split_only = raw.at[previous, symbol] if previous in raw.index else np.nan
    if pd.isna(adjusted) or pd.isna(split_only) or not split_only:
        return None
    return float(adjusted) / float(split_only)


def verify(frame: pd.DataFrame, raw: pd.DataFrame | None, *, use_cache: bool = True) -> dict | None:
    """Compare the frame's session on the IVV holdings date with IVV's closes.

    Returns {"date", "names", "median_deviation_pct", "suspect"}, or None when
    the holdings date is not a row with prices to compare.
    """
    day, closes = _holdings(use_cache)
    if day is None or day not in frame.index or day not in frame.index[-(LOOKBACK + 1):]:
        return None
    deviations = []
    for symbol in frame.columns:
        close = closes.get(ticker_key(symbol))
        factor = _factor(frame, raw, day, symbol)
        value = frame.at[day, symbol]
        if close and factor and pd.notna(value):
            deviations.append(abs(float(value) / (close * factor) - 1) * 100)
    if len(deviations) < MIN_VERIFY_NAMES:
        return None
    median = float(np.median(deviations))
    return {"date": day.strftime("%Y-%m-%d"), "names": len(deviations),
            "median_deviation_pct": round(median, 4), "suspect": median > VERIFY_TOLERANCE}


def _nasdaq_closes(symbol: str, start: str, end: str, classes: tuple[str, ...], use_cache: bool) -> dict[str, float]:
    if symbol.startswith("^"):
        code, kinds = NASDAQ_INDEX.get(symbol), ("index",)
        if code is None:
            return {}
    else:
        code, kinds = symbol.replace("-", "."), classes
    for kind in kinds:
        try:
            closes = nasdaq.fetch_history(code, start, end, asset=kind, use_cache=use_cache)
        except Exception:
            return {}
        if closes:
            return closes
    return {}


def _fred_closes(symbol: str, use_cache: bool) -> dict[str, float]:
    series = FRED_INDEX.get(symbol)
    if series is None:
        return {}
    try:
        frame, _ = fred.fetch_series(series, use_cache=use_cache)
    except Exception:
        return {}
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in zip(frame["date"], frame["value"])}


def fill(frame: pd.DataFrame, raw: pd.DataFrame | None, *, label: str, replace=(),
         classes: tuple[str, ...] = ("stocks", "etf"), use_cache: bool = True):
    """Rebuild ``frame``'s recent gaps and the ``replace`` sessions (found
    suspect by ``verify``). ``raw`` is the same symbols' split-only closes,
    used for the adjustment factor and rebuilt alongside; ``classes`` is the
    order Nasdaq's asset classes are tried in.

    Returns (frame, raw, report); the report is empty when nothing was done.
    """
    replace = [d for d in replace if d in frame.index]
    days = sorted(set(gaps(frame)) | set(replace))
    if not days:
        return frame, raw, {}
    frame = frame.copy()
    raw = raw.copy() if raw is not None else None
    for day in replace:
        frame.loc[day] = np.nan
        if raw is not None and day in raw.index:
            raw.loc[day] = np.nan

    holdings_day, holdings = _holdings(use_cache)
    # Nasdaq refuses a range whose start is not before its end; a week either
    # side also lets one request serve several gaps.
    start = (days[0] - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    end = (days[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    report: dict[str, dict] = {}
    looked_up: dict[str, dict[str, float]] = {}
    for day in days:
        key = day.strftime("%Y-%m-%d")
        closes: dict[str, tuple[str, float]] = {}
        if day == holdings_day:
            for symbol in frame.columns:
                close = holdings.get(ticker_key(symbol))
                if close and pd.isna(frame.at[day, symbol]):
                    closes[symbol] = ("ishares", close)
        for symbol in frame.columns:
            if symbol in closes or pd.notna(frame.at[day, symbol]):
                continue
            fred_closes = _fred_closes(symbol, use_cache) if symbol in FRED_INDEX else {}
            if key in fred_closes:
                closes[symbol] = ("fred", fred_closes[key])
        need = [s for s in frame.columns if pd.isna(frame.at[day, s]) and s not in closes]
        if len(need) <= MAX_NASDAQ_LOOKUPS:
            for symbol in need:
                if symbol not in looked_up:
                    looked_up[symbol] = _nasdaq_closes(symbol, start, end, classes, use_cache)
                if key in looked_up[symbol]:
                    closes[symbol] = ("nasdaq", looked_up[symbol][key])
        for symbol, (_, close) in closes.items():
            factor = _factor(frame, raw, day, symbol) or 1.0
            if raw is not None and symbol in raw.columns:
                raw.loc[day, symbol] = close
            frame.at[day, symbol] = close * factor
        unfilled = [s for s in frame.columns if pd.isna(frame.at[day, s])]
        report[key] = {
            "frame": label,
            "reason": "replaced: disagreed with IVV's closes" if day in replace else "missing at Yahoo",
            **{source: sum(1 for src, _ in closes.values() if src == source) for source in ("ishares", "nasdaq", "fred")},
            "unfilled": len(unfilled),
            "unfilled_symbols": unfilled[:20],
        }
    if raw is not None:
        raw = raw.sort_index()
    return frame, raw, report
