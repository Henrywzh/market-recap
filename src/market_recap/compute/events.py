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


# --- Report history ---------------------------------------------------------------
# What each past report was measured against and what followed. The guide a
# release gives is checked against the company's own last quarter before it
# is shown: a quarterly guide sits near it, a full-year one near four times it,
# and anything else is a segment line or a misread and is dropped.
# Micron guided $50bn after a $23.9bn quarter: a boom can double a quarter,
# so the quarterly band runs to 2.8x; a full year is 3-6 quarters' worth.
QUARTER_GUIDE_RATIO = (0.4, 2.8)
YEAR_GUIDE_RATIO = (3.0, 6.0)
DRIFT_SESSIONS = (5, 20)


def _mid(low: float | None, high: float | None) -> float | None:
    return None if low is None or high is None else (low + high) / 2


def guide_horizon(mid: float | None, reference: float | None) -> str | None:
    """'quarter', 'year' or None (not a guide this company could give)."""
    if mid is None or not reference or reference <= 0 or mid <= 0:
        return None
    ratio = mid / reference
    if QUARTER_GUIDE_RATIO[0] <= ratio <= QUARTER_GUIDE_RATIO[1]:
        return "quarter"
    if YEAR_GUIDE_RATIO[0] <= ratio <= YEAR_GUIDE_RATIO[1]:
        return "year"
    return None


def checked_guide(outlook: dict | None, revenue_ref: float | None, eps_ref: float | None) -> dict | None:
    """The outlook's figures that pass the scale check, each with its horizon."""
    if not outlook:
        return None
    out: dict = {}
    horizon = guide_horizon(_mid(outlook.get("revenue_low"), outlook.get("revenue_high")), revenue_ref)
    if horizon:
        out |= {"revenue_low": outlook["revenue_low"], "revenue_high": outlook["revenue_high"], "revenue_horizon": horizon}
    if outlook.get("revenue_growth_low") is not None:
        out |= {"revenue_growth_low": outlook["revenue_growth_low"], "revenue_growth_high": outlook["revenue_growth_high"]}
    eps_mid = _mid(outlook.get("eps_low"), outlook.get("eps_high"))
    # EPS can be small or negative; a quarterly guide is still within a few
    # times the last quarter's, a full-year one within a few times four.
    horizon = guide_horizon(abs(eps_mid), abs(eps_ref)) if eps_mid is not None and eps_ref else None
    if horizon:
        out |= {"eps_low": outlook["eps_low"], "eps_high": outlook["eps_high"], "eps_horizon": horizon}
    if not out:
        return None
    if outlook.get("gross_margin_pct") is not None:
        out["gross_margin_pct"] = outlook["gross_margin_pct"]
    return out | {"period": outlook.get("period"), "quote": outlook.get("quote")}


def drift(close: pd.Series, index_close: pd.Series, session: str, sessions: int) -> float | None:
    """Excess return over the index from the reaction session's close to
    ``sessions`` later: whether the first day's move carried on or reversed."""
    close, index_close = close.dropna(), index_close.reindex(close.index).ffill()
    day = pd.Timestamp(session)
    if day not in close.index:
        return None
    at = close.index.get_loc(day)
    if at + sessions >= len(close):
        return None
    stock = close.iloc[at + sessions] / close.iloc[at] - 1
    market = index_close.iloc[at + sessions] / index_close.iloc[at] - 1
    return round((stock - market) * 100, 2)


