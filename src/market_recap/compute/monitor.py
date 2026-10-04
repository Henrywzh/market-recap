"""Pure calculations used by the MONITOR panel.

The monitor has a slightly stricter completeness rule than most price tables.
It is a prospective observation ledger, so a missing exchange session is an
unknown observation rather than an invitation to compress the window or carry
the previous close forward.  The helpers in this module keep that rule in one
place and leave persistence, universe membership, and optional panels to
``panels.monitor``.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from . import catalysts as exchange_calendar


def _as_date(value: Any) -> date | None:
    """Return a calendar date without silently accepting an invalid value."""

    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.date()


def exchange_sessions_ending(as_of: Any, count: int) -> list[date]:
    """Return the last ``count`` exchange sessions ending at ``as_of``.

    The repository's NYSE calendar is deliberately used instead of a generic
    weekday range.  This means a missing holiday row stays a missing row and
    cannot be mistaken for an observed close.
    """

    end = _as_date(as_of)
    if end is None or count <= 0:
        return []
    found: list[date] = []
    day = end
    while len(found) < count:
        if exchange_calendar.is_session(day):
            found.append(day)
        day -= timedelta(days=1)
    return list(reversed(found))


def _numeric_series(series: Any) -> pd.Series | None:
    """Normalize a price series to a unique, date-indexed numeric series."""

    if series is None:
        return None
    if isinstance(series, pd.DataFrame):
        if series.shape[1] != 1:
            return None
        series = series.iloc[:, 0]
    if not isinstance(series, pd.Series):
        try:
            series = pd.Series(series)
        except (TypeError, ValueError):
            return None
    try:
        index = pd.to_datetime(series.index, errors="coerce")
    except (TypeError, ValueError):
        return None
    if not isinstance(index, pd.DatetimeIndex):
        return None
    if index.tz is not None:
        index = index.tz_localize(None)
    valid = ~index.isna()
    if not valid.any():
        return None
    out = pd.Series(pd.to_numeric(series.to_numpy(), errors="coerce"), index=index)
    out = out.loc[valid]
    # A duplicate source print for one date is not a second session.  Keep the
    # last print, which is also how a same-date observation is replaced.
    return out.groupby(level=0).last().sort_index()


def _window(series: Any, as_of: Any, count: int, *, label: str) -> tuple[pd.Series | None, str | None]:
    """Align a series to exact exchange sessions and require every value."""

    dates = exchange_sessions_ending(as_of, count)
    if len(dates) != count:
        return None, f"{label} needs {count} exchange sessions"
    clean = _numeric_series(series)
    if clean is None:
        return None, f"{label} source is unavailable"
    index = pd.DatetimeIndex(dates)
    values = clean.reindex(index)
    missing = values.isna()
    if bool(missing.any()):
        missing_dates = [d.strftime("%Y-%m-%d") for d in index[missing.to_numpy()][:3]]
        suffix = f"; missing {', '.join(missing_dates)}" if missing_dates else ""
        return None, f"{label} needs {count} exchange sessions{suffix}"
    numeric = values.to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        return None, f"{label} contains a non-finite observation"
    if (numeric <= 0).any():
        return None, f"{label} contains a non-positive price"
    return values.astype(float), None


def numeric_column(frame: Any, ticker: str) -> pd.Series | None:
    """``ticker``'s column of a frame or mapping as a unique, sorted, numeric,
    date-indexed series (``_numeric_series``), or None when there is none.

    Normalising a column costs a date parse, a group-by and a sort over its
    whole history. ``series_value`` did it on every question; a caller asking
    many questions of one column does it once and uses ``value_on``."""

    series: Any = None
    if isinstance(frame, pd.DataFrame):
        if ticker in frame.columns:
            series = frame[ticker]
    elif isinstance(frame, pd.Series):
        series = frame
    elif isinstance(frame, Mapping):
        series = frame.get(ticker)
    if series is None:
        return None
    return _numeric_series(series)


def value_on(clean: pd.Series | None, as_of: Any) -> float | None:
    """The finite value of a normalised series on exactly ``as_of``."""

    day = _as_date(as_of)
    if clean is None or day is None:
        return None
    value = clean.get(pd.Timestamp(day))
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def series_value(frame: Any, ticker: str, as_of: Any) -> float | None:
    """Read a value on exactly ``as_of`` from a frame or mapping.

    This helper intentionally does not use ``last_valid_index``: a stale last
    value is not today's quote.
    """

    return value_on(numeric_column(frame, ticker), as_of)


def _endpoint_return(values: pd.Series, sessions: int) -> float | None:
    if sessions <= 0 or len(values) != sessions + 1:
        return None
    start, end = float(values.iloc[0]), float(values.iloc[-1])
    if not (math.isfinite(start) and math.isfinite(end)) or start <= 0:
        return None
    return float((end / start - 1.0) * 100.0)


def period_return(series: Any, as_of: Any, sessions: int) -> tuple[float | None, str | None]:
    """Return over exact exchange sessions, with the completeness reason."""

    if sessions <= 0:
        return None, "return window must contain at least one session"
    values, reason = _window(series, as_of, sessions + 1, label=f"{sessions}-session return")
    if values is None:
        return None, reason
    result = _endpoint_return(values, sessions)
    return (result, None) if result is not None else (None, "return has no valid endpoints")


def drawdown(series: Any, as_of: Any, sessions: int) -> tuple[float | None, str | None]:
    """Current drawdown from the trailing high, requiring all sessions."""

    if sessions <= 0:
        return None, "drawdown window must contain at least one session"
    values, reason = _window(series, as_of, sessions, label="drawdown")
    if values is None:
        return None, reason
    high = float(values.max())
    current = float(values.iloc[-1])
    if not (math.isfinite(high) and high > 0 and math.isfinite(current)):
        return None, "drawdown has no valid high or current price"
    # A drawdown is never a positive admission signal.  The cap also absorbs
    # a tiny floating-point overshoot when today's value is the high.
    value = min(0.0, (current / high - 1.0) * 100.0)
    return float(value), None


def above_moving_average(series: Any, as_of: Any, sessions: int) -> tuple[bool | None, str | None]:
    """Whether the current close is strictly above its exact-session SMA."""

    if sessions <= 0:
        return None, "moving-average window must contain at least one session"
    values, reason = _window(series, as_of, sessions, label=f"{sessions}-session moving average")
    if values is None:
        return None, reason
    return bool(float(values.iloc[-1]) > float(values.mean())), None


def relative_strength_improving(
    stock: Any, sector: Any, as_of: Any, sessions: int
) -> tuple[bool | None, str | None]:
    """Whether stock/sector improved in the current window after a weak one."""

    if sessions <= 0:
        return None, "relative-strength window must contain at least one session"
    count = 2 * sessions + 1
    stock_values, stock_reason = _window(stock, as_of, count, label="relative-strength stock")
    if stock_values is None:
        return None, stock_reason
    sector_values, sector_reason = _window(sector, as_of, count, label="relative-strength sector")
    if sector_values is None:
        return None, sector_reason
    ratio = stock_values / sector_values
    current = _endpoint_return(ratio.iloc[sessions:], sessions)
    preceding = _endpoint_return(ratio.iloc[: sessions + 1], sessions)
    if current is None or preceding is None:
        return None, "relative-strength ratio has no valid endpoints"
    return bool(current > 0.0 and preceding <= 0.0), None



# ---------------------------------------------------------------------------
# Peer baskets. A sector ETF is cap-weighted, so for the largest names it is
# mostly the company itself (AAPL and MSFT are over a fifth of XLK). The peer
# basket is the other index members of the same sector, equally weighted, and
# never includes the company being measured.


def peer_window(frame: Any, peers: list[str], as_of: Any, count: int) -> tuple[pd.DataFrame | None, str | None]:
    """Peers' closes over exact sessions; a peer missing any session is dropped."""

    if not isinstance(frame, pd.DataFrame) or not peers:
        return None, "no peers in the sector"
    dates = exchange_sessions_ending(as_of, count)
    if len(dates) != count:
        return None, f"peer basket needs {count} exchange sessions"
    columns = [ticker for ticker in peers if ticker in frame.columns]
    if not columns:
        return None, "no priced peers in the sector"
    window = frame[columns].reindex(pd.DatetimeIndex(dates)).apply(pd.to_numeric, errors="coerce")
    complete = window.loc[:, window.notna().all() & (window > 0).all()]
    if complete.shape[1] == 0:
        return None, "no peer has every session in the window"
    return complete.astype(float), None


