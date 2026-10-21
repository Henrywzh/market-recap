"""Analyst EPS estimates and their recent revisions, from Yahoo's earningsTrend.

One quoteSummary request per company returns, for each fiscal period, the
period's end date, the consensus EPS now and 7/30/60/90 days ago, how many
analysts revised up or down, and how many contribute. Yahoo keeps the trend on
the same fiscal period: after Microsoft's FY26 report the FY27 row's "90 days
ago" value was an FY27 estimate (19.37), not FY26 (actual 17.28). The FY1 end
date is still recorded so the monitor's own snapshots never compare across a
roll-over.

Optional for every consumer. A refused or empty answer leaves that company's
expectations unknown; it is never read as "unchanged".
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
from typing import Any

from .. import cache
from ..util import ERROR_DETAIL_CHARS

NAMESPACE = "estimates"
URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=earningsTrend"
WORKERS = 4
# Consecutive failures after which the rest of the universe is not asked: one
# refused name is noise, eight in a row is Yahoo refusing the client.
GIVE_UP_AFTER = 8
PERIODS = ("0q", "+1q", "0y", "+1y")


def observed_at(symbol: str) -> str | None:
    """Cache observation time, not Yahoo's last estimate-revision time."""
    try:
        stamp = cache.modified(cache.path_for(NAMESPACE, symbol.replace("/", "_"), suffix=".json"))
    except OSError:
        return None
    return stamp.isoformat() if stamp is not None else None


def _raw(node: Any) -> float | None:
    if isinstance(node, dict):
        node = node.get("raw")
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def parse_trend(payload: Any) -> dict[str, dict] | None:
    """Pull each fiscal period's estimate, trend and revision counts.

    Returns ``None`` when the answer carries no trend at all (Yahoo's reply for
    names it has no coverage of), and per-period dicts otherwise.
    """
    try:
        result = payload["quoteSummary"]["result"]
        trend = result[0]["earningsTrend"]["trend"] if result else None
    except (KeyError, IndexError, TypeError):
        return None
    if not trend:
        return None
    out: dict[str, dict] = {}
    for row in trend:
        period = row.get("period")
        if period not in PERIODS:
            continue
        estimate = row.get("earningsEstimate") or {}
        revenue = row.get("revenueEstimate") or {}
        eps = row.get("epsTrend") or {}
        revisions = row.get("epsRevisions") or {}
        out[period] = {
            "end": row.get("endDate") if isinstance(row.get("endDate"), str) else None,
            "eps": _raw(eps.get("current")) if eps.get("current") else _raw(estimate.get("avg")),
            "eps_7d": _raw(eps.get("7daysAgo")),
            "eps_30d": _raw(eps.get("30daysAgo")),
            "eps_60d": _raw(eps.get("60daysAgo")),
            "eps_90d": _raw(eps.get("90daysAgo")),
            "low": _raw(estimate.get("low")),
            "high": _raw(estimate.get("high")),
            "year_ago_eps": _raw(estimate.get("yearAgoEps")),
            "analysts": _raw(estimate.get("numberOfAnalysts")),
            "up_30d": _raw(revisions.get("upLast30days")),
            "down_30d": _raw(revisions.get("downLast30days")),
            "up_7d": _raw(revisions.get("upLast7days")),
            "down_7d": _raw(revisions.get("downLast7Days")),
            "revenue": _raw(revenue.get("avg")),
            "revenue_low": _raw(revenue.get("low")),
            "revenue_high": _raw(revenue.get("high")),
            "revenue_year_ago": _raw(revenue.get("yearAgoRevenue")),
            "revenue_analysts": _raw(revenue.get("numberOfAnalysts")),
        }
    return out or None


def _fetch_one(symbol: str) -> str:
    # yfinance holds the cookie and crumb Yahoo requires; its private _fetch is
    # the one call that keeps endDate, which the public properties drop.
    import yfinance as yf

    payload = yf.Ticker(symbol)._quote._fetch(["earningsTrend"])
    if not payload:
        raise RuntimeError("empty quoteSummary answer")
    return json.dumps(payload)


