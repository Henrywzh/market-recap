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
import re

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


def candidates(corr: pd.DataFrame, symbol: str, *, count: int, same_issuer: set[str],
               linked: dict[str, str] | None = None, strong_corr: float = 0.45) -> list[tuple[str, float, str]]:
    """Up to ``count`` peers, most correlated first, each with why it is one.

    A peer needs a reason beyond the correlation itself: the same industry or
    a shared theme (``linked``: symbol -> reason), or a correlation of at least
    ``strong_corr``. Ranking the whole index by correlation alone handed Apple
    GoDaddy and Hershey at 0.28 -- the best of a crowd of chance matches. Another
    share class of the same issuer is left out (GOOG moves with GOOGL by
    construction)."""
    if symbol not in corr.columns:
        return []
    linked = linked or {}
    row = corr[symbol].drop(labels=[symbol, *same_issuer], errors="ignore").dropna()
    out = []
    for peer, value in row[row > 0].sort_values(ascending=False).items():
        reason = linked.get(str(peer)) or (f"trades with it (corr {value:.2f})" if value >= strong_corr else None)
        if reason:
            out.append((str(peer), float(value), reason))
        if len(out) >= count:
            break
    return out


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
    beta = sum(a * b for a, b in pairs) / denominator
    # The beta's t-statistic (a regression through the origin): how far it
    # stands above what eight noisy sessions give by chance.
    residual = sum((b - beta * a) ** 2 for a, b in pairs) / max(len(pairs) - 1, 1)
    t = beta / math.sqrt(residual / denominator) if residual > 0 else None
    return {
        "n": len(pairs),
        "beta": round(beta, 2),
        "t": None if t is None else round(t, 2),
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


# --- Large moves and what explains them ---------------------------------------
# A move is large against the name's own recent volatility, not a fixed size:
# 4% is noise for a memory maker and an event for a utility.
MOVE_Z = 2.5
MOVE_MIN_PCT = 2.0
MOVE_VOL_SESSIONS = 60


def big_moves(excess: pd.Series, *, since: str, skip: set[str], z: float = MOVE_Z, min_pct: float = MOVE_MIN_PCT,
              vol_sessions: int = MOVE_VOL_SESSIONS) -> list[dict]:
    """Sessions since ``since`` whose move beyond the S&P 500 was at least ``z``
    times the standard deviation of the ``vol_sessions`` before it, and at
    least ``min_pct``; ``skip`` (report sessions) left out. Oldest first."""
    series = excess.dropna()
    if len(series) <= vol_sessions:
        return []
    vol = series.rolling(vol_sessions, min_periods=int(vol_sessions * 0.8)).std().shift(1)
    out = []
    for day, value in series.loc[since:].items():
        sd = vol.get(day)
        key = day.strftime("%Y-%m-%d")
        if key in skip or sd is None or pd.isna(sd) or sd == 0:
            continue
        score = value / sd
        if abs(score) >= z and abs(value) >= min_pct:
            out.append({"date": key, "excess_pct": round(float(value), 2), "z": round(float(score), 1)})
    return out


_ROUNDUP = re.compile(r"stocks? making|market today|stock market|movers|biggest|top \d+|\d+ stocks|these stocks|week ahead|"
                      r"this week|wrap|midday|premarket|pre-market|after-hours|morning brief|futures|dow |s&p 500|nasdaq composite", re.I)
_EXPLAINS = re.compile(r"^why |shares? (?:jump|soar|surge|rise|rall|climb|gain|fall|drop|sink|slide|tumble|plunge|slump)|"
                       r"stock (?:jump|soar|surge|rise|rall|climb|gain|fall|drop|sink|slide|tumble|plunge|slump)|"
                       r"upgrade|downgrade|guidance|outlook|acqui|merger|deal|lawsuit|probe|investigat|recall|ceo|"
                       r"contract|order|approval|fda|tariff|ban|export", re.I)
_TRUSTED = {"reuters", "bloomberg", "cnbc", "wsj", "dow jones", "barrons", "barron's", "marketwatch", "financial times",
            "ft", "the information", "associated press", "yahoo"}


def short_name(name: str | None, symbol: str) -> str:
    """'Micron Technology Inc' -> 'Micron': the word a headline uses."""
    words = re.sub(r"[^A-Za-z0-9&.\- ]", " ", name or "").split()
    return words[0] if words and len(words[0]) > 2 else symbol


def rank_headlines(rows: list[dict], symbol: str, name: str | None, start_ts: float, end_ts: float,
                   keep: int = 3) -> list[dict]:
    """The headlines most likely to explain one session's move: published
    after the previous close and before this close, naming the company, saying
    why it moved, and not a market roundup."""
    word = short_name(name, symbol).lower()
    ticker = re.compile(rf"\b{re.escape(symbol.replace('-', '.'))}\b")
    scored = []
    seen = set()
    for r in rows:
        when, headline = r.get("datetime") or 0, (r.get("headline") or "").strip()
        if not headline or not start_ts <= when <= end_ts or headline.lower() in seen:
            continue
        seen.add(headline.lower())
        text = headline.lower()
        # A bank or a broker is named as often as the commentator as the subject:
        # "AVGO jumps -- JPMorgan says buy" is Broadcom's story, not JPMorgan's.
        # Only analyst phrasing: "raises", "sees" or "warns" is as often the
        # company's own news ("Micron raises outlook").
        voice = re.search(rf"\b{re.escape(word)}(?:'s)?\s+(?:analysts?|strategists?|economists?|upgrades?|downgrades?|initiates|"
                          r"reiterates|says investors|price target)\b", text)
        other = re.match(r"^([A-Z]{1,5})\b(?i: stock| shares)", headline)
        if voice or (other and other.group(1) != symbol.split("-")[0]):
            continue
        score = (3 if word in text or ticker.search(headline) else 0) + (2 if _EXPLAINS.search(headline) else 0) \
            + (1 if (r.get("source") or "").lower() in _TRUSTED else 0) - (3 if _ROUNDUP.search(headline) else 0)
        if score >= 3:
            scored.append((score, when, {"headline": headline, "source": r.get("source"), "url": r.get("url"),
                                         "time": pd.Timestamp(when, unit="s", tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [x[2] for x in scored[:keep]]


def move_reasons(day: str, timeline: list[dict], peer_reports: dict[str, list[str]], releases: dict[str, list[str]]) -> list[dict]:
    """What else happened on ``day``: the name's own dated events (that day or
    an after-close filing the evening before), linked peers' report sessions,
    and its themes' data released that day."""
    before = (pd.Timestamp(day) - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d")
    out = []
    for i in timeline:
        if i["kind"] == "earnings":
            continue
        if i["date"] == day or (i["kind"] == "filing" and i["date"] == before):
            if i["kind"] == "rating":
                what = {"up": "upgrade", "down": "downgrade", "init": "initiation"}.get(i.get("action"), "target change")
                out.append({"kind": "rating", "text": f"{i.get('firm')}: {what}" + (f" to {i['to']}" if i.get("to") else "")
                            + (f", target {i['prior_target']:.0f} → {i['target']:.0f}" if i.get("target") and i.get("prior_target") else "")})
            elif i["kind"] == "filing":
                out.append({"kind": "filing", "text": "8-K: " + ", ".join(i["labels"]), "url": i.get("url")})
            elif i["kind"] == "insider_buy":
                out.append({"kind": "insider", "text": f"insider buy: {i.get('owner')}"})
    for peer, sessions in peer_reports.items():
        if day in sessions:
            out.append({"kind": "peer", "text": f"{peer} reported", "symbol": peer})
    for label in releases.get(day, []):
        out.append({"kind": "data", "text": f"{label} released"})
    return out


# --- Company events announced ahead -------------------------------------------
# No free feed lists investor days, product events or FDA dates, but companies
# announce them, and the announcement names the date. A sentence counts only
# when it has both an event phrase and a date still ahead; the source line is
# kept so every event can be checked.
EVENT_KINDS = (
    ("investor day", re.compile(r"\b(?:investor|analyst|capital markets?|strategy) (?:day|update|meeting|event)\b", re.I)),
    ("FDA decision", re.compile(r"\bPDUFA\b|\btarget action date\b|\badvisory committee\b", re.I)),
    ("product event", re.compile(r"\b(?:keynote|launch event|product event|unveil\w*|developer conference|GTC|WWDC|re:Invent|"
                                 r"Google I/O|Build conference|Dreamforce|Ignite|Tesla AI Day|Capital Markets Day)\b", re.I)),
    ("shareholder meeting", re.compile(r"\b(?:annual (?:general |share(?:holder|owner)s?'? |stockholders?'? )?meeting|special meeting)\b", re.I)),
    ("trial or ruling", re.compile(r"\b(?:trial (?:begins|starts|set)|verdict|ruling (?:is )?(?:expected|due)|remedies (?:ruling|decision)|"
                                   r"hearing (?:is )?(?:set|scheduled))\b", re.I)),
)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_DATE = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|"
                   r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (20\d\d))?\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _dates_in(text: str, published: date, horizon_end: date) -> list[date]:
    out = []
    for m in _DATE.finditer(text):
        month, day = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        year = int(m.group(3)) if m.group(3) else published.year
        try:
            when = date(year, month, day)
        except ValueError:
            continue
        if not m.group(3) and when < published:
            when = date(year + 1, month, day) if month < published.month else when
        if published < when <= horizon_end:
            out.append(when)
    return out


def announced_events(rows: list[dict], symbol: str, name: str | None, today: date, horizon_days: int = 180) -> list[dict]:
    """Dated company events still ahead, from headlines and summaries that
    name the company: {date, kind, text, source, url, published}, soonest
    first, one per (date, kind)."""
    word = short_name(name, symbol).lower()
    ticker = re.compile(rf"\b{re.escape(symbol.replace('-', '.'))}\b")
    end = today + timedelta(days=horizon_days)
    found: dict[tuple[str, str], dict] = {}
    for r in rows:
        headline, summary = (r.get("headline") or "").strip(), (r.get("summary") or "").strip()
        if not (word in headline.lower() or ticker.search(headline) or word in summary.lower()[:300]):
            continue
        published = pd.Timestamp(r.get("datetime") or 0, unit="s", tz="UTC").tz_convert("America/New_York").date()
        for sentence in [headline, *_SENTENCE.split(summary)][:6]:
            for kind, pattern in EVENT_KINDS:
                if not pattern.search(sentence):
                    continue
                for when in _dates_in(sentence, published, end):
                    if when <= today:
                        continue
                    key = (when.isoformat(), kind)
                    if key not in found or published.isoformat() > found[key]["published"]:
                        found[key] = {"date": when.isoformat(), "kind": kind, "text": sentence[:240], "source": r.get("source"),
                                      "url": r.get("url"), "published": published.isoformat()}
    return sorted(found.values(), key=lambda e: e["date"])
