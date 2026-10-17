"""CATALYSTS: the NYSE session calendar and the events that follow rules.

Most events on the tab come from an agency's own calendar. A few are never
published as a calendar because they follow a fixed rule -- options expiry is
the third Friday, jobless claims print every Thursday -- and those are
generated here, marked ``rule`` so the page can say they were computed, not
announced. Holiday shifts that the rule itself defines are applied; one-off
changes (a national day of mourning) are not knowable in advance.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.easter import easter
import pandas as pd

from . import periods
from ..config import MARKET_TIMEZONE

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)
QUARTER_END_MONTHS = (3, 6, 9, 12)
VIX_EXPIRY_DAYS_BEFORE = 30
# Where SPX's settlement rule is published; the monthly and quarterly expiries share it.
SPX_OPTIONS_URL = "https://www.cboe.com/tradable_products/sp_500/spx_options/"
# Why an expiry morning can differ from the close: SPX AM settlement uses the opening prints.
SETTLEMENT = ("SPX standard options settle on the OPENING prices that morning (SET, AM-settled); "
              "SPXW and most ETF/equity options settle at the close.")
EXPIRY_RULES = ("monthly_opex", "quad_witching")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """NYSE rule: a Saturday holiday closes the Friday before, a Sunday one the Monday after."""
    if day.weekday() == SATURDAY:
        return day - timedelta(days=1)
    if day.weekday() == SUNDAY:
        return day + timedelta(days=1)
    return day


def nyse_holidays(year: int) -> dict[date, str]:
    holidays = {
        _nth_weekday(year, 1, MONDAY, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, MONDAY, 3): "Washington's Birthday",
        easter(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, MONDAY): "Memorial Day",
        _observed(date(year, 6, 19)): "Juneteenth",
        _observed(date(year, 7, 4)): "Independence Day",
        _nth_weekday(year, 9, MONDAY, 1): "Labor Day",
        _nth_weekday(year, 11, THURSDAY, 4): "Thanksgiving Day",
        _observed(date(year, 12, 25)): "Christmas Day",
    }
    # New Year's Day on a Saturday is not observed on the Friday before: NYSE
    # does not close on the last trading day of the year.
    new_year = date(year, 1, 1)
    if new_year.weekday() != SATURDAY:
        holidays[_observed(new_year)] = "New Year's Day"
    return holidays


def nyse_early_closes(year: int) -> dict[date, str]:
    """1:00 p.m. closes: the day before Independence Day, the day after
    Thanksgiving and Christmas Eve, when each is a weekday session."""
    holidays = nyse_holidays(year)
    candidates = {
        date(year, 7, 3): "Independence Day eve",
        _nth_weekday(year, 11, THURSDAY, 4) + timedelta(days=1): "Day after Thanksgiving",
        date(year, 12, 24): "Christmas Eve",
    }
    return {d: name for d, name in candidates.items() if d.weekday() < SATURDAY and d not in holidays}


# Closures no rule predicts, kept so a skipped day is not taken for a gap at the
# source. Add one when NYSE announces it.
SPECIAL_CLOSURES = {
    date(2025, 1, 9): "National Day of Mourning for President Carter",
}


def is_session(day: date) -> bool:
    return day.weekday() < SATURDAY and day not in nyse_holidays(day.year) and day not in SPECIAL_CLOSURES


def latest_completed_session(now: datetime | None = None) -> date:
    """Latest NYSE close, allowing fifteen minutes for the daily bars to settle.

    Use market time even when the runner is already on the next UTC day;
    weekends, holidays and 13:00 early closes share the existing calendar.
    """
    ny = (now or datetime.now(ZoneInfo(MARKET_TIMEZONE))).astimezone(ZoneInfo(MARKET_TIMEZONE))
    day = ny.date()
    settled = time(13, 15) if day in nyse_early_closes(day.year) else time(16, 15)
    if ny.time() < settled:
        day -= timedelta(days=1)
    while not is_session(day):
        day -= timedelta(days=1)
    return day


def sessions(start: date, end: date) -> list[date]:
    """NYSE sessions from ``start`` to ``end`` inclusive."""
    out, day = [], start
    while day <= end:
        if is_session(day):
            out.append(day)
        day += timedelta(days=1)
    return out


def next_sessions(after: date, count: int) -> list[date]:
    out, day = [], after
    while len(out) < count:
        day += timedelta(days=1)
        if is_session(day):
            out.append(day)
    return out


def _business_day(year: int, month: int, n: int) -> date:
    """The nth NYSE session of a month."""
    day, seen = date(year, month, 1), 0
    while True:
        if is_session(day):
            seen += 1
            if seen == n:
                return day
        day += timedelta(days=1)


def monthly_expiry(year: int, month: int) -> date:
    """Standard options expire on the third Friday, or the Thursday before when it is a holiday."""
    friday = _nth_weekday(year, month, FRIDAY, 3)
    return friday if is_session(friday) else friday - timedelta(days=1)


def _months(start: date, end: date):
    year, month = start.year, start.month
    while date(year, month, 1) <= end:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


EXPIRY_RULES_SHOWN = ("monthly_opex", "quad_witching", "vix_expiry")


def next_expiries(after: date) -> list[dict]:
    """The next monthly options expiry, quad witching and VIX expiry after
    ``after``, however far out: a reminder the calendar's window can't hide."""
    events = [e for e in rule_events(after + timedelta(days=1), after + timedelta(days=130))
              if e["rule"] in EXPIRY_RULES_SHOWN]
    first = {}
    for event in sorted(events, key=lambda e: e["date"]):
        first.setdefault(event["rule"], event)
    return [first[r] for r in EXPIRY_RULES_SHOWN if r in first]


def _week_shift(day: date) -> date:
    """A weekly release moves to the next session when its day is a holiday."""
    while not is_session(day):
        day += timedelta(days=1)
    return day


def rule_events(start: date, end: date) -> list[dict]:
    """Events defined by a rule, between ``start`` and ``end`` inclusive."""
    events = []

    def add(day, key, title, time, detail, url):
        if start <= day <= end:
            events.append({"source_id": "rule", "rule": key, "title": title, "date": day.isoformat(),
                           "time": time, "reference_period": None, "url": url, "detail": detail})

    for year, month in _months(start, end):
        expiry = monthly_expiry(year, month)
        if month in QUARTER_END_MONTHS:
            add(expiry, "quad_witching", "Quarterly options & futures expiry (quad witching)", "16:00",
                "Index futures, index options and single-stock options expire together. " + SETTLEMENT
                + " Index futures (ES/NQ) settle on the opening quotation; heavier volume, roll and "
                "rebalancing flows.", SPX_OPTIONS_URL)
            add(expiry, "sp_rebalance", "S&P 500 quarterly rebalance effective after the close", "16:00",
                "Share and float changes take effect after this close; the index deletes and adds "
                "announced beforehand trade in the closing auction.",
                "https://www.spglobal.com/spdji/en/governance/")
        else:
            add(expiry, "monthly_opex", "Monthly options expiry", "16:00",
                "Standard equity and index options expire. " + SETTLEMENT, SPX_OPTIONS_URL)
        # VIX: the Wednesday 30 days before the next month's standard expiry.
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        vix = monthly_expiry(next_year, next_month) - timedelta(days=VIX_EXPIRY_DAYS_BEFORE)
        add(vix if is_session(vix) else vix - timedelta(days=1), "vix_expiry", "VIX options & futures expiry",
            "09:30", "Settles on the opening prices of the SPX options used in the index.",
            "https://www.cboe.com/tradable_products/vix/")
        add(_business_day(year, month, 1), "ism_manufacturing", "ISM Manufacturing PMI", "10:00",
            "First business day of the month.", "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/")
        add(_business_day(year, month, 3), "ism_services", "ISM Services PMI", "10:00",
            "Third business day of the month.", "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/")

    day = start - timedelta(days=start.weekday())
    while day <= end:
        # Jobless claims: Thursday 8:30, moved to Wednesday in a Thursday-holiday week.
        thursday = day + timedelta(days=THURSDAY)
        claims = thursday if is_session(thursday) else thursday - timedelta(days=1)
        add(claims, "jobless_claims", "Initial jobless claims", "08:30", "Weekly, Department of Labor.",
            "https://www.dol.gov/ui/data.pdf")
        # EIA petroleum status: Wednesday 10:30, a day later when the week's Monday-Wednesday has a holiday.
        wednesday = day + timedelta(days=WEDNESDAY)
        holiday_week = any(not is_session(day + timedelta(days=k)) for k in range(MONDAY, THURSDAY))
        eia = _week_shift(wednesday + timedelta(days=1)) if holiday_week else wednesday
        add(eia, "eia_petroleum", "EIA weekly petroleum status (crude inventories)", "11:00" if holiday_week else "10:30",
            "Weekly; moves later in a holiday week.", "https://www.eia.gov/petroleum/supply/weekly/schedule.php")
        day += timedelta(days=7)
    return events


# --- Latest print of a FRED series ---------------------------------------------

TRANSFORMS = {
    "level": "",
    "yoy": "y/y",
    "mom": "m/m",
    "change": "change",
}


def latest_print(frame: pd.DataFrame, transform: str) -> dict | None:
    """The latest observation after ``transform``, with the period it covers.

    The period is shown beside the value because FRED updates after the
    agency does: until it has, the "latest" print is the one before, and the
    date says so.
    """
    series = periods.transform(frame.set_index("date")["value"], transform).dropna()
    if series.empty:
        return None
    return {"value": float(series.iloc[-1]), "period": series.index[-1].strftime("%Y-%m-%d")}


def earnings_importance(weight: float | None, high: float, medium: float) -> str:
    """By the company's weight in the index: a 1% name moves the index."""
    if weight is None:
        return "low"
    return "high" if weight >= high else "medium" if weight >= medium else "low"