def report_history(reactions: list[dict], calendar: dict[str, dict], guides: dict[str, dict],
                   close: pd.Series, index_close: pd.Series) -> list[dict]:
    """Newest first: each past report's EPS against consensus, the guide it
    gave, the first session's move and the drift after it."""
    rows = []
    for r in reactions:
        cal = calendar.get(r["date"]) or {}
        row = {
            "date": r["date"], "session": r.get("session"), "timing": r.get("timing"),
            "fiscal_quarter": cal.get("fiscal_quarter"),
            "eps_consensus": cal.get("eps_forecast"), "eps": cal.get("eps"), "surprise_pct": cal.get("surprise_pct"),
            "move_pct": r.get("move_pct"), "excess_pct": r.get("excess_pct"),
            "guide": guides.get(r["date"]),
        }
        for n in DRIFT_SESSIONS:
            row[f"drift_{n}d"] = drift(close, index_close, r["session"], n) if r.get("session") else None
        rows.append(row)
    # Each guide against what the company then reported for that quarter.
    for newer, older in zip(rows, rows[1:]):
        guide = older.get("guide") or {}
        mid = _mid(guide.get("eps_low"), guide.get("eps_high"))
        if guide.get("eps_horizon") == "quarter" and mid and newer.get("eps") is not None:
            older["next_eps_vs_guide_pct"] = round((newer["eps"] / mid - 1) * 100, 1) if mid > 0 else None
    return rows


def history_summary(rows: list[dict]) -> dict:
    """What the history says in one line each: how often it beat, how the
    stock answered a beat, and whether the first day's move lasted."""
    beats = [r for r in rows if r.get("surprise_pct") is not None]
    moved = [r for r in rows if r.get("excess_pct") is not None]
    carried = [r for r in rows if r.get("excess_pct") and r.get("drift_20d") is not None]
    out = {
        "reports": len(rows),
        "beats": sum(r["surprise_pct"] > 0 for r in beats), "measured": len(beats),
        "median_surprise_pct": round(float(pd.Series([r["surprise_pct"] for r in beats]).median()), 1) if beats else None,
        "beat_and_fell": sum(r["surprise_pct"] > 0 and (r.get("excess_pct") or 0) < 0 for r in beats),
        "up": sum(r["excess_pct"] > 0 for r in moved),
        # A 20-session drift the same way as the first day: the move held.
        "held_20d": sum(math.copysign(1, r["excess_pct"]) == math.copysign(1, r["drift_20d"]) for r in carried),
        "drift_measured": len(carried),
    }
    beat_own = [r["next_eps_vs_guide_pct"] for r in rows if r.get("next_eps_vs_guide_pct") is not None]
    out["beat_own_guide"] = sum(v > 0 for v in beat_own)
    out["guides_checked"] = len(beat_own)
    return out


def against_guide(guide: dict | None, consensus: dict) -> dict | None:
    """Where the street sits against the company's own guide for the quarter
    now being reported: above the top of the range is a high bar."""
    if not guide:
        return None
    out = {}
    for key, value in (("eps", consensus.get("eps")), ("revenue", consensus.get("revenue"))):
        low, high = guide.get(f"{key}_low"), guide.get(f"{key}_high")
        if guide.get(f"{key}_horizon") != "quarter" or value is None or low is None:
            continue
        mid = (low + high) / 2
        out[key] = {"low": low, "high": high, "consensus": value,
                    "vs_mid_pct": round((value / mid - 1) * 100, 1) if mid else None,
                    "position": "above" if value > high else "below" if value < low else "inside"}
    return out or None


REVISION_WINDOWS = (("7d", "eps_7d"), ("30d", "eps_30d"), ("60d", "eps_60d"), ("90d", "eps_90d"))
REVISION_PERIODS = (("0q", "This quarter"), ("+1q", "Next quarter"), ("0y", "This year"), ("+1y", "Next year"))


def revision_table(trend: dict | None) -> list[dict]:
    """Each period's consensus now and its change over 7/30/60/90 days."""
    rows = []
    for period, label in REVISION_PERIODS:
        row = (trend or {}).get(period) or {}
        now = row.get("eps")
        if now is None:
            continue
        changes = {}
        for window, key in REVISION_WINDOWS:
            then = row.get(key)
            changes[window] = round((now / then - 1) * 100, 1) if then and then > 0 and now > 0 else None
        spread = (row["high"] - row["low"]) / abs(now) * 100 if row.get("high") is not None and row.get("low") is not None and now else None
        rows.append({"period": period, "label": label, "end": row.get("end"), "eps": now, "changes": changes,
                     "up_30d": row.get("up_30d"), "down_30d": row.get("down_30d"), "analysts": row.get("analysts"),
                     "spread_pct": None if spread is None else round(spread, 1)})
    return rows
