"""Baskets of names totalled the way an index is: price, trailing P/E, earnings.

Each name's weekly close and earnings yield come from its VALUATION artifact
(artifacts/valuation/<T>.json: ``dates``, ``close`` -- split-adjusted, what a
multiple is quoted on -- and ``ey``, the TTM EPS on the name's lead basis over
that close, in percent, losses included). A basket holds its names one of two
ways:

    weights given   fixed share counts set from today's weights (market caps,
                    or a fund's holding weights) and held backwards, as an
                    index holds its members between rebalances
    weights None    equal value in every priced name, rebalanced each week

and is totalled each week:

    price      chained: each week's return over the names priced both weeks,
               weighted by their value the week before; =100 at the start.
               Price only, no dividends.
    pe         total value over total earnings (value x earnings yield) of the
               names with an earnings yield, drawn when they hold at least
               ``min_coverage`` of the priced value and the total is positive.
               Losses count, as in an index's own P/E.
    earnings   price / pe, =100 at the first week with a P/E: the earnings the
               price index stands for. price = pe x earnings holds exactly, so
               the ratio of two baskets splits the same way into a ratio of
               multiples and a ratio of earnings.

Members and weights are today's throughout: a name that left the index is not
in its past (survivorship), as for the sector P/E.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DEFAULT_MIN_COVERAGE = 0.8
MIN_STAT_WEEKS = 104
QUANTILES = {"p10": 0.10, "p25": 0.25, "median": 0.50, "p75": 0.75, "p90": 0.90}


def read_history(directory: Path, ticker: str) -> dict | None:
    try:
        return json.loads((directory / f"{ticker}.json").read_text())
    except (OSError, ValueError):
        return None


def _weekly(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per week (W-FRI): each column's last value that week, dated by
    the week's last session any column has."""
    if frame.empty:
        return frame
    frame = frame.sort_index()
    periods = frame.index.to_period("W-FRI")
    out = frame.groupby(periods).last()
    labels = pd.Series(frame.index, index=frame.index).groupby(periods).max()
    out.index = pd.DatetimeIndex(labels.loc[out.index].to_numpy())
    return out


def frames(histories: dict[str, dict | None]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Weekly closes and earnings yields (percent), one column per name. A name
    whose artifact predates the close/ey fields is left out."""
    closes, yields = {}, {}
    for ticker, history in histories.items():
        if not history or not history.get("dates") or not history.get("close") or not history.get("ey"):
            continue
        index = pd.to_datetime(history["dates"])
        closes[ticker] = pd.Series(history["close"], index=index, dtype=float)
        yields[ticker] = pd.Series(history["ey"], index=index, dtype=float)
    if not closes:
        return pd.DataFrame(), pd.DataFrame()
    return _weekly(pd.DataFrame(closes)), _weekly(pd.DataFrame(yields))


def basket(closes: pd.DataFrame, yields: pd.DataFrame, weights: dict[str, float] | None = None,
           *, min_coverage: float = DEFAULT_MIN_COVERAGE) -> pd.DataFrame | None:
    """Weekly price, pe, earnings, coverage and names for one basket (see the
    module note). ``weights`` maps ticker -> today's weight in any unit; None
    is equal weight. Names absent from the frames are absent from the basket."""
    if weights is None:
        columns = list(closes.columns)
    else:
        columns = [t for t in closes.columns if (weights.get(t) or 0) > 0]
    if not columns:
        return None
    c = closes[columns]
    e = yields.reindex(index=c.index, columns=columns)
    if weights is None:
        value = c.notna().astype(float).where(c.notna())
    else:
        last = c.ffill().iloc[-1]
        shares = pd.Series({t: float(weights[t]) for t in columns}) / last
        value = c * shares
    returns = c / c.shift(1) - 1
    before = value.shift(1)
    both = returns.notna() & before.notna()
    step = (returns.where(both) * before.where(both)).sum(axis=1, min_count=1) / before.where(both).sum(axis=1, min_count=1)
    step = step.fillna(0.0)
    step.iloc[0] = 0.0
    price = 100 * (1 + step).cumprod()

    priced = value.sum(axis=1, min_count=1)
    has = value.notna() & e.notna()
    covered = value.where(has).sum(axis=1, min_count=1)
    total_earnings = (value * e / 100).where(has).sum(axis=1, min_count=1)
    coverage = covered / priced
    pe = (covered / total_earnings).where((total_earnings > 0) & (coverage >= min_coverage))
    earnings = price / pe
    first = earnings.first_valid_index()
    if first is not None:
        earnings = 100 * earnings / earnings.loc[first]
    out = pd.DataFrame({"price": price, "pe": pe, "earnings": earnings, "coverage": coverage,
                        "names": has.sum(axis=1)})
    return out.loc[priced.notna()]


def stats(pe: pd.Series, *, min_weeks: int = MIN_STAT_WEEKS) -> dict | None:
    """Where the latest weekly P/E sits among all the weeks given."""
    valid = pe.dropna()
    if len(valid) < min_weeks:
        return None
    current = pe.iloc[-1]
    out = {name: float(valid.quantile(q)) for name, q in QUANTILES.items()}
    out |= {
        "current": None if pd.isna(current) else float(current),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "weeks": int(len(valid)),
        "first": valid.index[0].strftime("%Y-%m-%d"),
        "percentile": None if pd.isna(current) else float((valid <= current).mean() * 100),
    }
    out["vs_median"] = None if out["current"] is None else (out["current"] / out["median"] - 1) * 100
    return out


def payload(frame: pd.DataFrame | None, *, years: int | None = None) -> dict | None:
    """The basket as JSON lists (dates, price, pe, earnings, coverage) plus the
    P/E's stats; None when it never had a P/E."""
    if frame is None or frame.empty or frame["pe"].dropna().empty:
        return None
    if years:
        frame = frame[frame.index > frame.index[-1] - pd.DateOffset(years=years)]

    def rounded(series: pd.Series, digits: int) -> list:
        return [None if pd.isna(v) else round(float(v), digits) for v in series.to_numpy()]

    summary = stats(frame["pe"])
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in frame.index],
        "price": rounded(frame["price"], 2),
        "pe": rounded(frame["pe"], 2),
        "earnings": rounded(frame["earnings"], 2),
        "coverage": rounded(frame["coverage"], 3),
        "names": int(frame["names"].iloc[-1]),
        "stats": None if summary is None else {k: (round(v, 2) if isinstance(v, float) else v) for k, v in summary.items()},
    }


