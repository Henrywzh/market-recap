"""Once-a-session option-chain snapshot.

Taken inside a window from late in the session to midnight
(``[snapshots.options] window``): GitHub starts scheduled runs hours late, and
options stop trading at the close, so a later run records the closing quotes.
Free chains fetched after the close can carry zero bids; such a contract is
not used (``compute.options.mid_quote``). One file set per New York date:

- ``options/YYYY/YYYY-MM-DD-summary.csv``: one row per underlying and expiry
  (``compute.options.summarize_expiry``).
- ``options/YYYY/YYYY-MM-DD-contracts.csv.gz``: the contracts within
  ``strike_band`` of spot on the chosen expiries, for re-derivation.
- ``options/YYYY/YYYY-MM-DD-meta.json``: universe, what was dropped and why,
  the discount rate used, and timing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
import time
from typing import Any, Iterable, Mapping, Sequence

from ..compute import options as O
from ..config import load_config
from ..sources.http import FetchError, get_text
from ..sources.yahoo import _within
from . import store

SUMMARY_COLUMNS = (
    "fetched_at", "underlying", "expiry", "days", "spot", "forward", "atm_strike", "atm_iv",
    "straddle_mid", "straddle_pct", "put_25d_iv", "call_25d_iv",
    "call_oi", "put_oi", "call_volume", "put_volume", "quoted_strikes", "note",
)
CONTRACT_COLUMNS = (
    "fetched_at", "underlying", "expiry", "type", "contract", "strike", "bid", "ask", "last",
    "last_trade", "volume", "open_interest", "yahoo_iv",
)
CALL_DEADLINE_SECONDS = 45
PAUSE_SECONDS = 0.3


def build_universe(
    settings: Mapping[str, Any],
    watchlist: Sequence[Mapping[str, Any]],
    monitor_rows: Sequence[Mapping[str, Any]] | None,
    today: date,
    reporters: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Fixed names, then the watchlist, then the names reporting within
    ``report_days`` (up to ``report_max``, soonest first -- this session's
    closing straddle is their implied move), then up to ``monitor_max``
    MONITOR candidates. Candidates reporting within ``monitor_earnings_days``
    come first, then the furthest behind peers. Returns the ordered universe
    and what was left out by which rule."""
    universe: list[str] = []

    def add(symbol: str) -> None:
        symbol = symbol.strip().upper()
        if symbol and symbol not in universe:
            universe.append(symbol)

    for symbol in settings.get("fixed", []):
        add(symbol)
    if settings.get("include_watchlist", True):
        for entry in watchlist:
            add(entry["ticker"])

    left_out: dict[str, list[str]] = {}
    soon = []
    for row in reporters or []:
        try:
            days = (date.fromisoformat(str(row.get("date") or "")) - today).days
        except ValueError:
            continue
        if 0 <= days <= int(settings.get("report_days", 3)) and row.get("symbol"):
            soon.append((days, row["symbol"]))
    soon = [symbol for _, symbol in sorted(soon) if symbol.upper() not in universe]
    report_max = int(settings.get("report_max", 40))
    for symbol in soon[:report_max]:
        add(symbol)
    if soon[report_max:]:
        left_out["reporters_over_limit"] = soon[report_max:]
    limit = int(settings.get("monitor_max", 0))
    if monitor_rows is None or limit <= 0:
        return universe, left_out
    horizon = int(settings.get("monitor_earnings_days", 30))

    def reports_soon(row: Mapping[str, Any]) -> bool:
        try:
            days = (date.fromisoformat(row.get("earnings_date") or "") - today).days
        except ValueError:
            return False
        return 0 <= days <= horizon

    def lag(row: Mapping[str, Any]) -> float:
        value = row.get("peer_excess_pct")
        return value if isinstance(value, (int, float)) and math.isfinite(value) else math.inf

    candidates = [row for row in monitor_rows if row.get("candidate") and row.get("ticker") not in universe]
    candidates.sort(key=lambda row: (not reports_soon(row), lag(row), row["ticker"]))
    for row in candidates[:limit]:
        add(row["ticker"])
    left_out["monitor_over_limit"] = [row["ticker"] for row in candidates[limit:]]
    return universe, left_out