RANK = {"low": 0, "medium": 1, "high": 2}


def stronger(*levels: str) -> str:
    """The most important of the given importance labels."""
    return max(levels, key=lambda level: RANK[level])


def theme_shares(groups: list[dict], caps: dict[str, float | None], key=lambda s: s) -> dict[str, dict]:
    """Each bellwether's share of its theme's bellwether market cap, the
    largest across the themes it is in: {key(symbol): {"theme", "label", "share"}}.

    A name outside the S&P 500 and Nasdaq-100 (an ADR such as TSM) has no index
    weight, so an index-weight rule calls the report of its theme's second
    largest company unimportant; its weight among its theme's names is the
    measure of how much it speaks for the theme. A theme with fewer than three
    names with a cap gives no shares: a share of two is not a ranking."""
    out: dict[str, dict] = {}
    for spec in groups:
        names = [s for s in spec.get("bellwethers") or [] if caps.get(s)]
        if len(names) < 3:
            continue
        total = sum(caps[s] for s in names)
        for symbol in names:
            share = caps[symbol] / total
            held = out.get(key(symbol))
            if held is None or share > held["share"]:
                out[key(symbol)] = {"theme": spec["key"], "label": spec["label"], "share": share}
    return out


def theme_importance(share: float | None, high: float, medium: float) -> str:
    """By the share of the theme's bellwether market cap."""
    if share is None:
        return "low"
    return "high" if share >= high else "medium" if share >= medium else "low"