def fetch_trends(symbols: list[str], *, use_cache: bool = True) -> tuple[dict[str, dict], dict[str, str]]:
    """Trend per symbol, and the reason for every symbol that has none."""
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
            text = cache.fetch_text(NAMESPACE, symbol.replace("/", "_"), lambda: _fetch_one(symbol),
                                    kind="daily_file", suffix=".json", use_cache=use_cache)
            parsed = parse_trend(json.loads(text))
        except Exception as exc:  # noqa: BLE001 - one name must not fail the rest
            with lock:
                streak["n"] += 1
                failed[symbol] = str(exc)[:ERROR_DETAIL_CHARS] or type(exc).__name__
            return
        with lock:
            streak["n"] = 0
            if parsed is None:
                failed[symbol] = "Yahoo has no estimates for this name"
            else:
                found[symbol] = parsed

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, symbols))
    return found, failed


REPORTED_NAMESPACE = "estimates_reported"


def _fetch_reported_one(symbol: str) -> str:
    import yfinance as yf

    payload = yf.Ticker(symbol)._quote._fetch(["earnings"])
    if not payload:
        raise RuntimeError("empty quoteSummary answer")
    return json.dumps(payload)


def parse_reported(payload: Any) -> dict | None:
    """The latest reported quarter: Yahoo's actual and estimate for it, and its revenue.

    ``None`` when there is no quarterly history, or while the last row is still
    the quarter to be reported (Yahoo rolls its rows over only after the release).
    """
    try:
        result = payload["quoteSummary"]["result"]
        earnings = result[0]["earnings"] if result else None
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(earnings, dict):
        return None
    chart = earnings.get("earningsChart") or {}
    rows = [r for r in (chart.get("quarterly") or []) if isinstance(r, dict)]
    if not rows:
        return None
    last = rows[-1]
    label = last.get("date") if isinstance(last.get("date"), str) else None
    if label is None:
        return None
    quarter, year = chart.get("currentQuarterEstimateDate"), _raw(chart.get("currentQuarterEstimateYear"))
    next_quarter = f"{quarter}{int(year)}" if isinstance(quarter, str) and year else None
    if label == next_quarter:
        return None
    revenue = None
    for row in (earnings.get("financialsChart") or {}).get("quarterly") or []:
        if isinstance(row, dict) and row.get("date") == label:
            revenue = _raw(row.get("revenue"))
    return {"quarter": label, "eps": _raw(last.get("actual")), "eps_estimate": _raw(last.get("estimate")),
            "revenue": revenue, "next_quarter": next_quarter}


def fetch_reported(symbols: list[str], *, use_cache: bool = True) -> tuple[dict[str, dict], dict[str, str]]:
    """The latest reported quarter per symbol, and the reason for every symbol without one."""
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
            text = cache.fetch_text(REPORTED_NAMESPACE, symbol.replace("/", "_"), lambda: _fetch_reported_one(symbol),
                                    kind="daily_file", suffix=".json", use_cache=use_cache)
            parsed = parse_reported(json.loads(text))
        except Exception as exc:  # noqa: BLE001 - one name must not fail the rest
            with lock:
                streak["n"] += 1
                failed[symbol] = str(exc)[:ERROR_DETAIL_CHARS] or type(exc).__name__
            return
        with lock:
            streak["n"] = 0
            if parsed is None:
                failed[symbol] = "Yahoo has no reported quarter for this name yet"
            else:
                found[symbol] = parsed

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, symbols))
    return found, failed


def _fetch_price_module(symbol: str) -> str:
    import yfinance as yf

    payload = yf.Ticker(symbol)._quote._fetch(["price"])
    if not payload:
        raise RuntimeError("empty quoteSummary answer")
    return json.dumps(payload)


def market_cap(symbol: str, *, use_cache: bool = True) -> float | None:
    """Yahoo's market capitalisation, every share class included.

    Only for a company whose filings carry no total share count: one that
    reports its cover-page shares class by class (Berkshire, Hershey, Ares)
    has none in SEC's company facts. None on any failure."""
    try:
        text = cache.fetch_text("yahoo-price", symbol.replace("/", "_"), lambda: _fetch_price_module(symbol),
                                kind="daily_file", suffix=".json", use_cache=use_cache)
        price = json.loads(text)["quoteSummary"]["result"][0]["price"]
    except Exception:  # noqa: BLE001 - optional: the row keeps no market cap
        return None
    value = _raw(price.get("marketCap"))
    return value if value and value > 0 else None