def peer_index(window: pd.DataFrame, exclude: str | None = None) -> pd.Series | None:
    """Equal-weight daily-rebalanced index of the peers, rebased to 1."""

    frame = window.drop(columns=[exclude]) if exclude in window.columns else window
    if frame.shape[1] == 0:
        return None
    daily = frame.pct_change().iloc[1:].mean(axis=1)
    return pd.concat([pd.Series([1.0], index=frame.index[:1]), (1.0 + daily).cumprod()])


def peer_median_return(window: pd.DataFrame, exclude: str | None = None) -> tuple[float | None, int]:
    """Median return of the peers over the window, in percent, and their count."""

    frame = window.drop(columns=[exclude]) if exclude in window.columns else window
    if frame.shape[1] == 0:
        return None, 0
    returns = (frame.iloc[-1] / frame.iloc[0] - 1.0) * 100.0
    return float(returns.median()), int(frame.shape[1])


def price_state(rs_improving: bool | None, above_ma: bool | None) -> str | None:
    """``stabilising`` needs both checks; either one failing is ``weak``.

    Relative strength against peers turning up and the close back above its
    average answer different questions (is it still losing to its peers; has
    the fall paused), so one without the other is not stabilisation.
    """

    if rs_improving is True and above_ma is True:
        return "stabilising"
    if rs_improving is False or above_ma is False:
        return "weak"
    return None