def published_reporters(base_url: str) -> list[dict]:
    """{symbol, date} of every coming report the published EVENTS panel carded."""
    text = get_text(f"{base_url.rstrip('/')}/artifacts/events.json", timeout=30.0, retries=1)
    return [{"symbol": row.get("symbol"), "date": (row.get("card") or {}).get("date")}
            for row in json.loads(text).get("upcoming") or []]


def published_monitor_rows(base_url: str) -> list[dict]:
    text = get_text(f"{base_url.rstrip('/')}/artifacts/monitor.json", timeout=30.0, retries=1)
    return json.loads(text).get("rows") or []


def yahoo_last(symbol: str) -> tuple[float, int]:
    """Last price and its epoch time from Yahoo's chart endpoint."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    meta = json.loads(get_text(url, timeout=20.0, retries=1))["chart"]["result"][0]["meta"]
    return float(meta["regularMarketPrice"]), int(meta["regularMarketTime"])


def discount_rate(symbol: str) -> tuple[float, str]:
    """Continuously compounded rate from a T-bill yield quoted in percent."""
    price, stamp = yahoo_last(symbol)
    return math.log(1.0 + price / 100.0), datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _records(frame) -> list[dict]:
    return [] if frame is None else frame.to_dict("records")


def _contract_rows(fetched_at: str, underlying: str, expiry: str, kind: str, rows: Iterable[Mapping]) -> list[dict]:
    out = []
    for row in rows:
        last_trade = row.get("lastTradeDate")
        out.append({
            "fetched_at": fetched_at, "underlying": underlying, "expiry": expiry, "type": kind,
            "contract": row.get("contractSymbol"), "strike": row.get("strike"),
            "bid": row.get("bid"), "ask": row.get("ask"), "last": row.get("lastPrice"),
            "last_trade": last_trade.isoformat() if hasattr(last_trade, "isoformat") else last_trade,
            "volume": row.get("volume"), "open_interest": row.get("openInterest"),
            "yahoo_iv": row.get("impliedVolatility"),
        })
    return out


def _clean(value):
    """NaN from pandas becomes an empty cell, never the string 'nan'."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def snapshot_underlying(symbol: str, settings: Mapping[str, Any], today: date, rate: float, fetched_at: str):
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    expiries = _within(CALL_DEADLINE_SECONDS, lambda: ticker.options) or ()
    chosen = O.select_expiries(
        expiries, today, min_days=int(settings.get("min_days", 2)),
        targets=[int(v) for v in settings.get("target_days", [30, 60])],
    )
    if not chosen:
        raise ValueError(f"no expiry at least {settings.get('min_days', 2)} days out ({len(expiries)} listed)")
    summaries, contracts, market_times = [], [], []
    band = float(settings.get("strike_band", 0.25))
    for expiry in chosen:
        chain = _within(CALL_DEADLINE_SECONDS, lambda e=expiry: ticker.option_chain(e))
        underlying = chain.underlying or {}
        spot = underlying.get("regularMarketPrice")
        if underlying.get("regularMarketTime"):
            market_times.append(int(underlying["regularMarketTime"]))
        calls = [{k: _clean(v) for k, v in row.items()} for row in _records(chain.calls)]
        puts = [{k: _clean(v) for k, v in row.items()} for row in _records(chain.puts)]
        summary = O.summarize_expiry(
            calls, puts, spot=float(spot) if spot else 0.0,
            expiry=date.fromisoformat(expiry), today=today, rate=rate,
        )
        summaries.append({"fetched_at": fetched_at, "underlying": symbol, **summary})
        if spot:
            contracts += _contract_rows(fetched_at, symbol, expiry, "C", O.trim_contracts(calls, float(spot), band))
            contracts += _contract_rows(fetched_at, symbol, expiry, "P", O.trim_contracts(puts, float(spot), band))
        time.sleep(PAUSE_SECONDS)
    return summaries, contracts, market_times


