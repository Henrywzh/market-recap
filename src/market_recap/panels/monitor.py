"""MONITOR: a prospective, adjustable-threshold research queue.

The panel records observations; it does not decide the browser's pool.  The
browser can therefore change the drawdown threshold without asking the build
to rewrite history.  The only automatic admission fact is drawdown, while the
relative, trend, valuation, quality, and earnings columns remain independent
evidence with their own completeness rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, timedelta
import math
import tomllib
from typing import Any

import pandas as pd

from ..compute import monitor as M
from ..config import REPO_ROOT, period_sessions
from ..util import SourceRecord


SCHEMA_VERSION = 1
PE_MISMATCH_TOLERANCE = 0.25

# This is deliberately an explicit row schema.  In particular, ``history``
# is always a list of two-item [YYYY-MM-DD, drawdown-or-null] observations;
# persistence validation should not have to infer a shape from the current
# row's other fields.
ROW_FIELDS = (
    "ticker", "name", "sector", "in_universe", "drawdown_pct", "price_as_of", "history",
    "market_excess_pct", "sector_excess_pct", "market_benchmark", "sector_benchmark",
    "rs_improving", "above_ma", "pe", "pe_percentile", "pe_vs_median", "fcf_positive",
    "revenue_growth_pct", "filed", "period_end", "earnings_date", "earnings_status",
    "estimate_revision", "gaps",
    # Added with the research-queue layer. ``membership`` is index, watchlist
    # (an explicit non-member from config) or removed.
    "membership", "peer_return_pct", "peer_excess_pct", "peer_count", "expectations",
    "price_state", "evidence_state", "evidence_for", "evidence_against", "candidate",
    "reasons", "anomaly", "since_first_seen_pct", "peers_since_first_seen_pct",
    "first_seen", "state_log", "reported", "note", "why_today", "return_pct",
)
METRIC_FIELDS = ROW_FIELDS[4:23]
# Carried from one build to the next; everything else is recomputed.
DURABLE_FIELDS = ("history", "first_seen", "state_log", "reported")


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict, set)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    if _missing(value):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any, digits: int | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if hasattr(value, "item"):
        try:
            item = value.item()
        except (TypeError, ValueError):
            item = value
        if isinstance(item, bool):
            return item
    return None


def _strict_date(value: Any) -> str | None:
    """Validate an already-serialized ledger date without date coercion."""

    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def _date_text(value: Any) -> str | None:
    """Normalize optional source dates to the artifact's date representation."""

    if _missing(value):
        return None
    if isinstance(value, str):
        candidate = value[:10]
        if _strict_date(candidate) is not None:
            return candidate
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


def _as_of(ctx: Any) -> str:
    value = _date_text(getattr(ctx, "as_of", None))
    if value is None:
        raise ValueError("monitor requires a valid context as_of")
    return value


def _record_value(record: Any, *keys: str) -> Any:
    if isinstance(record, Mapping):
        for key in keys:
            if key in record and not _missing(record[key]):
                return record[key]
    return None


def _index_metadata(ctx: Any, key: str) -> tuple[str, str | None]:
    for spec in getattr(ctx, "indices", ()) or ():
        if _text(getattr(spec, "key", None)) == key:
            return _text(getattr(spec, "label", None)) or key, _date_text(
                (getattr(ctx, "holdings_dates", {}) or {}).get(key)
            )
    config = getattr(ctx, "config", {}) or {}
    for spec in (config.get("universe", {}).get("indices") or []):
        if _text(spec.get("key")) == key:
            return _text(spec.get("label")) or key, _date_text(
                (getattr(ctx, "holdings_dates", {}) or {}).get(key)
            )
    return key, _date_text((getattr(ctx, "holdings_dates", {}) or {}).get(key))


def _member_metadata(ctx: Any, key: str) -> dict[str, dict[str, str | None]]:
    frame = (getattr(ctx, "members", {}) or {}).get(key)
    if frame is None:
        return {}
    if isinstance(frame, pd.DataFrame):
        records = frame.to_dict("records")
    elif isinstance(frame, Mapping):
        records = list(frame.values())
    else:
        records = list(frame) if isinstance(frame, (list, tuple)) else []

    out: dict[str, dict[str, str | None]] = {}
    for record in records:
        ticker = _text(_record_value(record, "yahoo_symbol", "ticker", "symbol"))
        if ticker is None:
            continue
        ticker = ticker.upper()
        if ticker in out:
            continue
        out[ticker] = {
            "name": _text(_record_value(record, "name", "label")) or ticker,
            "sector": _text(_record_value(record, "sector")),
        }
    return out


def _series(frame: Any, ticker: str) -> Any:
    if isinstance(frame, pd.DataFrame):
        return frame[ticker] if ticker in frame.columns else None
    if isinstance(frame, pd.Series):
        return frame
    if isinstance(frame, Mapping):
        return frame.get(ticker)
    return None


def _price_series(ctx: Any, ticker: str) -> Any:
    return _series(getattr(ctx, "closes", None), ticker)


def _benchmark_series(ctx: Any, symbol: str | None) -> Any:
    if symbol is None:
        return None
    # Context keeps the shared ETF and index frames separate, but a small
    # offline preview may only provide one of them.  The order preserves the
    # normal build's source preference without inventing a ticker.
    for attr in ("etf_closes", "index_closes", "closes"):
        series = _series(getattr(ctx, attr, None), symbol)
        if series is not None:
            return series
    return None


def _positive_float(monitor: Mapping[str, Any], key: str, fallback: float, notices: list[str]) -> float | None:
    value = _number(monitor.get(key, fallback))
    if value is None or value <= 0:
        notices.append(f"monitor.{key} must be a positive number")
        return None
    return value


