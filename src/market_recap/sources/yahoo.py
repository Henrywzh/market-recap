"""Daily OHLCV and fund snapshots via yfinance.

yfinance is an unofficial wrapper around a mutable service. It is good enough
for a price panel and explicitly not good enough to be called a point-in-time
archive, so every artifact it feeds carries ``source: yahoo_finance`` and the
page footer says what that means.
"""

from __future__ import annotations

import contextlib
from datetime import date
import io
from pathlib import Path
import time
from typing import Iterable, Sequence

import pandas as pd

from .. import cache

CHUNK_SIZE = 60
# Yahoo rate-limits a client that pulls the whole index twice in a row: the
# second sweep comes back less than half populated. A short pause between
# chunks plus the day's on-disk cache keeps a rebuild from re-requesting
# anything it already has.
CHUNK_PAUSE_SECONDS = 0.4


def _silent_download(symbols: Sequence[str], **kwargs) -> pd.DataFrame:
    """yfinance prints delisting chatter to stderr; a partial batch is normal."""
    import yfinance as yf

    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer), contextlib.redirect_stdout(buffer):
        return yf.download(list(symbols), progress=False, auto_adjust=True, threads=True, **kwargs)


def _download_chunk(chunk: Sequence[str], period: str) -> pd.DataFrame | None:
    raw = _silent_download(chunk, period=period)
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"]
    closes = raw[["Close"]].copy()
    closes.columns = list(chunk[:1])
    return closes


# One file per history length, refreshed once a session. The whole point is
# that a rebuild on the same day re-requests nothing: the provider drops a
# random handful of symbols per sweep, so asking again is not free.
NAMESPACE = "prices"


def _cache_path(period: str) -> Path:
    return cache.path_for(NAMESPACE, f"closes-{period}", ".parquet")


def _load_cache(period: str) -> pd.DataFrame:
    path = _cache_path(period)
    if not cache.is_fresh(path, "daily_file"):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _save_cache(period: str, frame: pd.DataFrame) -> None:
    path = _cache_path(period)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path)
    except Exception:
        # A cache that cannot be written is a slow build, not a wrong one.
        pass


def fetch_closes(
    symbols: Iterable[str],
    *,
    period: str = "2y",
    retries: int = 3,
    use_cache: bool = True,
    retry_budget_seconds: float = 180.0,
) -> pd.DataFrame:
    """Wide adjusted-close frame indexed by date, one column per symbol.

    A batch request drops a random handful of symbols on most runs -- the same
    universe returns 502 columns once and 497 the next time. Left alone that
    turns into a sector whose member count quietly changes between builds, so
    missing symbols are re-requested in progressively smaller batches. What is
    still missing afterwards is a real coverage gap and the caller reports it
    rather than back-filling it.
    """
    wanted = sorted({s for s in symbols if s})
    collected: dict[str, pd.Series] = {}

    if use_cache:
        cached = _load_cache(period)
        for symbol in wanted:
            if symbol in cached.columns and not cached[symbol].dropna().empty:
                collected[symbol] = cached[symbol]

    pending = [s for s in wanted if s not in collected]
    deadline = time.monotonic() + retry_budget_seconds
    for attempt in range(retries + 1):
        if not pending or time.monotonic() > deadline:
            break
        size = CHUNK_SIZE if attempt == 0 else max(1, CHUNK_SIZE // (4 * attempt))
        for start in range(0, len(pending), size):
            chunk = pending[start : start + size]
            try:
                closes = _download_chunk(chunk, period)
            except Exception:
                continue
            if closes is None:
                continue
            for column in closes.columns:
                series = closes[column].dropna()
                if not series.empty:
                    collected[str(column)] = closes[column]
            time.sleep(CHUNK_PAUSE_SECONDS)
        pending = [s for s in wanted if s not in collected]

    if not collected:
        return pd.DataFrame()
    out = pd.DataFrame(collected)
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index().dropna(axis=1, how="all")

    if use_cache:
        cached = _load_cache(period)
        # combine_first unions both the index and the columns, so a run that
        # only recovered part of the universe still adds to the day's cache.
        merged = out if cached.empty else cached.combine_first(out)
        _save_cache(period, merged.loc[:, ~merged.columns.duplicated()])
    return out


def fetch_ohlcv(symbol: str, *, period: str = "2y") -> pd.DataFrame:
    raw = _silent_download([symbol], period=period)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(symbol, axis=1, level=1)
    frame = raw.rename(columns=str.lower).reset_index()
    frame = frame.rename(columns={"date": "date", "Date": "date"})
    frame.columns = [str(c).lower() for c in frame.columns]
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame.dropna(subset=["close"]).reset_index(drop=True)


def fetch_fund_snapshot(symbols: Iterable[str]) -> pd.DataFrame:
    """Price, total assets and share count for ETFs, as of right now.

    Net flow on the ETF heat map is derived from the change in *shares
    outstanding*, never from a change in market value: a fund whose price fell
    has not seen an outflow, and conflating the two is the classic way to get
    that panel wrong.
    """
    import yfinance as yf

    rows: list[dict] = []
    for symbol in sorted({s for s in symbols if s}):
        try:
            info = yf.Ticker(symbol).get_info()
        except Exception:
            continue
        price = info.get("regularMarketPrice") or info.get("previousClose")
        aum = info.get("totalAssets")
        shares = info.get("sharesOutstanding")
        if shares in (None, 0) and aum and price:
            # Yahoo omits sharesOutstanding for many ETFs; AUM/NAV is the
            # issuer-consistent fallback and is flagged as such.
            shares = aum / price
            basis = "derived_aum_over_price"
        else:
            basis = "reported_shares_outstanding"
        if not price:
            continue
        rows.append(
            {
                "ticker": symbol,
                "name": info.get("shortName") or info.get("longName") or symbol,
                "price": float(price),
                "aum": float(aum) if aum else None,
                "shares_outstanding": float(shares) if shares else None,
                "shares_basis": basis,
            }
        )
    return pd.DataFrame(rows)


# Yahoo's own sector taxonomy is not GICS. Mapping it explicitly keeps one
# vocabulary on the page: a table that shows both "Technology" and
# "Information Technology" as separate sectors is simply wrong.
YAHOO_TO_GICS = {
    "Technology": "Information Technology",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Healthcare": "Health Care",
    "Financial Services": "Financials",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Basic Materials": "Materials",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}


def fetch_sectors(symbols: Iterable[str]) -> pd.DataFrame:
    """Sector and industry for names the GICS list does not cover.

    Used only as a fallback for index members outside the S&P 500, and the
    artifact records that these labels came from a different taxonomy.
    """
    import yfinance as yf

    rows: list[dict] = []
    for symbol in sorted({s for s in symbols if s}):
        try:
            info = yf.Ticker(symbol).get_info()
        except Exception:
            continue
        sector = info.get("sector")
        rows.append(
            {
                "ticker": symbol,
                "name": info.get("shortName") or info.get("longName") or symbol,
                "sector": YAHOO_TO_GICS.get(sector, sector or "Unclassified"),
                "sub_sector": info.get("industry") or "-",
                "classification_source": "yahoo_mapped_to_gics",
            }
        )
    return pd.DataFrame(rows)