# --- Expiry after a large move ---------------------------------------------------

def recent_shock(closes: pd.DataFrame, session: date, *, funds: list[str], lookback: int, window: int,
                 z_limit: float) -> dict | None:
    """The largest close-to-close move by any of ``funds`` in the last ``lookback``
    sessions up to ``session`` that is beyond ``z_limit`` of that fund's own volatility.

    The volatility is the standard deviation of the ``window`` daily returns before
    the move, so a move does not count itself. A missing close leaves its return
    and the next one unknown, and a window with a gap in it is not used.
    """
    best, best_z = None, 0.0
    for fund in funds:
        if fund not in closes.columns:
            continue
        close = closes[fund]
        close = close[[d <= session for d in pd.to_datetime(close.index).date]]
        returns = close / close.shift(1) - 1
        for position in range(max(0, len(returns) - lookback), len(returns)):
            day_return = returns.iloc[position]
            past = returns.iloc[max(0, position - window):position].dropna()
            if pd.isna(day_return) or len(past) < window:
                continue
            sigma = float(past.std())
            if not sigma > 0:
                continue
            z = float(day_return) / sigma
            # Compare the unrounded z: the stored one is rounded, and a tie should keep the first fund.
            if abs(z) > z_limit and (best is None or abs(z) > abs(best_z)):
                best_z = z
                best = {"fund": fund, "date": pd.Timestamp(returns.index[position]).strftime("%Y-%m-%d"),
                        "return_pct": round(float(day_return) * 100, 2), "z": round(z, 2)}
    return best


def expiry_watch(events: list[dict], closes: pd.DataFrame, session: date, settings: dict) -> None:
    """Flag each monthly or quarterly expiry within the next few sessions when a
    large move in the broad market came just before it, with the move that did it.

    Descriptive only: the flag tells a reader what the market has just done, and
    the page says that expiry is not a directional signal.
    """
    shock = recent_shock(closes, session, funds=list(settings["expiry_watch_funds"]),
                         lookback=int(settings["expiry_shock_lookback_sessions"]),
                         window=int(settings["expiry_shock_window_sessions"]),
                         z_limit=float(settings["expiry_shock_z"]))
    if shock is None:
        return
    soon = {d.isoformat() for d in next_sessions(session, int(settings["expiry_watch_sessions"]))}
    for event in events:
        if event.get("rule") in EXPIRY_RULES and event["date"] in soon:
            event["expiry_watch"] = dict(shock)
