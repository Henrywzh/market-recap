"""European coverage: index membership and Yahoo's own multiples.

Membership is Wikipedia's current table for each index (descriptive, never a
record of what the index held on a past date), already carrying Yahoo-style
symbols for the EURO STOXX 50 and EPIC codes for the FTSE 100, which get a
``.L`` suffix. The multiples are Yahoo's own forward and trailing P/E: Yahoo
holds each company's price currency and reporting currency, which a UK name
that reports in dollars and trades in pence would otherwise get wrong by two
orders of magnitude, so this module never divides a price by an EPS.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import threading
from typing import Any

import pandas as pd

from .. import cache
from ..util import ERROR_DETAIL_CHARS
from .http import get_text

NAMESPACE = "europe"
FTSE_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
STOXX50_URL = "https://en.wikipedia.org/wiki/EURO_STOXX_50"
WORKERS = 4
GIVE_UP_AFTER = 8
MODULES = ["summaryDetail", "defaultKeyStatistics", "price"]


def ftse_symbol(epic: str) -> str:
    """The Yahoo symbol of a London-listed EPIC code: BT.A is BT-A.L, BP. is BP.L."""
    return str(epic).strip().rstrip(".").replace(".", "-").upper() + ".L"


def _tables(url: str) -> list[pd.DataFrame]:
    return pd.read_html(StringIO(get_text(url, timeout=45.0)))


def fetch_ftse100(*, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Current FTSE 100 members: symbol, name and the table's industry label."""

    def _parse() -> pd.DataFrame:
        frame = next(t for t in _tables(FTSE_URL) if t.shape == (100, 3) or (t.shape[0] in range(95, 106) and "Ticker" in map(str, t.columns)))
        frame = frame.copy()
        frame.columns = ["name", "ticker", "sector_source"]
        frame["symbol"] = frame["ticker"].map(ftse_symbol)
        frame["sector_source"] = frame["sector_source"].astype(str).str.strip()
        return frame[["symbol", "name", "sector_source"]]

    return cache.frame(NAMESPACE, "ftse100", _parse, kind="reference_data", use_cache=use_cache), FTSE_URL


def fetch_eurostoxx50(*, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Current EURO STOXX 50 members: Yahoo symbol, name and the table's sector."""

    def _parse() -> pd.DataFrame:
        frame = next(t for t in _tables(STOXX50_URL) if t.shape[0] == 50 and "Ticker" in t.columns)
        frame = frame.rename(columns={"Ticker": "symbol", "Name": "name", "Sector": "sector_source"})
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        return frame[["symbol", "name", "sector_source"]]

    return cache.frame(NAMESPACE, "eurostoxx50", _parse, kind="reference_data", use_cache=use_cache), STOXX50_URL


def _raw(node: Any) -> float | None:
    if isinstance(node, dict):
        node = node.get("raw")
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def parse_multiples(payload: Any) -> dict | None:
    """Forward and trailing P/E, forward and trailing EPS, market cap and the
    price currency, from a quoteSummary answer; None when it carries nothing."""
    try:
        result = payload["quoteSummary"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return None
    detail, stats, price = result.get("summaryDetail") or {}, result.get("defaultKeyStatistics") or {}, result.get("price") or {}
    out = {
        "forward_pe": _raw(detail.get("forwardPE")) or _raw(stats.get("forwardPE")),
        "trailing_pe": _raw(detail.get("trailingPE")),
        "forward_eps": _raw(stats.get("forwardEps")),
        "trailing_eps": _raw(stats.get("trailingEps")),
        "market_cap": _raw(price.get("marketCap")),
        "price": _raw(price.get("regularMarketPrice")),
        "currency": price.get("currency") if isinstance(price.get("currency"), str) else None,
    }
    return out if any(v is not None for k, v in out.items() if k != "currency") else None


def _fetch_one(symbol: str) -> str:
    import yfinance as yf

    payload = yf.Ticker(symbol)._quote._fetch(MODULES)
    if not payload:
        raise RuntimeError("empty quoteSummary answer")
    return json.dumps(payload)


def fetch_multiples(symbols: list[str], *, use_cache: bool = True) -> tuple[dict[str, dict], dict[str, str]]:
    """Yahoo's multiples per symbol, and the reason for every one without."""
    found: dict[str, dict] = {}
    failed: dict[str, str] = {}
    lock = threading.Lock()
    streak = {"n": 0}

    def one(symbol: str) -> None:
        with lock:
            if streak["n"] >= GIVE_UP_AFTER:
                failed[symbol] = "not asked: Yahoo refused the preceding requests"
                return
        try:
            text = cache.fetch_text(NAMESPACE + "-multiples", symbol.replace("/", "_"), lambda: _fetch_one(symbol),
                                    kind="daily_file", suffix=".json", use_cache=use_cache)
            parsed = parse_multiples(json.loads(text))
        except Exception as exc:  # noqa: BLE001 - one name must not fail the rest
            with lock:
                streak["n"] += 1
                failed[symbol] = str(exc)[:ERROR_DETAIL_CHARS] or type(exc).__name__
            return
        with lock:
            streak["n"] = 0
            if parsed is None:
                failed[symbol] = "Yahoo has no multiples for this name"
            else:
                found[symbol] = parsed

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, symbols))
    return found, failed