def _settings(ctx: Any) -> tuple[dict, list[str]]:
    config = getattr(ctx, "config", {}) or {}
    monitor = dict(config.get("monitor") or {})
    index = _text(monitor.get("index"))
    if index is None:
        raise ValueError("config[monitor].index is required")

    drawdown_period = _text(monitor.get("drawdown_period")) or "1Y"
    relative_period = _text(monitor.get("relative_period")) or "1M"
    notices: list[str] = []

    try:
        drawdown_sessions = period_sessions(drawdown_period)
    except KeyError:
        drawdown_sessions = None
        notices.append(f"drawdown period {drawdown_period!r} is not defined")
    try:
        relative_sessions = period_sessions(relative_period)
    except KeyError:
        relative_sessions = None
        notices.append(f"relative period {relative_period!r} is not defined")

    def positive_int(key: str, fallback: int) -> int | None:
        try:
            result = int(monitor.get(key, fallback))
        except (TypeError, ValueError):
            notices.append(f"monitor.{key} must be a positive integer")
            return None
        if result <= 0:
            notices.append(f"monitor.{key} must be a positive integer")
            return None
        return result

    try:
        threshold = float(monitor.get("threshold_pct", 20.0))
    except (TypeError, ValueError):
        threshold = None
        notices.append("monitor.threshold_pct is not numeric")
    if threshold is not None and not math.isfinite(threshold):
        threshold = None
        notices.append("monitor.threshold_pct is not finite")

    settings = {
        "index": index,
        "drawdown_period": drawdown_period,
        "drawdown_sessions": drawdown_sessions,
        "threshold_pct": threshold,
        "relative_period": relative_period,
        "relative_sessions": relative_sessions,
        "ma_sessions": positive_int("ma_sessions", 20),
        "earnings_days": positive_int("earnings_days", 30),
        "peer_excess_pp": _positive_float(monitor, "peer_excess_pp", 10.0, notices),
        "sector_event_pp": _positive_float(monitor, "sector_event_pp", 3.0, notices),
        "revision_pct": _positive_float(monitor, "revision_pct", 2.0, notices),
        "min_analysts": positive_int("min_analysts", 3),
        "report_days": positive_int("report_days", 100),
        "expectations": monitor.get("expectations", False) is True,
    }
    return settings, notices


def _append_gap(gaps: list[str], message: str | None) -> None:
    if message and message not in gaps:
        gaps.append(message)


def _blank_row(
    ticker: str,
    name: str | None,
    sector: str | None,
    in_universe: bool,
    history: list[list[Any]],
    gaps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name or ticker,
        "sector": sector,
        "in_universe": bool(in_universe),
        "drawdown_pct": None,
        "price_as_of": None,
        "history": history,
        "market_excess_pct": None,
        "sector_excess_pct": None,
        "market_benchmark": None,
        "sector_benchmark": None,
        "rs_improving": None,
        "above_ma": None,
        "pe": None,
        "pe_percentile": None,
        "pe_vs_median": None,
        "fcf_positive": None,
        "revenue_growth_pct": None,
        "filed": None,
        "period_end": None,
        "earnings_date": None,
        "earnings_status": None,
        "estimate_revision": None,
        "gaps": list(gaps or []),
        "membership": "index" if in_universe else "removed",
        "peer_return_pct": None,
        "peer_excess_pct": None,
        "peer_count": None,
        "expectations": None,
        "price_state": None,
        "evidence_state": None,
        "evidence_for": [],
        "evidence_against": [],
        "candidate": None,
        "reasons": [],
        "anomaly": None,
        "since_first_seen_pct": None,
        "peers_since_first_seen_pct": None,
        "first_seen": None,
        "state_log": [],
        "reported": None,
        "note": None,
        "why_today": [],
        "return_pct": None,
    }


def _history_observations(raw: Any, *, tracking_started: str, as_of: str) -> list[list[Any]]:
    if not isinstance(raw, list):
        raise ValueError("row history is not a list")
    result: list[list[Any]] = []
    previous: str | None = None
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("history observations must be [date, drawdown] pairs")
        observed = _strict_date(item[0])
        if observed is None:
            raise ValueError("history contains an invalid date")
        if observed < tracking_started or observed > as_of or (previous is not None and observed <= previous):
            raise ValueError("history dates are not strictly increasing within the ledger")
        value = None if item[1] is None else _number(item[1], 12)
        if item[1] is not None and value is None:
            raise ValueError("history contains a non-finite drawdown")
        if value is not None and value > 0.0:
            raise ValueError("history drawdown cannot be positive")
        result.append([observed, value])
        previous = observed
    return result