# --- What the market expects of a basket, today -------------------------------
# From VALUATION's rows (consensus per-share EPS, price, market cap, TTM revenue
# growth from filings). Each name is held at its value in the basket (market cap,
# a fund's holding weight, or equal value), so a name's earnings in the basket are
# value x EPS / price -- the same totalling as the P/E above, on today's figures.

def _held(rows: dict[str, dict], values: dict[str, float] | None) -> dict[str, float]:
    if values is None:
        return {t: 1.0 for t in rows}
    return {t: float(values[t]) for t in rows if (values.get(t) or 0) > 0}


def outlook(rows: dict[str, dict], values: dict[str, float] | None = None, revenue: dict[str, float] | None = None,
            *, min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    """Forward P/E (next twelve months), consensus EPS growth this fiscal year
    (over last year's actual) and next (over this year), and TTM revenue growth,
    for one basket; each None when the names it needs hold less than
    ``min_coverage`` of the basket's value.

    ``rows`` maps ticker -> VALUATION row; ``values`` ticker -> value held (None:
    equal value); ``revenue`` ticker -> its latest annual revenue, which weights
    the names' revenue growth (so the figure is the basket's total revenue
    growth, near enough, not an average of percentages).
    """
    held = _held(rows, values)
    total = sum(held.values())
    out: dict = {"forward_pe": None, "eps_growth_this": None, "eps_growth_next": None, "revenue_growth": None,
                 "names": len(held)}
    if not total:
        return out

    def earnings(field: str) -> dict[str, float]:
        found = {}
        for ticker, value in held.items():
            row = rows[ticker]
            eps, price = row.get(field), row.get("price")
            if eps is not None and price:
                found[ticker] = value * eps / price
        return found

    def covers(names) -> bool:
        return sum(held[t] for t in names) / total >= min_coverage

    ntm = earnings("eps_ntm")
    if ntm and covers(ntm) and sum(ntm.values()) > 0:
        out["forward_pe"] = sum(held[t] for t in ntm) / sum(ntm.values())

    def growth(before: dict[str, float], after: dict[str, float]) -> float | None:
        both = [t for t in before if t in after]
        start = sum(before[t] for t in both)
        if not both or not covers(both) or start <= 0:
            return None
        return (sum(after[t] for t in both) / start - 1) * 100

    prev, fy0, fy1 = earnings("eps_fy_prev"), earnings("eps_fy0"), earnings("eps_fy1")
    out["eps_growth_this"] = growth(prev, fy0)
    out["eps_growth_next"] = growth(fy0, fy1)

    if revenue:
        weights, rates = {}, {}
        for ticker, value in held.items():
            row = rows[ticker]
            rate, cap, sales = row.get("revenue_growth"), row.get("market_cap"), revenue.get(ticker)
            if rate is not None and cap and sales and sales > 0:
                weights[ticker] = value / cap * sales      # the basket's share of the name's revenue
                rates[ticker] = rate
        if weights and covers(weights):
            out["revenue_growth"] = sum(weights[t] * rates[t] for t in weights) / sum(weights.values())
    return out


def latest_revenue(directory: Path, ticker: str) -> float | None:
    """A name's latest annual revenue from its FINANCIALS artifact, or None."""
    try:
        body = json.loads((directory / f"{ticker}.json").read_text())
    except (OSError, ValueError):
        return None
    values = [v for v in ((body.get("values") or {}).get("revenue") or []) if v is not None]
    return float(values[-1]) if values else None


# --- Fundamentals by fiscal year ------------------------------------------------
# From each name's FINANCIALS artifact (annual statements as filed: ``columns``
# with each fiscal_year, ``values`` with revenue, gross_profit, ebit per year).
# A basket holds a fraction of each company (its value held over its market
# cap: 1 for a sector holding the whole company, a fund's weight over the cap
# for a fund), and its figures are totals of those fractions -- revenue growth
# is the basket's total revenue against the year before over the names reported
# both years, margins are total profit over total revenue. Each company's
# fiscal year is its own, so a year mixes year-ends.

HISTORY_YEARS = 10


def read_statements(directory: Path, ticker: str) -> dict | None:
    try:
        return json.loads((directory / f"{ticker}.json").read_text())
    except (OSError, ValueError):
        return None


def _by_year(statement: dict, field: str) -> dict[int, float]:
    years = [c.get("fiscal_year") for c in statement.get("columns") or []]
    values = (statement.get("values") or {}).get(field) or []
    return {int(y): float(v) for y, v in zip(years, values) if y is not None and v is not None}


def _field(statement: dict, field: str, fallbacks: tuple = ()) -> dict[int, float]:
    """A field by year, filled where it is missing from the first fallback that
    has it (a fallback is a field name, or a function of the statement)."""
    out = _by_year(statement, field)
    for fallback in fallbacks:
        extra = fallback(statement) if callable(fallback) else _by_year(statement, fallback)
        for year, value in extra.items():
            out.setdefault(year, value)
    return out


def _gross_from_cost(statement: dict) -> dict[int, float]:
    revenue, cost = _by_year(statement, "revenue"), _by_year(statement, "cost_of_revenue")
    return {y: revenue[y] - cost[y] for y in revenue if y in cost}


def fundamentals_history(statements: dict[str, dict | None], fractions: dict[str, float],
                         *, years: int = HISTORY_YEARS, min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict | None:
    """{years, revenue_growth, gross_margin, operating_margin} in percent, one
    entry per fiscal year (last ``years``), each None when the names it needs
    carry less than ``min_coverage`` of the basket's revenue that year.

    ``statements`` maps ticker -> FINANCIALS artifact; ``fractions`` ticker -> the
    share of the company the basket holds (1.0 for the whole company).

    Gross profit is revenue less cost of revenue where a company tags no gross
    profit; operating profit is pre-tax income where it reports no operating
    line (banks, insurers). A year some companies have not reported yet is
    measured against their previous year's revenue, so a half-filed year fails
    the coverage test instead of standing for the few that filed.
    """
    names = {t: f for t, f in fractions.items() if f and f > 0 and statements.get(t)}
    if not names:
        return None
    revenue = {t: _by_year(statements[t], "revenue") for t in names}
    gross = {t: _field(statements[t], "gross_profit", (_gross_from_cost,)) for t in names}
    operating = {t: _field(statements[t], "ebit", ("pretax_income",)) for t in names}
    every = sorted({y for r in revenue.values() for y in r})
    if not every:
        return None
    span = every[-years:]

    def scale(t: str, year: int) -> float:
        """The company's revenue that year, or the year before when it has not reported."""
        value = revenue[t].get(year)
        if value is None or value <= 0:
            value = revenue[t].get(year - 1)
        return names[t] * value if value and value > 0 else 0.0

    def coverage(year: int, tickers: list[str]) -> float:
        base = sum(scale(t, year) for t in names)
        return sum(names[t] * revenue[t][year] for t in tickers) / base if base else 0.0

    out = {"years": span, "revenue_growth": [], "gross_margin": [], "operating_margin": []}
    for year in span:
        both = [t for t in names if revenue[t].get(year, 0) > 0 and revenue[t].get(year - 1, 0) > 0]
        growth = None
        if both and coverage(year, both) >= min_coverage:
            growth = (sum(names[t] * revenue[t][year] for t in both) / sum(names[t] * revenue[t][year - 1] for t in both) - 1) * 100
        out["revenue_growth"].append(None if growth is None else round(growth, 1))
        for key, field in (("gross_margin", gross), ("operating_margin", operating)):
            tickers = [t for t in names if revenue[t].get(year, 0) > 0 and year in field[t]]
            margin = None
            if tickers and coverage(year, tickers) >= min_coverage:
                margin = sum(names[t] * field[t][year] for t in tickers) / sum(names[t] * revenue[t][year] for t in tickers) * 100
            out[key].append(None if margin is None else round(margin, 1))
    return out