def expectation_reading(trend: Mapping[str, Any] | None, *, revision_pct: float,
                        min_analysts: int) -> dict[str, Any] | None:
    """What the FY1 consensus did over 30 and 90 days, and whether it is live.

    ``stale`` means nobody revised in 30 days and the number did not move: an
    estimate that stood still because no one looked is not the same as one
    that was checked and kept. ``thin`` means too few analysts for either.
    """

    if not trend:
        return None
    fy1 = trend.get("0y") if isinstance(trend, Mapping) else None
    if not isinstance(fy1, Mapping) or fy1.get("eps") is None:
        return None

    def change(old: Any) -> float | None:
        eps = fy1.get("eps")
        if old is None or eps is None or old == 0:
            return None
        return round((eps - old) / abs(old) * 100.0, 2)

    analysts = fy1.get("analysts")
    up, down = fy1.get("up_30d"), fy1.get("down_30d")
    change_30d, change_90d = change(fy1.get("eps_30d")), change(fy1.get("eps_90d"))
    if analysts is not None and analysts < min_analysts:
        state = "thin"
    elif (up or 0) + (down or 0) == 0 and change_30d == 0:
        state = "stale"
    elif change_30d is None:
        state = None
    elif change_30d <= -revision_pct:
        state = "cut"
    elif change_30d >= revision_pct:
        state = "raised"
    else:
        state = "steady"
    return {
        "fiscal_year_end": fy1.get("end"),
        "eps": fy1.get("eps"),
        "eps_30d": fy1.get("eps_30d"),
        "eps_90d": fy1.get("eps_90d"),
        "change_30d_pct": change_30d,
        "change_90d_pct": change_90d,
        "up_30d": up,
        "down_30d": down,
        "analysts": analysts,
        "low": fy1.get("low"),
        "high": fy1.get("high"),
        "state": state,
    }


def evidence(row: Mapping[str, Any], *, as_of: str, revision_pct: float,
             report_days: int) -> tuple[str, list[str], list[str]]:
    """Evidence for and against the business holding up, kept side by side.

    Nothing is weighed or netted. The state is ``deteriorating`` when any item
    is against, ``steady`` when nothing is against and the estimate is live,
    and ``unknown`` otherwise, so a name with no estimate data can never read
    as steady.
    """

    support: list[str] = []
    against: list[str] = []
    exp = row.get("expectations") or None
    if exp:
        fy = (exp.get("fiscal_year_end") or "")[:7] or "FY1"
        n = exp.get("analysts")
        who = f"{int(n)} analysts" if n is not None else "analyst count unknown"
        c30 = exp.get("change_30d_pct")
        if exp.get("state") == "cut":
            against.append(f"FY1 EPS (year to {fy}) cut {abs(c30):.1f}% in 30 days; {who}")
        elif exp.get("state") == "raised":
            support.append(f"FY1 EPS (year to {fy}) raised {c30:.1f}% in 30 days; {who}")
        elif exp.get("state") == "steady":
            support.append(f"FY1 EPS (year to {fy}) within ±{revision_pct:g}% over 30 days; {who}")
        up, down = exp.get("up_30d"), exp.get("down_30d")
        if up is not None and down is not None and down >= 3 and down >= 2 * max(up, 1):
            against.append(f"{int(down)} analysts revised down and {int(up)} up in 30 days")

    growth = row.get("revenue_growth_pct")
    filed = row.get("filed") or "unknown date"
    if growth is not None:
        (support if growth > 0 else against).append(
            f"Revenue {growth:+.1f}% y/y in the filing of {filed}")
    if row.get("fcf_positive") is True:
        support.append(f"Free cash flow positive (filing of {filed})")
    elif row.get("fcf_positive") is False:
        against.append(f"Free cash flow negative (filing of {filed})")

    reported = row.get("reported") or None
    if reported and reported.get("date") and reported.get("surprise_pct") is not None:
        age = (date.fromisoformat(as_of) - date.fromisoformat(reported["date"])).days
        if 0 <= age <= report_days:
            surprise = reported["surprise_pct"]
            (support if surprise >= 0 else against).append(
                f"EPS {'beat' if surprise >= 0 else 'missed'} consensus by {abs(surprise):.1f}% on {reported['date']}")

    live = bool(exp) and exp.get("state") in ("cut", "raised", "steady")
    if against:
        state = "deteriorating"
    elif live:
        state = "steady"
    else:
        state = "unknown"
    return state, support, against
