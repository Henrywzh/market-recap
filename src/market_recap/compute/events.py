"""Earnings event cards: what a report is priced for, what it has moved, and
who has moved with it.

Every figure here is a description of the past or of a price today, never a
forecast:

- Read-through is measured, not listed by hand. Candidates are the names
  whose daily returns in excess of the index were most correlated with the
  company's over the last year; each is then scored on the company's own
  reaction sessions only: beta = sum(peer * company) / sum(company^2) on the
  excess moves, and the share of those sessions on which the two moved the
  same way. Eight reports is a small sample and the card says how many.
- Index impact is weight x move: the index points one name's report is worth
  at the implied move (or, without an options quote, its average move).
- The consensus is Yahoo's current-quarter row, used only when its fiscal
  period ends in the month the calendar's fiscal quarter names -- after a
  report Yahoo rolls that row to the next quarter, and a card that mixed the
  two would compare an actual with the wrong estimate.
"""

from __future__ import annotations

from datetime import date, timedelta
import math

import pandas as pd

MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def daily_excess(closes: pd.DataFrame, index_close: pd.Series) -> pd.DataFrame:
    """Each column's one-session return minus the index's, in percent.

    A missing print stays missing: the session after it is not a one-day move.
    """
    returns = closes.pct_change(fill_method=None) * 100
    market = index_close.reindex(closes.index).pct_change(fill_method=None) * 100
    return returns.sub(market, axis=0)


def candidates(corr: pd.DataFrame, symbol: str, *, count: int, same_issuer: set[str]) -> list[tuple[str, float]]:
    """The ``count`` names most correlated with ``symbol``, another share
    class of the same issuer excluded (GOOG moves with GOOGL by construction)."""
    if symbol not in corr.columns:
        return []
    row = corr[symbol].drop(labels=[symbol, *same_issuer], errors="ignore").dropna()
    row = row[row > 0].sort_values(ascending=False).head(count)
    return [(str(s), float(v)) for s, v in row.items()]


def co_move(leader: list[float | None], follower: list[float | None], *, min_reports: int) -> dict | None:
    """How ``follower`` moved on the sessions ``leader`` reacted to its own report."""
    pairs = [(a, b) for a, b in zip(leader, follower)
             if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    if len(pairs) < min_reports:
        return None
    denominator = sum(a * a for a, _ in pairs)
    if denominator == 0:
        return None
    signed = [(a, b) for a, b in pairs if a != 0 and b != 0]
    return {
        "n": len(pairs),
        "beta": round(sum(a * b for a, b in pairs) / denominator, 2),
        "hit": round(sum((a > 0) == (b > 0) for a, b in signed) / len(signed), 2) if signed else None,
        "mean_abs": round(sum(abs(b) for _, b in pairs) / len(pairs), 2),
    }


def moves_on(excess: pd.DataFrame, symbol: str, sessions: list[str]) -> list[float | None]:
    """``symbol``'s excess move on each session, None where it did not trade."""
    if symbol not in excess.columns:
        return [None] * len(sessions)
    column = excess[symbol]
    out = []
    for session in sessions:
        stamp = pd.Timestamp(session)
        value = column.get(stamp) if stamp in column.index else None
        out.append(None if value is None or pd.isna(value) else float(value))
    return out


def index_impact(weights: dict[str, float | None], move_pct: float | None) -> dict[str, dict]:
    """Index points (in percent) that one name's move is worth, per index."""
    if move_pct is None:
        return {}
    return {key: {"weight": round(w, 3), "points_pct": round(w * move_pct / 100, 2)}
            for key, w in weights.items() if w}


def quarter_matches(period_end: str | None, fiscal_quarter: str | None) -> bool:
    """Yahoo's period end against Nasdaq's "Aug/2026". Unknown on either side
    counts as a match only when the calendar names no quarter at all."""
    if not period_end:
        return False
    if not fiscal_quarter:
        return True
    try:
        month, year = fiscal_quarter.split("/")
        end = date.fromisoformat(period_end[:10])
    except (ValueError, AttributeError):
        return False
    return MONTHS.get(month[:3].title()) == end.month and int(year) == end.year


def consensus(trend: dict | None, event: dict) -> dict:
    """The quarter's estimates: Nasdaq's EPS point, and Yahoo's range, revenue
    and revisions when Yahoo's row is the same fiscal quarter."""
    out = {
        "fiscal_quarter": event.get("fiscal_quarter"),
        "eps": event.get("eps_forecast"),
        "eps_estimates": event.get("estimates"),
        "eps_year_ago": event.get("last_year_eps"),
        "source": "nasdaq",
    }
    row = (trend or {}).get("0q")
    if row and quarter_matches(row.get("end"), event.get("fiscal_quarter")):
        eps_30d = row.get("eps_30d")
        out.update({
            "source": "nasdaq + yahoo",
            "period_end": row.get("end"),
            "eps_yahoo": row.get("eps"),
            "eps_low": row.get("low"),
            "eps_high": row.get("high"),
            "eps_change_30d_pct": round(100 * (row["eps"] / eps_30d - 1), 2) if row.get("eps") and eps_30d else None,
            "up_30d": row.get("up_30d"),
            "down_30d": row.get("down_30d"),
            "analysts": row.get("analysts"),
            "revenue": row.get("revenue"),
            "revenue_low": row.get("revenue_low"),
            "revenue_high": row.get("revenue_high"),
            "revenue_year_ago": row.get("revenue_year_ago"),
            "revenue_growth_pct": round(100 * (row["revenue"] / row["revenue_year_ago"] - 1), 1)
            if row.get("revenue") and row.get("revenue_year_ago") else None,
        })
        if out["eps_year_ago"] is None:
            out["eps_year_ago"] = row.get("year_ago_eps")
    eps, year_ago = out.get("eps"), out.get("eps_year_ago")
    out["eps_growth_pct"] = round(100 * (eps / year_ago - 1), 1) if eps is not None and year_ago and year_ago > 0 else None
    return out


def _ret(series: pd.Series, sessions: int) -> float | None:
    s = series.dropna()
    if len(s) <= sessions:
        return None
    return round(100 * (s.iloc[-1] / s.iloc[-1 - sessions] - 1), 2)


def setup(close: pd.Series, sector_close: pd.Series | None) -> dict:
    """Where the stock stands going into the report."""
    s = close.dropna()
    if s.empty:
        return {}
    last = s.iloc[-1]
    year = s.iloc[-252:]
    ma50 = s.iloc[-50:].mean() if len(s) >= 50 else None
    out = {
        "ret_5d": _ret(s, 5),
        "ret_20d": _ret(s, 20),
        "from_high_pct": round(100 * (last / year.max() - 1), 2),
        "above_50d": None if ma50 is None else bool(last > ma50),
    }
    if sector_close is not None:
        sector = _ret(sector_close, 20)
        out["vs_sector_20d"] = None if sector is None or out["ret_20d"] is None else round(out["ret_20d"] - sector, 2)
    return out


def reaction_session(report: date, timing: str | None, sessions: list[date]) -> date | None:
    """The first session that trades on a report: the next one after an
    after-close report, the report day itself otherwise."""
    for day in sessions:
        if (timing == "amc" and day > report) or (timing != "amc" and day >= report):
            return day
    return None


def pre_event_day(report: date, timing: str | None) -> date:
    """The last day whose afternoon options snapshot precedes the report."""
    if timing == "amc":
        return report
    day = report - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day