def _compatible_previous(
    previous: Any,
    *,
    current_index: str,
    current_drawdown_sessions: int | None,
    current_as_of: str,
) -> dict[str, Any] | None:
    """Validate and copy only the state needed for a new observation.

    A bad ledger must not quietly become a new baseline.  The caller is on the
    build path, so raising is the safe behavior: the main runner can leave the
    production artifact untouched.
    """

    if previous is None:
        return None
    if not isinstance(previous, Mapping):
        raise ValueError("previous observation ledger is not an object")
    if previous.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("previous observation ledger schema version is incompatible")
    previous_as_of = _strict_date(previous.get("as_of"))
    tracking_started = _strict_date(previous.get("tracking_started"))
    if previous_as_of is None or tracking_started is None or tracking_started > previous_as_of:
        raise ValueError("previous observation ledger has invalid as_of/tracking_started")
    if previous_as_of > current_as_of:
        raise ValueError(
            f"rollback rejected: build as_of {current_as_of} is older than accepted {previous_as_of}"
        )
    universe = previous.get("universe")
    if not isinstance(universe, Mapping) or _text(universe.get("key")) != current_index:
        raise ValueError("previous observation ledger universe is incompatible")
    if tracking_started > current_as_of:
        raise ValueError("previous observation ledger tracking starts after the build")

    old_settings = previous.get("settings")
    if isinstance(old_settings, Mapping) and current_drawdown_sessions is not None:
        old_sessions = old_settings.get("drawdown_sessions")
        if old_sessions is not None:
            try:
                parsed_sessions = int(old_sessions)
            except (TypeError, ValueError):
                raise ValueError("previous observation ledger has an invalid drawdown window")
            if parsed_sessions != current_drawdown_sessions:
                raise ValueError("previous observation ledger drawdown window changed")

    raw_rows = previous.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("previous observation ledger rows are not a list")
    rows: dict[str, dict[str, Any]] = {}
    for old in raw_rows:
        if not isinstance(old, Mapping):
            raise ValueError("previous observation ledger row is not an object")
        ticker = _text(old.get("ticker"))
        if ticker is None:
            raise ValueError("previous observation ledger row has no ticker")
        ticker = ticker.upper()
        if ticker in rows:
            raise ValueError(f"previous observation ledger has duplicate ticker {ticker}")
        history = _history_observations(
            old.get("history"), tracking_started=tracking_started, as_of=previous_as_of
        )
        rows[ticker] = {
            "ticker": ticker,
            "name": _text(old.get("name")) or ticker,
            "sector": _text(old.get("sector")),
            "in_universe": _bool(old.get("in_universe")) is True,
            "history": history,
            "first_seen": deepcopy(old.get("first_seen")) if isinstance(old.get("first_seen"), Mapping) else None,
            "state_log": [list(item) for item in old.get("state_log") or [] if isinstance(item, (list, tuple))],
            "reported": deepcopy(old.get("reported")) if isinstance(old.get("reported"), Mapping) else None,
        }

    return {
        "as_of": previous_as_of,
        "previous_as_of": _strict_date(previous.get("previous_as_of")),
        "tracking_started": tracking_started,
        "universe": deepcopy(dict(universe)),
        "settings": deepcopy(dict(previous.get("settings") or {})),
        "rows": rows,
        "notices": [str(item) for item in (previous.get("notices") or []) if isinstance(item, str)],
        "note": _text(previous.get("note")),
    }


def _merge_history(history: list[list[Any]], observed: str, value: float | None) -> list[list[Any]]:
    by_date = {item[0]: [item[0], item[1]] for item in history}
    by_date[observed] = [observed, value]
    return [by_date[key] for key in sorted(by_date)]


