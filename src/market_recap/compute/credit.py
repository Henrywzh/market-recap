"""Equity-implied default risk: the distance to default from filed debt and the close.

A description of credit stress for names whose CDS and bond prices the site
cannot buy or republish (quantamental-lab docs/credit_proxy_v1.md). Monthly
changes in the median of it track Moody's BAA - 10Y spread (correlation about
-0.7 over 2017-2026) but do not lead it, and a debt plan the market prices is
seen only once a 10-Q files it. So it is shown as a level against the name's
own history, never as a warning.

Bharath and Shumway's (2008) naive distance to default:
  E  = the close x shares outstanding as filed by that day (split-adjusted)
  F  = debt due within a year + half the long-term debt (the KMV default point),
       each value counting from its filing date
  sE = annualised volatility of daily log returns over the last year
  sD = 0.05 + 0.25 sE; V = E + F; sV = E/V sE + F/V sD
  DD = (ln(V/F) + (r - sV^2/2) T) / (sV sqrt T), T = 1 year
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# What a filer's company facts are read for: kept on the parsed filer (sources.sec).
# Filers report the same debt several ways (with or without leases, as one total or as
# parts); each side takes the largest of the ways a filer used, so none is undercounted.
SHORT_TOTAL = "DebtCurrent"
SHORT_WITH_LEASES = "LongTermDebtAndCapitalLeaseObligationsCurrent"
SHORT_PARTS = ("LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper", "ConvertibleDebtCurrent",
               "NotesPayableCurrent", "OtherLongTermDebtCurrent")
LEASE_CURRENT = "FinanceLeaseLiabilityCurrent"
LONG_WITH_LEASES = "LongTermDebtAndCapitalLeaseObligations"
LONG_PARTS = ("LongTermDebtNoncurrent", "ConvertibleDebtNoncurrent", "LongTermNotesPayable",
              "OtherLongTermDebtNoncurrent", "FinanceLeaseLiabilityNoncurrent")
# Includes the current portion when a filer tags only the total.
LONG_TOTAL = "LongTermDebt"
# Debt by kind of instrument (REITs file it this way): their sum is one more reading of
# the long side.
BY_INSTRUMENT = ("SeniorNotes", "SecuredDebt", "UnsecuredDebt", "ConvertibleDebt", "OtherNotesPayable", "NotesPayable")
# The debt note's total: counts the debt a balance sheet files under the filer's own
# tags (CoreWeave's 2026 Q2), which company facts leave out.
CARRYING = "DebtInstrumentCarryingAmount"
# One figure for all debt, used only when a filer gives neither side.
ALL_DEBT = ("DebtAndCapitalLeaseObligations", "DebtLongtermAndShorttermCombinedAmount")
SHARE_TAGS = (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding"))
DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"
DEBT_TAGS = (SHORT_TOTAL, SHORT_WITH_LEASES, *SHORT_PARTS, LEASE_CURRENT, LONG_WITH_LEASES, *LONG_PARTS,
             LONG_TOTAL, *BY_INSTRUMENT, *ALL_DEBT, CARRYING)
TRADING_DAYS = 252
DEBT_JUMP = 10.0


def filed_facts(facts: dict) -> dict:
    """The few series the measure reads, as (end, filed, value) rows per tag: small
    enough to keep on the parsed filer between builds."""
    out: dict[str, tuple] = {}
    groups = facts.get("facts") or {}

    def rows(taxonomy: str, tag: str, durations: bool = False) -> tuple:
        units = (groups.get(taxonomy) or {}).get(tag, {}).get("units", {})
        found: dict[tuple, float] = {}
        seen: set[tuple] = set()
        for unit in ("USD", "shares"):
            for v in units.get(unit, []):
                if v.get("val") is None or "end" not in v or "filed" not in v:
                    continue
                if ("start" in v) != durations:
                    continue
                if durations and v.get("fp") not in ("FY", "Q1", "Q2", "Q3", "Q4"):
                    continue
                key = (v["end"], v["filed"], v.get("accn"))
                if (*key, v.get("frame"), v["val"]) in seen:
                    continue  # the same fact listed twice
                seen.add((*key, v.get("frame"), v["val"]))
                # A cover page lists each share class once: the company's count is their sum.
                found[key] = found.get(key, 0.0) + float(v["val"]) if taxonomy == "dei" else float(v["val"])
        return tuple(sorted((end, filed, val) for (end, filed, _), val in found.items()))

    for tag in DEBT_TAGS:
        if found := rows("us-gaap", tag):
            out[tag] = found
    for taxonomy, tag in SHARE_TAGS:
        if found := rows(taxonomy, tag):
            out[tag] = found
    if found := rows("us-gaap", DILUTED, durations=True):
        out[DILUTED] = found
    return out


def as_of(rows, index: pd.DatetimeIndex, stale_days: int) -> pd.Series:
    """Each day's value for the latest period among filings public by that day; a value
    whose period ended more than ``stale_days`` before is dropped (a line the filer
    stopped tagging)."""
    if not rows:
        return pd.Series(np.nan, index=index)
    frame = pd.DataFrame(rows, columns=["end", "filed", "val"])
    frame["end"] = pd.to_datetime(frame["end"])
    frame["filed"] = pd.to_datetime(frame["filed"])
    frame = frame.sort_values(["filed", "end"])
    # Per filing date, the latest period it reports; a later filing restating an
    # older period does not replace a newer one already public.
    latest = frame.groupby("filed").tail(1)
    latest = latest[latest["end"] >= latest["end"].cummax()]
    latest = latest.drop_duplicates("filed", keep="last").set_index("filed")
    full = index.union(latest.index)
    value = latest["val"].reindex(full).ffill().reindex(index)
    end = pd.to_datetime(latest["end"].reindex(full).ffill().reindex(index))
    age = (pd.Series(index, index=index) - end).dt.days
    return value.where(age <= stale_days)


def debt_parts(kept: dict, index: pd.DatetimeIndex, stale_days: int) -> tuple[pd.Series, pd.Series]:
    """Debt due within a year and long-term debt, as filed by each day."""
    zero = pd.Series(0.0, index=index)
    read = lambda tag: as_of(kept.get(tag), index, stale_days)  # noqa: E731
    lease_now = read(LEASE_CURRENT).fillna(0)
    parts = sum((read(tag).fillna(0) for tag in SHORT_PARTS), zero)
    short = pd.concat([read(SHORT_TOTAL).fillna(0) + lease_now, read(SHORT_WITH_LEASES).fillna(0),
                       parts + lease_now], axis=1).max(axis=1)
    long_parts = sum((read(tag).fillna(0) for tag in LONG_PARTS), zero)
    # A filer tagging only the total long-term debt: the non-current part is total less current.
    from_total = (read(LONG_TOTAL) - read("LongTermDebtCurrent").fillna(0)).clip(lower=0).fillna(0)
    by_instrument = sum((read(tag).fillna(0) for tag in BY_INSTRUMENT), zero)
    long_ = pd.concat([long_parts, read(LONG_WITH_LEASES).fillna(0), from_total, by_instrument], axis=1).max(axis=1)
    # Neither side filed: one combined figure, counted as long-term (the milder reading).
    combined = pd.concat([read(tag).fillna(0) for tag in ALL_DEBT], axis=1).max(axis=1)
    long_ = long_.where((short + long_) > 0, combined)
    # Debt the note counts beyond the lines read (maturity unknown): counted as long-term.
    extra = (read(CARRYING).fillna(0) - (short + long_)).clip(lower=0)
    return short, long_ + extra


def default_point(kept: dict, index: pd.DatetimeIndex, stale_days: int) -> pd.Series:
    """Debt due within a year plus half the long-term debt (the KMV default point)."""
    short, long_ = debt_parts(kept, index, stale_days)
    point = short + 0.5 * long_
    return point.where(point > 0)


def total_debt(kept: dict, index: pd.DatetimeIndex, stale_days: int) -> pd.Series:
    """All the debt the measure counts, for the check against what the filer reports."""
    short, long_ = debt_parts(kept, index, stale_days)
    return short + long_


def shares(kept: dict, index: pd.DatetimeIndex, stale_days: int, split_after) -> pd.Series:
    """Shares outstanding as filed by each day, on today's split basis: a count filed
    before a split is scaled by the splits after its filing date (``split_after``)."""
    # The source still in use: the one with the newest period (cover pages and balance
    # sheets go stale when a filer stops tagging them); a zero count is not a count.
    candidates = [tuple(r for r in kept.get(tag) or () if r[2] > 0) for tag in (*(t for _, t in SHARE_TAGS), DILUTED)]
    candidates = [rows for rows in candidates if rows]
    if not candidates:
        return pd.Series(np.nan, index=index)
    rows = max(candidates, key=lambda rows: max(r[0] for r in rows))
    scaled = tuple((end, filed, val * split_after(str(filed))) for end, filed, val in rows)
    return as_of(scaled, index, stale_days)


def naive_dd(E, F, sE, r, T: float = 1.0):
    sD = 0.05 + 0.25 * sE
    V = E + F
    sV = E / V * sE + F / V * sD
    return (np.log(V / F) + (r - 0.5 * sV ** 2) * T) / (sV * math.sqrt(T))


def default_probability(dd):
    """N(-DD): the model's one-year probability under its own assumptions, not a market price."""
    values = np.asarray(dd, dtype=float)
    # N(-x) = erfc(x / sqrt 2) / 2, without a SciPy dependency.
    return 0.5 * np.vectorize(math.erfc)(values / math.sqrt(2))


