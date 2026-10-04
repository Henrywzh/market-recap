"""CHAIN: how a report travels along the AI supply chain.

A report is news at one instant; each company in the chain trades it on its
own exchange's first session that closes after that instant. A Tokyo Electron
release at 15:30 Tokyo time is traded by Tokyo's next session and by New
York's session the same calendar day; an NVIDIA release after New York's
close is traded by Seoul and Tokyo the next morning, and by New York the next
day. So every move here is a session close-to-close move beyond the
company's own market index, on the session its exchange first had the news.

Four questions are asked of every ordered pair (the company that reported,
then a company linked to it), each over every report since the price history
allows:

1. immediate -- did the linked company move the same way on the session it
   first traded the report?
2. fundamental -- when the reporter beat consensus, did the linked company
   beat too, at its own next report?
3. drift -- from the session after, until the linked company's own report,
   did it keep moving the way the reporter's stock had?
4. priced in -- the linked company's moves on all its partners' report days
   this season, before its own report: did a larger run-up mean a weaker
   reaction to its own report?

A lead's report pairs with every follower at once, so pairs are not
independent: every t-statistic here is taken across lead reports (each
report's followers averaged first), never across pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# A follower's own report counts for the drift and fundamental questions when
# it comes this many days or fewer after the lead's.
FOLLOW_DAYS = 100
# A season's reports: from a week after the calendar quarter ends, for three months.
SEASON_START_DAYS = 7
# Surprises are clipped here for means: a tiny EPS base makes -900% out of a cent.
SURPRISE_CLIP = 50.0
# Tokyo's cash session has closed at 15:30 since 2024-11-05, at 15:00 before.
TOKYO_LONGER = date(2024, 11, 5)


@dataclass(frozen=True)
class Market:
    key: str
    tz: str
    close: time
    index: str
    # When a report's time of day is unknown: before this exchange's open
    # ("bmo") or after its close ("amc"), the local custom.
    unknown: str

    def close_at(self, day: date) -> datetime:
        close = self.close
        if self.key == "JP" and day < TOKYO_LONGER:
            close = time(15, 0)
        return datetime.combine(day, close, tzinfo=ZoneInfo(self.tz))


def market_from(key: str, spec: dict) -> Market:
    hh, mm = (int(p) for p in str(spec["close"]).split(":"))
    return Market(key, spec["tz"], time(hh, mm), spec["index"], spec.get("unknown", "amc"))


def info_time(report: dict, market: Market) -> pd.Timestamp:
    """The instant a report became public, in UTC. A report with no clock
    time takes ``market``'s custom -- the market the company releases in,
    which for an ADR is its home one: early morning, or just after the
    close, on its local date."""
    ts = pd.Timestamp(report["ts"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    timing = report.get("timing")
    if report.get("timed", True) and not timing:
        return ts.tz_convert("UTC")
    local = pd.Timestamp(report["local"]) if report.get("local") else ts.tz_convert(market.tz)
    day = local.date()
    timing = timing or market.unknown
    zone = ZoneInfo(market.tz)
    if timing == "bmo":
        at = datetime.combine(day, time(7, 0), tzinfo=zone)
    elif timing == "intraday":
        at = datetime.combine(day, time(12, 0), tzinfo=zone)
    else:
        at = market.close_at(day) + timedelta(minutes=5)
    return pd.Timestamp(at).tz_convert("UTC")


def close_times(sessions: pd.DatetimeIndex, market: Market) -> np.ndarray:
    """Each session's close as UTC nanoseconds, for searchsorted."""
    return np.array([pd.Timestamp(market.close_at(d.date())).tz_convert("UTC").value for d in sessions], dtype="int64")


class Series:
    """One company's daily excess moves (percent beyond its own market's
    index) on its own sessions, with each session's close instant."""

    def __init__(self, excess: pd.Series, market: Market):
        self.excess = excess.dropna()
        self.market = market
        self.closes = close_times(self.excess.index, market)
        self.cum = np.concatenate([[0.0], np.cumsum(self.excess.to_numpy())])

    def first_after(self, instant: pd.Timestamp, max_days: int = 5) -> int | None:
        """Position of the first session closing after ``instant``."""
        at = int(np.searchsorted(self.closes, instant.value, side="right"))
        if at >= len(self.closes) or at == 0:
            return None
        if (self.closes[at] - instant.value) / 86_400e9 > max_days:
            return None
        return at

    def move(self, at: int) -> float:
        return float(self.excess.iloc[at])

    def between(self, after: int, through: int) -> float | None:
        """Summed excess over sessions after ``after`` through ``through``."""
        if through <= after:
            return None
        return float(self.cum[through + 1] - self.cum[after + 1])

    def day(self, at: int) -> str:
        return self.excess.index[at].strftime("%Y-%m-%d")