def run(*, root=None, now: datetime | None = None, force: bool = False) -> dict:
    config = load_config()
    settings = config.get("snapshots", {}).get("options", {})
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(store.NEW_YORK)
    today = local.date()
    window = settings.get("window", ["15:10", "16:00"])
    if not force and not store.in_window(now, window):
        return {"status": "skipped", "reason": f"{local:%a %H:%M} New York is outside {window[0]}-{window[1]} on a weekday"}

    # GitHub's schedule is best effort. A second in-window attempt should
    # repair a thin first capture, but not refetch a sufficiently broad one.
    saved = store.root_dir(root) / "options" / f"{today:%Y}" / f"{today}-meta.json"
    if not force and saved.exists():
        try:
            prior = json.loads(saved.read_text())
            floor = max(1, math.ceil(0.8 * len(settings.get("fixed", []))))
            if int(prior.get("usable_underlyings", 0)) >= floor:
                return {"status": "skipped", "reason": f"{today} already has {prior['usable_underlyings']} underlyings with priced straddles (floor {floor})"}
        except (OSError, ValueError, KeyError, TypeError):
            pass

    base_url = config.get("monitor", {}).get("published_base_url")
    problems: dict[str, str] = {}
    monitor_rows = None
    if base_url and int(settings.get("monitor_max", 0)) > 0:
        try:
            monitor_rows = published_monitor_rows(base_url)
        except (FetchError, ValueError, KeyError) as exc:
            problems["monitor"] = str(exc)[:300]
    reporters = None
    if base_url and int(settings.get("report_max", 0)) > 0:
        try:
            reporters = published_reporters(base_url)
        except (FetchError, ValueError, KeyError) as exc:
            problems["events"] = str(exc)[:300]
    universe, left_out = build_universe(settings, config.get("watchlist", []), monitor_rows, today, reporters)

    rate_symbol = settings.get("rate_symbol", "^IRX")
    try:
        rate, rate_time = discount_rate(rate_symbol)
    except (FetchError, ValueError, KeyError, IndexError) as exc:
        return {"status": "failed", "reason": f"discount rate {rate_symbol}: {exc}"}

    fetched_at = store.utc_stamp(now)
    budget = float(settings.get("time_budget_seconds", 1200))
    started = time.monotonic()
    summaries, contracts, failed, market_times = [], [], {}, []
    for symbol in universe:
        if time.monotonic() - started > budget:
            failed[symbol] = f"time budget of {budget:.0f}s spent"
            continue
        try:
            rows, raw, stamps = snapshot_underlying(symbol, settings, today, rate, fetched_at)
        except Exception as exc:  # one underlying never sinks the snapshot
            failed[symbol] = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue
        summaries += rows
        contracts += raw
        market_times += stamps

    # A holiday still answers with the last session's chain. The snapshot is
    # for today's session only, so if no underlying traded today, keep nothing.
    traded_today = [t for t in market_times if datetime.fromtimestamp(t, timezone.utc).astimezone(store.NEW_YORK).date() == today]
    usable_underlyings = len({row["underlying"] for row in summaries
                              if row.get("straddle_pct") is not None and math.isfinite(float(row["straddle_pct"]))
                              and float(row["straddle_pct"]) > 0})
    meta = {
        "session": today.isoformat(), "fetched_at": fetched_at, "window": window, "forced": force,
        "after_close": local.time() >= store.parse_clock(settings.get("close", "16:00")),
        "universe": universe, "left_out": left_out, "failed": failed, "problems": problems,
        "rate": {"symbol": rate_symbol, "continuous": rate, "quoted_at": rate_time},
        "underlyings_ok": len({row["underlying"] for row in summaries}), "summary_rows": len(summaries),
        "usable_underlyings": usable_underlyings,
        "contract_rows": len(contracts), "seconds": round(time.monotonic() - started, 1),
    }
    if not traded_today:
        return {"status": "skipped", "reason": f"no chain quoted a trade on {today} (market closed?)", **meta}

    folder = store.day_dir(store.root_dir(root), "options", local)
    prefix = folder / today.isoformat()
    store.write_csv(prefix.with_name(f"{today}-summary.csv"), summaries, SUMMARY_COLUMNS)
    store.write_csv(prefix.with_name(f"{today}-contracts.csv.gz"), contracts, CONTRACT_COLUMNS, compress=True)
    prefix.with_name(f"{today}-meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n")
    floor = max(1, math.ceil(0.8 * len(settings.get("fixed", []))))
    status = "ok" if not failed and usable_underlyings >= floor else "partial"
    return {"status": status, **meta}
