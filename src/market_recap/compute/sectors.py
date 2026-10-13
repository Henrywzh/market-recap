"""Pure helpers for the SECTORS hub: keys, cap-weighted returns, extremes and the page series.

A sub-industry's key is its sector's fund, a dash and the initials of its words,
so a key can be read off its label and needs no lookup table. The keys are
deterministic: the caller assigns them in label order, so a weight change never
renames a sub-industry.

The page series (``relative_payload``, ``valuation_band``) are read by each
page's charts. A page's relative line is its cap-weighted basket over the whole
S&P 500 built the way ROTATION builds its benchmark, so it is a true relative
price line, not a return. The P/E figures on the hub are aggregates -- total
market cap over total earnings, as an index's P/E is -- and the medians that
INDUSTRIES keeps are carried beside them, not replaced.
"""

from __future__ import annotations

import re

import pandas as pd

from ..util import clean_float
from . import baskets as B
from . import rotation as R
from . import series as SR
from . import valuation as V

# Words that do not start a key's initials ("Soft Drinks & Non-alcoholic Beverages").
SKIPPED_WORDS = frozenset({"&", "and", "of"})
# Years of history each page's relative line and P/E band cover.
PAGE_YEARS = 10


def initials(label: str) -> str:
    """Uppercase initials of a label's words, skipping "&", "and" and "of".

    A hyphenated word counts once ("Non-alcoholic" is N), and a token with no
    letter or digit ("-") counts for nothing.
    """
    letters = []
    for word in re.split(r"[\s,]+", label or ""):
        if not word or word.lower() in SKIPPED_WORDS:
            continue
        head = next((ch for ch in word if ch.isalnum()), None)
        if head is not None:
            letters.append(head.upper())
    return "".join(letters) or "SUB"


def sub_key(sector_key: str, label: str, taken) -> str:
    """The key for a sub-industry: sector key, dash, initials; a digit on collision.

    ``taken`` holds the keys already given within the sector. The caller adds the
    returned key to it. The first of two colliding labels keeps the bare key and
    the next gets "2", so the order of assignment (label order) decides.
    """
    base = f"{sector_key}-{initials(label)}"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}{n}"
    return key


def weighted_returns(members: list[dict], periods) -> dict[str, float | None]:
    """Cap-weighted return per period from members with ``weight`` and ``returns``.

    A member with no return for a period is left out of that period and the
    weights that remain are renormalised. None where no member has a return.
    """
    out: dict[str, float | None] = {}
    for period in periods:
        pairs = []
        for member in members:
            weight = clean_float(member.get("weight"))
            value = clean_float((member.get("returns") or {}).get(period))
            if weight is not None and value is not None:
                pairs.append((weight, value))
        total = sum(weight for weight, _ in pairs)
        out[period] = sum(weight * value for weight, value in pairs) / total if total else None
    return out


def excess(value: float | None, base: float | None) -> float | None:
    """``value`` less ``base`` in percentage points, or None if either is missing."""
    if value is None or base is None:
        return None
    return value - base


def best_and_worst(members: list[dict], period: str) -> tuple[dict | None, dict | None]:
    """(best, worst) as ``{"ticker", "return"}`` over the members with a return.

    Ties break on ticker, so the same data always names the same name.
    """
    ranked = []
    for member in members:
        value = clean_float((member.get("returns") or {}).get(period))
        if value is not None:
            ranked.append((value, member["ticker"]))
    if not ranked:
        return None, None
    ranked.sort()
    worst, best = ranked[0], ranked[-1]
    return ({"ticker": best[1], "return": best[0]}, {"ticker": worst[1], "return": worst[0]})


def index_basket(closes: pd.DataFrame, weights: dict[str, float]) -> dict | None:
    """The whole index, built the way ROTATION builds its benchmark.

    Every name with a weight and a price is held at today's weight as units, over
    the sessions they were all priced on. Returns the sessions, the units and the
    index level (starting at 1), or None when no weighted name has a price.
    """
    names = [t for t in closes.columns if (weights.get(t) or 0) > 0]
    if not names:
        return None
    sessions = R.sessions(closes[names])
    if sessions.empty:
        return None
    held = R.units(sessions, pd.Series({t: float(weights[t]) for t in names}, dtype=float))
    return {"sessions": sessions, "held": held, "level": R.basket(sessions, held)}


def page_ratio(index: dict, members: list[str]) -> pd.Series | None:
    """The members' cap-weighted basket over the whole index, on the index's sessions.

    A member with no price (or no unit held) is left out; None when none is left.
    Not yet rebased: ``relative_payload`` sets the start to 100.
    """
    sessions, held = index["sessions"], index["held"]
    cols = [t for t in members if t in sessions.columns and pd.notna(held.get(t))]
    if not cols:
        return None
    level = R.basket(sessions[cols], held.reindex(cols))
    return level / index["level"]


def fund_ratio(etf_closes: pd.DataFrame, fund: str | None, benchmark: str) -> pd.Series | None:
    """A sector fund's adjusted close over the benchmark's; None when either has no closes."""
    if not fund or fund not in etf_closes.columns or benchmark not in etf_closes.columns:
        return None
    return etf_closes[fund] / etf_closes[benchmark]


def _rebased(series: pd.Series) -> pd.Series:
    """The series x100 at its first real value, so a line that starts later still starts at 100."""
    valid = series.dropna()
    if valid.empty:
        return series
    return 100 * series / valid.iloc[0]


def relative_payload(frame: pd.DataFrame) -> dict:
    """The page's dated relative lines: the last PAGE_YEARS, each column x100 at its first value.

    Columns are whatever the caller built (``basket``, and ``fund`` for a sector).
    Thinned the way every long series on the page is, so the page stays small.
    """
    last = frame.index[-1]
    recent = frame[frame.index > last - pd.DateOffset(years=PAGE_YEARS)]
    return SR.payload(recent.apply(_rebased), PAGE_YEARS)


def valuation_band(histories: dict[str, dict | None], weights: dict[str, float], *,
                   min_names: int) -> tuple[dict | None, int]:
    """The page's P/E band from its names' weekly VALUATION histories, and how many names it could use.

    The band is baskets.basket over the names with a history and a weight, cut to
    PAGE_YEARS. The band is None when fewer than ``min_names`` names are usable, or
    when no week ever has a P/E with enough cover and a positive total.
    """
    closes, yields = B.frames(histories)
    usable = [t for t in closes.columns if (weights.get(t) or 0) > 0]
    if len(usable) < min_names:
        return None, len(usable)
    frame = B.basket(closes, yields, {t: float(weights[t]) for t in usable})
    return B.payload(frame, years=PAGE_YEARS), len(usable)


def forward_pe(members: list[dict], *, min_names: int) -> float | None:
    """Aggregate next-twelve-months P/E of the members, as panels/valuation's groups compute it.

    Total market cap over total NTM earnings (per-share NTM EPS times the cap over
    the price) for the members with an estimate. None when fewer than ``min_names``
    members carry a market cap, when the names with an estimate hold less than
    AGGREGATE_MIN_COVERAGE of the cap, or when their total earnings are not positive.
    """
    caps = {r["ticker"]: r["market_cap"] for r in members if r.get("market_cap")}
    if len(caps) < min_names:
        return None
    earnings = {r["ticker"]: r["eps_ntm"] * r["market_cap"] / r["price"]
                for r in members
                if r.get("market_cap") and r.get("eps_ntm") is not None and r.get("price")}
    found = V.aggregate_forward(caps, earnings)
    if found is None or found["coverage"] < V.AGGREGATE_MIN_COVERAGE:
        return None
    return clean_float(found["pe"], 1)