def _optional_panel(payload: Any, name: str, as_of: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, f"{name} unavailable: optional panel was not supplied"
    payload_as_of = _date_text(payload.get("as_of"))
    if payload_as_of != as_of:
        return None, f"{name} unavailable: as_of mismatch"
    return dict(payload), None


def _valuation_lookup(payload: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    if payload is None:
        return {}, set(), set()
    rows: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        ticker = _text(row.get("ticker"))
        if ticker is not None:
            rows.setdefault(ticker.upper(), dict(row))
    flagged = {
        _text(item.get("ticker")).upper()
        for item in (payload.get("weight_check") or {}).get("flagged", [])
        if isinstance(item, Mapping) and _text(item.get("ticker"))
    }
    mismatched = {
        _text(item).upper()
        for item in (payload.get("pe_history") or {}).get("disagree", [])
        if _text(item)
    }
    return rows, flagged, mismatched


def _valuation_metrics(
    ticker: str,
    valuation_row: dict[str, Any] | None,
    valuation_flagged: bool,
    valuation_mismatched: bool,
    current_close: float | None,
    gaps: list[str],
) -> dict[str, Any]:
    if valuation_row is None:
        _append_gap(gaps, "valuation row unavailable")
        return {}

    quoted_price = _number(valuation_row.get("price"))
    price_valid = (
        quoted_price is not None and current_close is not None
        and math.isclose(quoted_price, current_close, rel_tol=0.005, abs_tol=0.02)
    )
    if not price_valid:
        _append_gap(gaps, "valuation price unavailable or stale; price-derived metrics withheld")
    if valuation_flagged:
        _append_gap(gaps, "valuation row flagged by share-count check; price-derived metrics withheld")
    if valuation_mismatched:
        _append_gap(gaps, "valuation P/E flagged or mismatched; P/E metrics withheld")

    values: dict[str, Any] = {}
    pe_current = _number(valuation_row.get("pe"))
    pe_history_current = _number(valuation_row.get("pe_history_current"))
    calculated_mismatch = (
        pe_current is not None and pe_history_current is not None and pe_current != 0
        and abs(pe_history_current / pe_current - 1.0) > PE_MISMATCH_TOLERANCE
    )
    pe_ok = price_valid and not valuation_flagged and not valuation_mismatched and not calculated_mismatch
    if calculated_mismatch:
        _append_gap(gaps, "valuation P/E flagged or mismatched; P/E metrics withheld")
    if pe_ok:
        # The operating P/E, on the same basis as the percentile beside it;
        # the reported one where the company has no operating history.
        operating = _number(valuation_row.get("pe_operating"), 2)
        values.update({
            "pe": operating if operating is not None else _number(valuation_row.get("pe"), 2),
            "pe_percentile": _number(valuation_row.get("pe_percentile"), 1),
            "pe_vs_median": _number(valuation_row.get("pe_vs_median"), 1),
        })

    # Existing VALUATION exposes FCF as a price-derived yield.  Offline tests
    # and future producers may provide the underlying FCF directly; prefer it
    # so its sign remains usable even when the market-cap quote is stale.
    direct_fcf = None
    for key in ("fcf", "free_cash_flow", "fcf_ttm"):
        if key in valuation_row:
            direct_fcf = _number(valuation_row.get(key))
            break
    if direct_fcf is not None:
        values["fcf_positive"] = bool(direct_fcf > 0.0)
    elif price_valid and not valuation_flagged:
        fcf_yield = _number(valuation_row.get("fcf_yield"))
        if fcf_yield is not None:
            values["fcf_positive"] = bool(fcf_yield > 0.0)

    revenue = valuation_row.get("revenue_growth_pct")
    if revenue is None:
        revenue = valuation_row.get("revenue_growth")
    values["revenue_growth_pct"] = _number(revenue, 2)
    values["filed"] = _date_text(valuation_row.get("filed"))
    values["period_end"] = _date_text(valuation_row.get("period_end"))
    return values


def _earnings_lookup(payload: dict[str, Any] | None, as_of: str, days: int | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if payload is None:
        return {}, "earnings unavailable: catalysts optional panel was not supplied"
    failed = payload.get("failed_sources") or {}
    if isinstance(failed, Mapping) and "nasdaq" in failed:
        return {}, "earnings unavailable: Nasdaq calendar failed"
    events = payload.get("events")
    if not isinstance(events, list):
        return {}, "earnings unavailable: catalysts earnings events are missing"
    if days is None:
        return {}, "earnings unavailable: earnings horizon is invalid"
    start = date.fromisoformat(as_of)
    end = start + timedelta(days=days)
    selected: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if event.get("lane") not in (None, "single_name") and event.get("event_type") != "earnings":
            continue
        ticker = _text(event.get("symbol") or event.get("ticker"))
        event_date = _date_text(event.get("date") or event.get("earnings_date"))
        if ticker is None or event_date is None:
            continue
        parsed = date.fromisoformat(event_date)
        if parsed < start or parsed > end:
            continue
        ticker = ticker.upper()
        old = selected.get(ticker)
        if old is not None and (_date_text(old.get("date")) or "9999-12-31") <= event_date:
            continue
        selected[ticker] = dict(event)
    return selected, None


def _earnings_metrics(event: dict[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {"earnings_date": None, "earnings_status": "not_scheduled"}
    timing = event.get("timing")
    status = _text(event.get("earnings_status") or event.get("status"))
    if status is None:
        status = {"bmo": "before_open", "amc": "after_close"}.get(timing, "scheduled")
    return {
        "earnings_date": _date_text(event.get("date") or event.get("earnings_date")),
        "earnings_status": status,
    }


def _current_row(
    ctx: Any,
    *,
    ticker: str,
    name: str | None,
    sector: str | None,
    as_of: str,
    settings: dict[str, Any],
    sector_etfs: Mapping[str, Any],
    market_proxy: str | None,
    valuation_payload: dict[str, Any] | None,
    valuation_gap: str | None,
    catalysts_payload: dict[str, Any] | None,
    catalysts_gap: str | None,
    valuation_rows: dict[str, dict[str, Any]],
    valuation_flagged: set[str],
    valuation_mismatched: set[str],
    earnings_rows: dict[str, dict[str, Any]],
    earnings_gap: str | None,
    peers: tuple[pd.DataFrame | None, str | None] = (None, "no peer basket"),
    membership: str = "index",
) -> dict[str, Any]:
    gaps: list[str] = []
    stock = _price_series(ctx, ticker)

    drawdown_value: float | None = None
    if settings["drawdown_sessions"] is None:
        _append_gap(gaps, "drawdown unavailable: invalid configured period")
    else:
        drawdown_value, reason = M.drawdown(stock, as_of, int(settings["drawdown_sessions"]))
        _append_gap(gaps, reason)

    market_series = _benchmark_series(ctx, market_proxy)
    sector_symbol = _text(sector_etfs.get(sector)) if sector is not None else None
    sector_series = _benchmark_series(ctx, sector_symbol) if sector_symbol else None

    market_return = sector_return = stock_return = None
    if settings["relative_sessions"] is None:
        _append_gap(gaps, "relative returns unavailable: invalid configured period")
    else:
        relative_sessions = int(settings["relative_sessions"])
        stock_return, stock_reason = M.period_return(stock, as_of, relative_sessions)
        market_return, market_reason = M.period_return(market_series, as_of, relative_sessions)
        sector_return, sector_reason = M.period_return(sector_series, as_of, relative_sessions)
        if stock_reason:
            _append_gap(gaps, f"stock relative return unavailable: {stock_reason}")
        if market_reason:
            _append_gap(gaps, f"market benchmark unavailable: {market_reason}")
        if sector_symbol is None:
            _append_gap(gaps, "sector benchmark unavailable: no configured sector ETF")
        elif sector_reason:
            _append_gap(gaps, f"sector benchmark unavailable: {sector_reason}")

    # Relative strength and the peer return use the peer basket without the
    # company, not the cap-weighted sector ETF the company may dominate.
    rs_improving = peer_return = None
    peer_count = 0
    peer_window, peer_reason = peers
    if settings["relative_sessions"] is not None and peer_window is not None:
        sessions = int(settings["relative_sessions"])
        index = M.peer_index(peer_window, exclude=ticker)
        if index is None:
            _append_gap(gaps, "peer basket unavailable: no other sector member")
        else:
            rs_improving, rs_reason = M.relative_strength_improving(stock, index, as_of, sessions)
            _append_gap(gaps, rs_reason)
            peer_return, peer_count = M.peer_median_return(peer_window.iloc[sessions:], exclude=ticker)
    elif peer_reason:
        _append_gap(gaps, f"peer basket unavailable: {peer_reason}")

    above_ma = None
    if settings["ma_sessions"] is None:
        _append_gap(gaps, "moving average unavailable: invalid configured window")
    else:
        above_ma, ma_reason = M.above_moving_average(stock, as_of, int(settings["ma_sessions"]))
        _append_gap(gaps, ma_reason)

    adjusted_close = M.series_value(getattr(ctx, "closes", None), ticker, as_of)
    split_only_close = M.series_value(getattr(ctx, "prices", None), ticker, as_of)
    quote_as_of = as_of if adjusted_close is not None else None
    values = _blank_row(ticker, name, sector, membership == "index", [], gaps)
    values.update({
        "membership": membership,
        "peer_return_pct": _number(peer_return, 2),
        "peer_excess_pct": (
            _number(stock_return - peer_return, 2)
            if stock_return is not None and peer_return is not None else None
        ),
        "peer_count": peer_count or None,
        "drawdown_pct": _number(drawdown_value, 4),
        "price_as_of": quote_as_of,
        "market_excess_pct": (
            _number(stock_return - market_return, 2)
            if stock_return is not None and market_return is not None else None
        ),
        "sector_excess_pct": (
            _number(stock_return - sector_return, 2)
            if stock_return is not None and sector_return is not None else None
        ),
        "market_benchmark": market_proxy,
        "sector_benchmark": sector_symbol,
        "rs_improving": rs_improving,
        "above_ma": above_ma,
    })

    if valuation_payload is None:
        _append_gap(values["gaps"], valuation_gap or "valuation unavailable: optional panel was not supplied")
    else:
        values.update(_valuation_metrics(
            ticker,
            valuation_rows.get(ticker),
            ticker in valuation_flagged,
            ticker in valuation_mismatched,
            split_only_close,
            values["gaps"],
        ))

    if catalysts_payload is None:
        _append_gap(values["gaps"], catalysts_gap or "earnings unavailable: optional panel was not supplied")
    elif earnings_gap:
        # A failed calendar is unknown coverage, not evidence that no event is
        # scheduled.  Leave both fields null so the frontend cannot turn a
        # source failure into a negative fact.
        _append_gap(values["gaps"], earnings_gap)
    else:
        values.update(_earnings_metrics(earnings_rows.get(ticker)))

    return values




# ---------------------------------------------------------------------------
# Research-queue layer: who is a candidate and why, what changed today, and
# which sectors are weak as a whole.

NOTES_PATH = REPO_ROOT / "config" / "monitor_notes.toml"
NOTE_STATUSES = ("watch", "exclude")
STATE_FIELDS = ("candidate", "price_state", "evidence_state")
REPAIR_LOOKBACK_SESSIONS = 5


def load_notes(path=NOTES_PATH) -> tuple[dict[str, dict], list[str]]:
    """Hand-kept watch/exclude decisions with their reasons, from the repo.

    They are versioned with the code rather than kept in a browser, so the
    reason a name was set aside survives devices, caches and rebuilds.
    """

    if not path.exists():
        return {}, []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"monitor notes unreadable: {exc}"]
    notes: dict[str, dict] = {}
    problems: list[str] = []
    for number, item in enumerate(data.get("note") or [], start=1):
        item = item if isinstance(item, Mapping) else {}
        ticker = _text(item.get("ticker"))
        status = _text(item.get("status"))
        reason = _text(item.get("reason"))
        if ticker is None or status not in NOTE_STATUSES or reason is None:
            problems.append(f"monitor note {number} needs ticker, status (watch or exclude) and reason")
            continue
        notes[ticker.upper()] = {
            "status": status,
            "since": _date_text(item.get("since")),
            "reason": reason,
            "outcome": _text(item.get("outcome")),
        }
    return notes, problems


def _reported_events(payload: Mapping[str, Any] | None, as_of: str) -> dict[str, dict]:
    """The latest reported quarter per symbol that CATALYSTS saw this build."""

    if payload is None:
        return {}
    recent = payload.get("recent") or {}
    events = [*(payload.get("events") or []), *(recent.get("earnings_reacted") or []),
              *(recent.get("earnings_after_close") or [])]
    out: dict[str, dict] = {}
    for event in events:
        if not isinstance(event, Mapping) or event.get("event_type") != "earnings":
            continue
        eps, forecast = _number(event.get("eps")), _number(event.get("eps_forecast"))
        day = _date_text(event.get("date"))
        symbol = _text(event.get("symbol"))
        if eps is None or day is None or day > as_of or symbol is None:
            continue
        surprise = _number(event.get("surprise_pct"), 2)
        if surprise is None and forecast not in (None, 0):
            surprise = round((eps - forecast) / abs(forecast) * 100.0, 2)
        record = {
            "date": day, "eps": eps, "eps_forecast": forecast, "surprise_pct": surprise,
            "fiscal_quarter": _text(event.get("fiscal_quarter")),
            "return_1d": _number(event.get("return_1d"), 2),
        }
        old = out.get(symbol.upper())
        if old is None or old["date"] < day or (old["date"] == day and record["return_1d"] is not None):
            out[symbol.upper()] = record
    return out


def _newer_report(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None) -> dict | None:
    if new is None:
        return dict(old) if old else None
    if old is None or str(old.get("date")) < new["date"]:
        return dict(new)
    if old.get("date") == new["date"] and new.get("return_1d") is not None:
        return dict(new)
    return dict(old)


def _candidate(row: Mapping[str, Any], settings: Mapping[str, Any]) -> tuple[bool | None, list[str]]:
    reasons: list[str] = []
    drawdown, peer = row.get("drawdown_pct"), row.get("peer_excess_pct")
    threshold, peer_pp = settings.get("threshold_pct"), settings.get("peer_excess_pp")
    if drawdown is not None and threshold is not None and drawdown <= -threshold:
        reasons.append("drawdown")
    if peer is not None and peer_pp is not None and peer <= -peer_pp:
        reasons.append("peer_laggard")
    if reasons:
        return True, reasons
    return (False if drawdown is not None or peer is not None else None), reasons


def _loggable(row: Mapping[str, Any]) -> dict[str, Any]:
    """The states a transition may be read from.

    With no estimate reading (Yahoo did not answer), evidence can only be
    ``deteriorating`` from the filings or the last report; ``steady`` needs a
    live estimate and ``unknown`` is then the source's gap, not the company's.
    So evidence is logged as unknown-for-now and a refused night of requests
    does not flip every name.
    """

    evidence = row.get("evidence_state")
    if row.get("expectations") is None and evidence != "deteriorating":
        evidence = None
    return {"candidate": row.get("candidate"), "price_state": row.get("price_state"), "evidence_state": evidence}


def _last_state(log: list[list[Any]], before: str) -> dict[str, Any] | None:
    for entry in reversed(log):
        if entry and entry[0] < before:
            return dict(zip(("date", *STATE_FIELDS), entry))
    return None


def _log_state(log: list[list[Any]], as_of: str, today: Mapping[str, Any]) -> list[list[Any]]:
    """Append today's state when it differs from the last one.

    An unknown reading carries the last known value into the entry, so a data
    gap is never recorded as a transition.
    """

    kept = [list(entry) for entry in log if entry and entry[0] < as_of]
    last = _last_state(kept, as_of)
    entry = [as_of] + [
        today.get(field) if today.get(field) is not None else (last or {}).get(field)
        for field in STATE_FIELDS
    ]
    if last is None or [last[field] for field in STATE_FIELDS] != entry[1:]:
        if any(value is not None for value in entry[1:]):
            kept.append(entry)
    return kept


def _changes(row: Mapping[str, Any], before: Mapping[str, Any] | None, *, new_row: bool,
             baseline: bool, was_index: bool | None, as_of: str, settings: Mapping[str, Any]) -> list[dict]:
    """What is different about this row today, in the reader's terms."""

    out: list[dict] = []

    def add(kind: str, text: str) -> None:
        out.append({"ticker": row["ticker"], "sector": row.get("sector"), "kind": kind,
                    "anomaly": row.get("anomaly"), "text": text})

    watched = (row.get("note") or {}).get("status") == "watch"
    if was_index and row.get("membership") == "removed":
        add("left_index", "No longer an index member; its history is kept")
    candidate = row.get("candidate")
    reasons = ", ".join(_REASON_TEXT[r] for r in row.get("reasons") or [])
    if candidate is True and not baseline:
        if new_row:
            add("first_observed", f"First observed already in the queue: {reasons}")
        elif not (before or {}).get("candidate"):
            add("entered", f"Entered the queue: {reasons}")
    if candidate is False and (before or {}).get("candidate") is True:
        add("left", "Left the queue: drawdown shallower than "
                    f"−{settings.get('threshold_pct'):g}% and not lagging peers by {settings.get('peer_excess_pp'):g} pp")
    if not (candidate or watched) or before is None:
        return out
    price, was_price = row.get("price_state"), before.get("price_state")
    if price == "stabilising" and was_price == "weak":
        add("stabilising", "Relative strength against peers turned up and the close is back above its average")
    elif price == "weak" and was_price == "stabilising":
        add("weakening", "Stabilisation failed: " + ("lagging peers again" if row.get("rs_improving") is False
                                                     else "back below its average"))
    evidence, was_evidence = _loggable(row)["evidence_state"], before.get("evidence_state")
    if evidence == "deteriorating" and was_evidence != "deteriorating" and was_evidence is not None:
        add("evidence_down", "; ".join(row.get("evidence_against") or []))
    elif evidence == "steady" and was_evidence == "deteriorating":
        add("evidence_up", "Nothing against it any more: " + "; ".join(row.get("evidence_for") or []))
    elif evidence == "unknown" and was_evidence == "steady":
        add("evidence_unknown", "Estimates stopped being live: " + str((row.get("expectations") or {}).get("state")))
    reported = row.get("reported") or {}
    if reported.get("date") == as_of:
        surprise = reported.get("surprise_pct")
        add("reported", f"Reported {reported.get('fiscal_quarter') or ''}: EPS {reported.get('eps')} vs "
                        f"{reported.get('eps_forecast')} expected"
                        + (f" ({surprise:+.1f}%)" if surprise is not None else ""))
    return out


_REASON_TEXT = {
    "drawdown": "drawdown past the threshold",
    "peer_laggard": "lagging its sector peers",
}


def _since_first_seen(ctx: Any, ticker: str, peers: list[str], start: str, as_of: str) -> tuple[float | None, float | None]:
    """Adjusted return since the first queue date, and the peers' median."""

    closes = getattr(ctx, "closes", None)
    if start >= as_of or not isinstance(closes, pd.DataFrame):
        return None, None

    def ret(symbol: str) -> float | None:
        a, b = M.series_value(closes, symbol, start), M.series_value(closes, symbol, as_of)
        return (b / a - 1.0) * 100.0 if a and b is not None and a > 0 else None

    own = ret(ticker)
    others = [value for value in (ret(peer) for peer in peers if peer != ticker) if value is not None]
    peer = float(pd.Series(others).median()) if others else None
    return _number(own, 2), _number(peer, 2)


def _sector_summary(ctx: Any, rows: list[dict], sector_members: dict[str, list[str]], *, as_of: str,
                    settings: Mapping[str, Any], sector_etfs: Mapping[str, Any],
                    market_return: float | None, members_median: float | None) -> list[dict]:
    """Per sector: how weak against the market, how broad, and any repair.

    Like is compared with like: the cap-weighted ETF against the cap-weighted
    market, the median member against the median of all members. When a few
    mega-caps carry the index, every equal-weight median trails it; a sector
    is weak as a whole only when it trails on both.
    """

    sessions = settings.get("relative_sessions")
    ma = settings.get("ma_sessions")
    earlier = M.exchange_sessions_ending(as_of, REPAIR_LOOKBACK_SESSIONS + 1)[0].isoformat()
    by_ticker = {row["ticker"]: row for row in rows}
    out = []
    for sector, members in sorted(sector_members.items()):
        member_rows = [by_ticker[t] for t in members if t in by_ticker]
        returns = [r["return_pct"] for r in member_rows if r.get("return_pct") is not None]
        etf = _text(sector_etfs.get(sector))
        etf_return = None
        if etf and sessions:
            etf_return, _ = M.period_return(_benchmark_series(ctx, etf), as_of, int(sessions))
        median = float(pd.Series(returns).median()) if returns else None
        above_now = [r["above_ma"] for r in member_rows if r.get("above_ma") is not None]
        above_then = []
        if ma:
            for ticker in members:
                value, _ = M.above_moving_average(_price_series(ctx, ticker), earlier, int(ma))
                if value is not None:
                    above_then.append(value)
        excess_etf = (etf_return - market_return) if etf_return is not None and market_return is not None else None
        excess_median = (median - members_median) if median is not None and members_median is not None else None
        pp = settings.get("sector_event_pp")
        known = [v for v in (excess_etf, excess_median) if v is not None]
        event = pp is not None and bool(known) and all(v <= -pp for v in known)
        out.append({
            "sector": sector,
            "etf": etf,
            "members": len(member_rows),
            "etf_return_pct": _number(etf_return, 2),
            "etf_excess_pct": _number(excess_etf, 2),
            "median_return_pct": _number(median, 2),
            "median_excess_pct": _number(excess_median, 2),
            "down_share": _number(sum(v < 0 for v in returns) / len(returns), 3) if returns else None,
            "candidates": sum(1 for r in member_rows if r.get("candidate")),
            "drawdown_share": _number(
                sum(1 for r in member_rows if "drawdown" in (r.get("reasons") or [])) / len(member_rows), 3
            ) if member_rows else None,
            "above_ma_share": _number(sum(above_now) / len(above_now), 3) if above_now else None,
            "above_ma_share_before": _number(sum(above_then) / len(above_then), 3) if above_then else None,
            "repair_since": earlier,
            "event": bool(event),
        })
    return out


def build(ctx, *, valuation=None, catalysts=None, previous=None, trends=None, notes=None) -> dict:
    """Build one MONITOR artifact from the already-fetched build context.

    ``trends`` and ``notes`` are injectable for tests; by default estimates are
    fetched when ``[monitor] expectations`` is on and notes are read from
    config/monitor_notes.toml.
    """

    as_of = _as_of(ctx)
    settings, notices = _settings(ctx)
    index_key = settings["index"]
    label, holdings_as_of = _index_metadata(ctx, index_key)
    members = _member_metadata(ctx, index_key)
    config = getattr(ctx, "config", {}) or {}
    universe_config = config.get("universe") or {}
    market_proxy = _text(universe_config.get("market_proxy"))
    sector_etfs = universe_config.get("sectors") or {}

    previous_state = _compatible_previous(
        previous,
        current_index=index_key,
        current_drawdown_sessions=settings["drawdown_sessions"],
        current_as_of=as_of,
    )
    # A rerun of the first session is still the baseline, and a rerun of any
    # session compares with the build before it, not with itself.
    baseline = previous_state is None or previous_state["tracking_started"] == as_of
    if previous_state is None:
        compared_with = None
    elif previous_state["as_of"] < as_of:
        compared_with = previous_state["as_of"]
    else:
        compared_with = previous_state["previous_as_of"]
    valuation_payload, valuation_notice = _optional_panel(valuation, "valuation", as_of)
    catalysts_payload, catalysts_notice = _optional_panel(catalysts, "catalysts", as_of)
    if valuation_notice:
        notices.append(valuation_notice)
    if catalysts_notice:
        notices.append(catalysts_notice)

    valuation_rows, valuation_flagged, valuation_mismatched = _valuation_lookup(valuation_payload)
    earnings_rows, earnings_gap = _earnings_lookup(
        catalysts_payload, as_of, settings["earnings_days"]
    )
    if earnings_gap and catalysts_payload is not None:
        notices.append(earnings_gap)
    reported_today = _reported_events(catalysts_payload, as_of)

    if notes is None:
        notes, problems = load_notes()
        notices.extend(problems)

    # Explicit non-members: the configured watchlist, measured the same way.
    watch: dict[str, dict[str, str | None]] = {}
    frame = getattr(ctx, "watchlist", None)
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        for record in frame.to_dict("records"):
            ticker = _text(record.get("ticker"))
            if ticker and ticker.upper() not in members and record.get("priced", True):
                watch[ticker.upper()] = {"name": _text(record.get("name")) or _text(record.get("label")) or ticker,
                                         "sector": _text(record.get("sector"))}

    sector_members: dict[str, list[str]] = {}
    for ticker, meta in members.items():
        if meta["sector"]:
            sector_members.setdefault(meta["sector"], []).append(ticker)
    peer_windows: dict[str, tuple[pd.DataFrame | None, str | None]] = {}
    if settings["relative_sessions"] is not None:
        for sector, tickers in sector_members.items():
            peer_windows[sector] = M.peer_window(
                getattr(ctx, "closes", None), tickers, as_of, 2 * int(settings["relative_sessions"]) + 1)

    if trends is None:
        trends = {}
        if settings["expectations"]:
            from ..sources import estimates

            symbols = sorted({*members, *watch})
            trends, failed = estimates.fetch_trends(symbols)
            log = getattr(ctx, "log", None)
            if log is not None:
                log.add(SourceRecord(
                    "yahoo_estimates", "Analyst EPS estimates and revisions (Yahoo earningsTrend)",
                    estimates.URL.format(symbol="{symbol}"), observed_date=as_of, rows=len(trends),
                    status="ok" if len(failed) <= 0.1 * max(len(symbols), 1) else "partial",
                    error=f"{len(failed)} of {len(symbols)} without estimates" if failed else None,
                ))
            if len(failed) > 0.5 * max(len(symbols), 1):
                notices.append(f"estimates unavailable for {len(failed)} of {len(symbols)} names")

    rows: list[dict[str, Any]] = []
    old_rows = previous_state["rows"] if previous_state is not None else {}
    universe = [(t, members[t], "index") for t in sorted(members)] + [(t, watch[t], "watchlist") for t in sorted(watch)]
    for ticker, meta, membership in universe:
        row = _current_row(
            ctx,
            ticker=ticker,
            name=meta["name"],
            sector=meta["sector"],
            as_of=as_of,
            settings=settings,
            sector_etfs=sector_etfs,
            market_proxy=market_proxy,
            valuation_payload=valuation_payload,
            valuation_gap=valuation_notice,
            catalysts_payload=catalysts_payload,
            catalysts_gap=catalysts_notice,
            valuation_rows=valuation_rows,
            valuation_flagged=valuation_flagged,
            valuation_mismatched=valuation_mismatched,
            earnings_rows=earnings_rows,
            earnings_gap=earnings_gap,
            peers=peer_windows.get(meta["sector"], (None, "no sector")) if meta["sector"] else (None, "no sector"),
            membership=membership,
        )
        old_history = old_rows.get(ticker, {}).get("history", [])
        row["history"] = _merge_history(old_history, as_of, row["drawdown_pct"])
        rows.append(row)

    # Keep prior names as metadata/history only.  In particular, do not carry
    # their old valuation, earnings, or current-price fields into a removed
    # universe row.
    listed = {ticker for ticker, _, _ in universe}
    for ticker, old in sorted(old_rows.items()):
        if ticker in listed:
            continue
        removed_history = _merge_history(old["history"], as_of, None)
        rows.append(_blank_row(
            ticker, old["name"], old["sector"], False, removed_history, ["outside universe"],
        ))

    market_return = None
    if settings["relative_sessions"] is not None:
        market_return, _ = M.period_return(_benchmark_series(ctx, market_proxy), as_of,
                                           int(settings["relative_sessions"]))
    for row in rows:
        excess = row.get("market_excess_pct")
        row["return_pct"] = _number(excess + market_return, 2) if excess is not None and market_return is not None else None

    changes: list[dict] = []
    for row in rows:
        ticker = row["ticker"]
        old = old_rows.get(ticker)
        current = row["membership"] != "removed"
        row["note"] = notes.get(ticker)
        row["reported"] = _newer_report((old or {}).get("reported"), reported_today.get(ticker))
        if current:
            reading = M.expectation_reading(
                trends.get(ticker), revision_pct=settings["revision_pct"] or 2.0,
                min_analysts=settings["min_analysts"] or 1)
            row["expectations"] = reading
            row["estimate_revision"] = (reading or {}).get("change_30d_pct")
            if reading is None:
                _append_gap(row["gaps"], "analyst estimates unavailable")
            elif reading["state"] in ("stale", "thin"):
                _append_gap(row["gaps"], f"analyst estimates {reading['state']}")
            row["price_state"] = M.price_state(row["rs_improving"], row["above_ma"])
            row["evidence_state"], row["evidence_for"], row["evidence_against"] = M.evidence(
                row, as_of=as_of, revision_pct=settings["revision_pct"] or 2.0,
                report_days=settings["report_days"] or 100)
            row["candidate"], row["reasons"] = _candidate(row, settings)
        first = (old or {}).get("first_seen")
        if first is None and row["candidate"]:
            first = {"date": as_of, "reasons": list(row["reasons"]), "baseline": old is None}
        row["first_seen"] = first
        if first and current:
            row["since_first_seen_pct"], row["peers_since_first_seen_pct"] = _since_first_seen(
                ctx, ticker, sector_members.get(row.get("sector") or "", []), first["date"], as_of)
        old_log = (old or {}).get("state_log") or []
        before = _last_state(old_log, as_of)
        row["state_log"] = _log_state(old_log, as_of, _loggable(row)) if current else [
            list(entry) for entry in old_log if entry and entry[0] < as_of]
        row["_changes_before"] = before
        row["_new_row"] = old is None
        row["_was_index"] = (old or {}).get("in_universe")

    member_returns = [r["return_pct"] for r in rows if r["membership"] == "index" and r["return_pct"] is not None]
    members_median = float(pd.Series(member_returns).median()) if member_returns else None
    sectors = _sector_summary(ctx, rows, sector_members, as_of=as_of, settings=settings,
                              sector_etfs=sector_etfs, market_return=market_return,
                              members_median=members_median)
    event_sectors = {s["sector"] for s in sectors if s["event"]}
    for row in rows:
        if row["candidate"]:
            if "peer_laggard" in row["reasons"]:
                row["anomaly"] = "company"
            elif row.get("sector") in event_sectors:
                row["anomaly"] = "sector"
            else:
                row["anomaly"] = "drawdown"
        found = _changes(row, row.pop("_changes_before"), new_row=row.pop("_new_row"), baseline=baseline,
                         was_index=row.pop("_was_index"), as_of=as_of, settings=settings)
        row["why_today"] = [change["kind"] for change in found]
        changes.extend(found)

    if not members:
        notices.append(f"configured monitor universe {index_key} has no members in context")
    notices = list(dict.fromkeys(notices))
    tracking_started = previous_state["tracking_started"] if previous_state is not None else as_of
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "tracking_started": tracking_started,
        "previous_as_of": compared_with,
        "universe": {
            "key": index_key,
            "label": label,
            "members": len(members),
            "holdings_as_of": holdings_as_of,
            "watchlist": len(watch),
        },
        "settings": settings,
        "market_return_pct": _number(market_return, 2),
        # Equal-weight against cap-weighted: the breadth of the move.
        "members_median_return_pct": _number(members_median, 2),
        "sectors": sectors,
        "changes": changes,
        "rows": rows,
        "notices": notices,
        "note": (
            "A name enters the research queue when its adjusted close is at least the threshold below its "
            "1Y high, or when its 1M return trails the median of its sector peers (other index members, "
            "equally weighted, the company excluded) by the peer margin. Nothing is scored. Evidence for "
            "and against is listed side by side: FY1 consensus EPS revisions (Yahoo earningsTrend, same "
            "fiscal period), revenue growth and free cash flow from the latest filing, and the last "
            "reported quarter against consensus. Price is 'stabilising' only when relative strength "
            "against peers turned up and the close is above its average. Unknown is never steady. "
            "History is prospective from the first build; a first observation is not a historical entry."
        ),
    }