def distance_series(prices: pd.Series, kept: dict, rate: pd.Series, *, split_after, stale_days: int,
                    vol_sessions: int = TRADING_DAYS, market_cap_now: float | None = None) -> pd.DataFrame:
    """Daily equity value, default point, volatility and distance to default for one name.

    ``market_cap_now`` (VALUATION's figure, every share class counted) scales the filed
    share count, so a cover page that lists one class does not halve the company."""
    prices = prices.dropna()
    prices = prices[prices > 0]
    if prices.empty:
        return pd.DataFrame()
    index = prices.index
    count = shares(kept, index, stale_days, split_after)
    E = prices * count
    if market_cap_now and pd.notna(E.iloc[-1]) and E.iloc[-1] > 0:
        E = E * (market_cap_now / E.iloc[-1])
    F = default_point(kept, index, stale_days)
    vol = np.log(prices).diff().rolling(vol_sessions, min_periods=vol_sessions // 2).std() * math.sqrt(TRADING_DAYS)
    r = rate.reindex(index.union(rate.index)).ffill().reindex(index)
    frame = pd.DataFrame({"E": E, "F": F, "sE": vol, "r": r}).dropna()
    if frame.empty:
        return frame
    frame["dd"] = naive_dd(frame["E"], frame["F"], frame["sE"], frame["r"])
    # Counted debt jumping tenfold at one filing means the filings before it held the
    # debt under tags this does not read (Nebius before its first 10-K): the path
    # before the jump would look far safer than the company was, so it is left out.
    jump = frame["F"] / frame["F"].shift(1)
    late = jump[jump >= DEBT_JUMP]
    if not late.empty:
        frame = frame[frame.index >= late.index[-1]]
    return frame


def own_percentile(series: pd.Series, value: float) -> float | None:
    """Where today's distance sits in the name's own history: share of days at or below it."""
    history = series.dropna()
    if len(history) < 60 or value is None or not np.isfinite(value):
        return None
    return float((history <= value).mean() * 100)
