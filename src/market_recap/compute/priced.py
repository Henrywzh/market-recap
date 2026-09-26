"""What the rates market prices for each FOMC meeting, from fed funds futures.

The meeting-month method (the arithmetic behind CME's FedWatch):

    A fed funds future settles on the month's average effective rate, so its
    implied rate is R = 100 - price. In a month with a meeting on day d of N,
    the rate holds for d days and the new one for the other N - d:

        R_month = (d * pre + (N - d) * post) / N

    The pre-meeting rate is today's effective rate, then each meeting's
    post-meeting rate in turn. When the following month has no meeting, its
    contract is the post-meeting rate directly, which avoids dividing by a
    small N - d when the meeting falls late in the month.

A meeting's expected change is post - pre. Its probability of a 25 bp move is
that change over 25 bp (a move of one step either way, the usual reading);
beyond one step it is a certain step plus a probability of the next. The
distribution over target ranges is shown as the two nearest outcomes to the
cumulative change, not CME's full tree: which pair of ranges the market sits
between, and how far toward each.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
import math

import pandas as pd

STEP_BP = 25.0


def month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def next_month(key: str) -> str:
    year, month = map(int, key.split("-"))
    return f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"


def policy_path(prices: dict[str, float], meetings: list[date], start_rate: float) -> list[dict]:
    """Expected rate after each meeting, in percent, from month -> futures price.

    Stops at the first meeting whose month has no price.
    """
    by_month = {month_key(m) for m in meetings}
    rate = start_rate
    out = []
    for meeting in sorted(meetings):
        key = month_key(meeting)
        if key not in prices:
            break
        implied = 100.0 - prices[key]
        following = next_month(key)
        days = calendar.monthrange(meeting.year, meeting.month)[1]
        before = meeting.day
        if following not in by_month and following in prices:
            post = 100.0 - prices[following]
            method = "next month's contract"
        elif days - before > 0:
            post = (days * implied - before * rate) / (days - before)
            method = "this month's contract"
        else:
            break
        change_bp = (post - rate) * 100
        out.append({
            "date": meeting.isoformat(),
            "pre": round(rate, 4),
            "post": round(post, 4),
            "change_bp": round(change_bp, 1),
            "cumulative_bp": round((post - start_rate) * 100, 1),
            "method": method,
        })
        rate = post
    return out


def step_probabilities(change_bp: float) -> dict:
    """A change read as steps of 25 bp: the whole steps and the chance of one more."""
    steps = change_bp / STEP_BP
    whole = math.floor(steps) if steps >= 0 else math.ceil(steps)
    fraction = abs(steps - whole)
    direction = "hike" if steps > 0 else "cut" if steps < 0 else "hold"
    return {"steps": round(steps, 3), "whole_steps": int(whole), "p_next_step": round(fraction, 3), "direction": direction}


def two_nearest(cumulative_bp: float, lower: float, upper: float) -> list[dict]:
    """The two target ranges either side of the cumulative change, with weights."""
    steps = cumulative_bp / STEP_BP
    low = math.floor(steps)
    weight_high = steps - low
    ranges = []
    for count, weight in ((low, 1 - weight_high), (low + 1, weight_high)):
        shift = count * STEP_BP / 100
        ranges.append({
            "range": f"{lower + shift:.2f}–{upper + shift:.2f}",
            "change_bp": int(count * STEP_BP),
            "probability": round(weight, 3),
        })
    return [r for r in ranges if r["probability"] > 0.0005] or ranges[:1]


def prices_on(history: pd.DataFrame, day: pd.Timestamp) -> dict[str, float]:
    """Each contract's last close on or before ``day`` (columns are month keys)."""
    before = history[history.index <= day]
    if before.empty:
        return {}
    last = before.ffill().iloc[-1]
    return {key: float(value) for key, value in last.items() if pd.notna(value)}


def rate_on(series: pd.Series, day: pd.Timestamp) -> float | None:
    before = series[series.index <= day].dropna()
    return float(before.iloc[-1]) if not before.empty else None


def next_meeting_history(history: pd.DataFrame, effr: pd.Series, meetings: list[date],
                         days: int = 120) -> pd.DataFrame:
    """For each session in the last ``days``, the change priced at the meeting
    that was next on that day -- the series BRIEF reads its 1D / 1W change from."""
    if history.empty:
        return pd.DataFrame(columns=["date", "meeting", "change_bp"])
    end = history.index[-1]
    rows = []
    for day in history.index[history.index >= end - timedelta(days=days)]:
        upcoming = [m for m in meetings if pd.Timestamp(m) > day]
        start = rate_on(effr, day)
        if not upcoming or start is None:
            continue
        path = policy_path(prices_on(history, day), upcoming[:1], start)
        if path:
            rows.append({"date": day, "meeting": path[0]["date"], "change_bp": path[0]["change_bp"]})
    return pd.DataFrame(rows)


KALSHI_OUTCOMES = (
    (r"cut\s*>\s*25", -50.0), (r"cut\s*25", -25.0), (r"maintain|hold|unchanged", 0.0),
    (r"hike\s*25", 25.0), (r"hike\s*>\s*25", 50.0),
)


def kalshi_meeting(event: dict) -> dict | None:
    """Kalshi's outcome probabilities for one meeting and their expected change.

    ">25 bp" outcomes are counted as 50 bp in the expectation, which is the
    smallest move they can be; the page says so.
    """
    import re

    outcomes = []
    for market in event.get("markets") or []:
        label = str(market.get("yes_sub_title") or market.get("subtitle") or "")
        bp = next((value for pattern, value in KALSHI_OUTCOMES if re.search(pattern, label, re.I)), None)
        if bp is None:
            continue
        try:
            bid, ask = float(market.get("yes_bid_dollars")), float(market.get("yes_ask_dollars"))
        except (TypeError, ValueError):
            bid = ask = None
        try:
            last = float(market.get("last_price_dollars"))
        except (TypeError, ValueError):
            last = None
        probability = (bid + ask) / 2 if bid is not None and ask is not None and 0 <= ask - bid <= 0.10 and ask > 0 else last
        if probability is None:
            continue
        outcomes.append({"label": label, "change_bp": bp, "probability": round(probability, 3)})
    total = sum(o["probability"] for o in outcomes)
    if not outcomes or total <= 0:
        return None
    closes = sorted(str(m.get("close_time"))[:10] for m in event.get("markets") or [] if m.get("close_time"))
    expected = sum(o["change_bp"] * o["probability"] for o in outcomes) / total
    return {
        "event": event.get("event_ticker"),
        "title": event.get("title"),
        "date": closes[0] if closes else None,
        "outcomes": outcomes,
        "expected_bp": round(expected, 1),
        "p_hike": round(sum(o["probability"] for o in outcomes if o["change_bp"] > 0) / total, 3),
        "p_cut": round(sum(o["probability"] for o in outcomes if o["change_bp"] < 0) / total, 3),
        "sum_of_prices": round(total, 3),
    }