def daily_excess(close: pd.Series, index: pd.Series) -> pd.Series:
    """Session return less the index's over the same sessions, in percent.
    A session the index lacks, or after a gap in the stock's own prices,
    is left out."""
    c = close.dropna()
    i = index.dropna().reindex(c.index)
    out = (c.pct_change(fill_method=None) - i.pct_change(fill_method=None)) * 100
    gaps = pd.Series(c.index, index=c.index).diff().dt.days > 6
    return out[~gaps].dropna()


@dataclass
class Report:
    info: pd.Timestamp
    surprise: float | None
    own_at: int | None          # position of its own reaction session
    own_move: float | None
    source: str


def reports_for(rows: list[dict], series: Series | None, releases: Market) -> list[Report]:
    """``releases``: the market whose hours an untimed report is read in."""
    out = []
    for r in rows:
        info = info_time(r, releases)
        at = series.first_after(info) if series is not None else None
        out.append(Report(info, r.get("surprise_pct"), at, series.move(at) if at is not None else None, r.get("source", "")))
    out.sort(key=lambda r: r.info)
    return out


def _clip(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return max(-SURPRISE_CLIP, min(SURPRISE_CLIP, x))


def pair_records(lead_key: str, lead: list[Report], follow_key: str, follow: Series, follow_reports: list[Report]) -> list[dict]:
    """One row per lead report the follower traded: its move that session,
    and -- when the follower reported within FOLLOW_DAYS -- the drift until
    then, its own surprise and its own reaction."""
    rows = []
    for rep in lead:
        if rep.own_move is None:
            continue
        at = follow.first_after(rep.info)
        if at is None:
            continue
        row = {"lead": lead_key, "follow": follow_key, "lead_info": rep.info, "lead_day": rep.info.date().isoformat(),
               "lead_move": rep.own_move, "lead_surprise": _clip(rep.surprise), "follow_day": follow.day(at),
               "follow_move": follow.move(at), "follow_at": at}
        # The follower's next report after the session it traded the lead's.
        session_close = pd.Timestamp(follow.closes[at], tz="UTC")
        nxt = next((f for f in follow_reports if f.info >= session_close), None)
        if nxt is not None and nxt.own_at is not None and (nxt.info - rep.info).days <= FOLLOW_DAYS:
            row["drift"] = follow.between(at, nxt.own_at - 1)
            row["follow_surprise"] = _clip(nxt.surprise)
            row["follow_reaction"] = nxt.own_move
            row["follow_report_info"] = nxt.info
        rows.append(row)
    return rows


# --- Aggregation ------------------------------------------------------------------------

def _t(values: list[float]) -> float | None:
    v = [x for x in values if x is not None and math.isfinite(x)]
    if len(v) < 3:
        return None
    sd = float(np.std(v, ddof=1))
    return None if sd == 0 else round(float(np.mean(v)) / (sd / math.sqrt(len(v))), 2)


def _spearman(a: list[float], b: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 12:
        return None
    x, y = zip(*pairs)
    sx, sy = pd.Series(x), pd.Series(y)
    if sx.nunique() < 2 or sy.nunique() < 2:
        return None
    return round(float(sx.rank().corr(sy.rank())), 2)


def _clustered(rows: list[dict], value) -> dict:
    """Mean of ``value(row)``, its t across lead reports (each report's
    followers averaged first), and the counts behind both."""
    by_lead: dict[tuple, list[float]] = {}
    for r in rows:
        v = value(r)
        if v is None or not math.isfinite(v):
            continue
        by_lead.setdefault((r["lead"], r["lead_day"]), []).append(v)
    means = [float(np.mean(v)) for v in by_lead.values()]
    flat = [x for v in by_lead.values() for x in v]
    return {"mean": round(float(np.mean(flat)), 2) if flat else None, "t": _t(means),
            "pairs": len(flat), "reports": len(means)}


def _sign(x: float | None) -> float | None:
    if x is None or x == 0:
        return None
    return 1.0 if x > 0 else -1.0


def summarise(rows: list[dict]) -> dict:
    """The four questions over one set of pair rows (one category of link)."""
    immediate = _clustered(rows, lambda r: r["follow_move"] * s if (s := _sign(r["lead_move"])) else None)
    same = [r for r in rows if _sign(r["lead_move"]) and _sign(r["follow_move"])]
    immediate["same_way_pct"] = round(100 * sum(_sign(r["lead_move"]) == _sign(r["follow_move"]) for r in same) / len(same)) if same else None
    immediate["rank_corr"] = _spearman([r["lead_move"] for r in rows], [r["follow_move"] for r in rows])

    with_both = [r for r in rows if r.get("lead_surprise") is not None and r.get("follow_surprise") is not None]
    lead_beat = [r for r in with_both if r["lead_surprise"] > 0]
    lead_miss = [r for r in with_both if r["lead_surprise"] < 0]
    beat_rate = lambda part: round(100 * sum(r["follow_surprise"] > 0 for r in part) / len(part)) if part else None  # noqa: E731
    fundamental = {"pairs": len(with_both), "rank_corr": _spearman([r["lead_surprise"] for r in with_both],
                                                                    [r["follow_surprise"] for r in with_both]),
                   "follow_beat_after_beat_pct": beat_rate(lead_beat), "after_beat": len(lead_beat),
                   "follow_beat_after_miss_pct": beat_rate(lead_miss), "after_miss": len(lead_miss),
                   "follow_beat_pct": beat_rate(with_both)}

    drifted = [r for r in rows if r.get("drift") is not None]
    drift = _clustered(drifted, lambda r: r["drift"] * s if (s := _sign(r["lead_move"])) else None)
    up = [r["drift"] for r in drifted if (r["lead_move"] or 0) > 0]
    down = [r["drift"] for r in drifted if (r["lead_move"] or 0) < 0]
    drift["after_up"] = round(float(np.mean(up)), 2) if up else None
    drift["after_down"] = round(float(np.mean(down)), 2) if down else None
    drift["n_up"], drift["n_down"] = len(up), len(down)
    drift["same_day_vs_drift_corr"] = _spearman([r["follow_move"] for r in drifted], [r["drift"] for r in drifted])
    return {"immediate": immediate, "fundamental": fundamental, "drift": drift}


def priced_in(rows: list[dict], *, window_days: int = 90) -> dict:
    """Question 4, per follower report: the follower's summed moves on its
    linked companies' report sessions in the ``window_days`` before its own
    report (the read-in), against its own reaction to that report."""
    by_report: dict[tuple, dict] = {}
    for r in rows:
        info = r.get("follow_report_info")
        if info is None or r.get("follow_reaction") is None:
            continue
        if (info - r["lead_info"]).days > window_days:
            continue
        key = (r["follow"], info)
        entry = by_report.setdefault(key, {"read_in": 0.0, "sessions": set(), "reaction": r["follow_reaction"],
                                           "surprise": r.get("follow_surprise")})
        # Two leads traded on one session count that session once.
        if r["follow_day"] not in entry["sessions"]:
            entry["sessions"].add(r["follow_day"])
            entry["read_in"] += r["follow_move"]
    reports = list(by_report.values())
    if not reports:
        return {"reports": 0}
    read_in = [e["read_in"] for e in reports]
    reaction = [e["reaction"] for e in reports]
    out = {"reports": len(reports), "rank_corr": _spearman(read_in, reaction)}
    beats = [e for e in reports if (e["surprise"] or 0) > 0]
    if len(beats) >= 12:
        cut_lo, cut_hi = np.percentile([e["read_in"] for e in beats], [33.3, 66.7])
        high = [e["reaction"] for e in beats if e["read_in"] >= cut_hi]
        low = [e["reaction"] for e in beats if e["read_in"] <= cut_lo]
        out.update({"beats": len(beats), "beat_reaction_high_read_in": round(float(np.mean(high)), 2) if high else None,
                    "beat_reaction_low_read_in": round(float(np.mean(low)), 2) if low else None,
                    "high_read_in_floor": round(float(cut_hi), 2), "low_read_in_ceiling": round(float(cut_lo), 2),
                    "beat_rank_corr": _spearman([e["read_in"] for e in beats], [e["reaction"] for e in beats])})
    return out


def season_window(as_of: date) -> tuple[date, date, str]:
    """The reporting season ``as_of`` falls in: from a week after a calendar
    quarter's end, for three months; and its label (the quarter reported)."""
    for back in range(0, 5):
        month = ((as_of.month - 1) // 3) * 3 + 1 - 3 * back
        year = as_of.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        quarter_end = date(year, month, 1) - timedelta(days=1)
        start = quarter_end + timedelta(days=SEASON_START_DAYS)
        if start <= as_of:
            end_month = month + 3
            end = date(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1) - timedelta(days=1) + timedelta(days=SEASON_START_DAYS)
            label = f"CQ{(quarter_end.month - 1) // 3 + 1} {quarter_end.year}"
            return start, end, label
    raise ValueError(as_of)
