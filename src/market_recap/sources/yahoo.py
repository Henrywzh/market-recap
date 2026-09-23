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
import threading
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


# A batch that has not answered in this long is abandoned and retried like any
# other failed batch. yfinance's own timeout does not cover every stall: a
# build once sat for ten minutes on an open connection, and in the nightly
# job one such stall spends the whole job's time limit.
DOWNLOAD_DEADLINE_SECONDS = 120


def _within(seconds: float, call):
    """Run ``call`` with a wall-clock deadline. The worker is a daemon thread,
    so a request that never returns cannot keep the process alive either."""
    outcome: dict = {}

    def run():
        try:
            outcome["value"] = call()
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"no response from the price feed in {seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _silent_download(symbols: Sequence[str], **kwargs) -> pd.DataFrame:
    """yfinance prints delisting chatter to stderr; a partial batch is normal.

    The redirect wraps the deadline rather than sitting inside the worker, so
    an abandoned request cannot leave the process's stderr pointing at a
    buffer.
    """
    import yfinance as yf

    kwargs.setdefault("auto_adjust", True)
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer), contextlib.redirect_stdout(buffer):
        return _within(
            DOWNLOAD_DEADLINE_SECONDS,
            lambda: yf.download(list(symbols), progress=False, threads=True, **kwargs),
        )


# One response carries every price series the build needs. ``Adj Close`` is
# adjusted for splits and dividends -- the total-return series every return on
# the page is measured on. ``Close`` is adjusted for splits only: the price a
# multiple is quoted on. A P/E on dividend-adjusted prices understates every
# past multiple by the dividends paid since (Coca-Cola's 2016 price is 42.74,
# its adjusted close 31.35).
ADJUSTED_FIELD = "Adj Close"
PRICE_FIELD = "Close"
SPLITS_FIELD = "Stock Splits"
FIELDS = {"closes": ADJUSTED_FIELD, "prices": PRICE_FIELD, "splits": SPLITS_FIELD}


def _download_chunk(chunk: Sequence[str], period: str) -> dict[str, pd.DataFrame] | None:
    """{kind: frame} for a batch: adjusted closes, split-only prices, split ratios."""
    raw = _silent_download(chunk, period=period, actions=True, auto_adjust=False)
    if raw is None or raw.empty:
        return None
    out = {}
    for kind, field in FIELDS.items():
        if isinstance(raw.columns, pd.MultiIndex):
            present = field in raw.columns.get_level_values(0)
            out[kind] = raw[field] if present else pd.DataFrame(index=raw.index)
        else:
            frame = raw[[field]].copy() if field in raw.columns else pd.DataFrame(index=raw.index)
            frame.columns = list(chunk[:1])[: frame.shape[1]]
            out[kind] = frame
    return out


# One file per history length, refreshed once a session. The whole point is
# that a rebuild on the same day re-requests nothing: the provider drops a
# random handful of symbols per sweep, so asking again is not free.
NAMESPACE = "prices"


def _cache_path(period: str, kind: str = "closes") -> Path:
    return cache.path_for(NAMESPACE, f"{kind}-{period}", ".parquet")


def _read(path: Path) -> pd.DataFrame:
    if not cache.is_fresh(path, "daily_file"):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _load_cache(period: str) -> pd.DataFrame:
    # Closes cached without their companion files predate them; reusing them
    # would leave the day's splits and split-only prices unknown, so they
    # count as stale.
    if not all(_cache_path(period, kind).exists() for kind in FIELDS):
        return pd.DataFrame()
    return _read(_cache_path(period))


def _save(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path)
    except Exception:
        # A cache that cannot be written is a slow build, not a wrong one.
        pass


def fetch_splits(period: str) -> pd.DataFrame:
    """Split ratios (date x symbol, NaN where none) seen by this session's
    ``fetch_closes`` calls for ``period``. Read from the same download, so a
    symbol whose closes are known has its splits known too."""
    return _read(_cache_path(period, "splits"))


def fetch_prices(period: str) -> pd.DataFrame:
    """Split-adjusted, not dividend-adjusted closes, from the same download as
    ``fetch_closes``: what a valuation multiple is quoted on."""
    frame = _read(_cache_path(period, "prices"))
    if not frame.empty:
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


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
    companions: dict[str, dict[str, pd.Series]] = {"prices": {}, "splits": {}}

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
                result = _download_chunk(chunk, period)
            except Exception:
                continue
            if result is None:
                continue
            closes = result["closes"]
            for column in closes.columns:
                series = closes[column].dropna()
                if not series.empty:
                    collected[str(column)] = closes[column]
                    prices, splits = result["prices"], result["splits"]
                    if column in prices.columns:
                        companions["prices"][str(column)] = prices[column]
                    if column in splits.columns:
                        companions["splits"][str(column)] = splits[column].where(splits[column] > 0)
            time.sleep(CHUNK_PAUSE_SECONDS)
        pending = [s for s in wanted if s not in collected]

    if not collected:
        return pd.DataFrame()
    out = pd.DataFrame(collected)
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index().dropna(axis=1, how="all")

    if use_cache:
        # combine_first unions both the index and the columns, so a run that
        # only recovered part of the universe still adds to the day's cache.
        frames = {"closes": out}
        for kind, series in companions.items():
            frame = pd.DataFrame(series)
            if not frame.empty:
                frame.index = pd.to_datetime(frame.index).tz_localize(None)
            frames[kind] = frame
        for kind, frame in frames.items():
            path = _cache_path(period, kind)
            cached = _read(path) if path.exists() else pd.DataFrame()
            frame = frame.sort_index()
            merged = frame if cached.empty else cached.combine_first(frame)
            _save(path, merged.loc[:, ~merged.columns.duplicated()])
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
