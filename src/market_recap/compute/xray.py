"""ETF X-RAY: what a fund holds, computed from the issuer's own holdings file.

Weights are fractions of the fund as the issuer states them. Every summary
here is over the lines the file lists; a figure that needs data this build
does not have (a price, a sector) says how much of the fund it covers rather
than quietly renormalising the rest into a whole.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

UNCLASSIFIED = "Unclassified"
CASH_LABEL = "Cash / no maturity"
TOP_WEIGHT_LINES = 10

# Remaining-maturity buckets for a bond fund, in years: (label, upper bound).
MATURITY_BUCKETS = (
    ("0-1y", 1), ("1-3y", 3), ("3-5y", 5), ("5-7y", 7), ("7-10y", 10), ("10-20y", 20), ("20y+", np.inf),
)
DAYS_PER_YEAR = 365.25

_SEPARATORS = re.compile(r"[.\-/ ]")


def ticker_key(ticker: str) -> str:
    """Issuers disagree on class-share tickers: SSGA writes BRK.B, iShares BRKB,
    Yahoo BRK-B. Comparing without separators matches all three."""
    return _SEPARATORS.sub("", str(ticker).upper())


# Exchanges whose listings this build prices. A ticker only means the same
# company within one market: EFA's DG (Vinci, Paris) and EL (EssilorLuxottica)
# are not Dollar General and Estee Lauder. Whole names, because "Nyse Euronext
# - Euronext Paris" and "Nasdaq Omx Nordic" are European exchanges.
US_EXCHANGES = re.compile(r"^(?:NASDAQ|NYSE|New York Stock Exchange.*|Nyse Mkt Llc|Cboe .*|Non-Nms .*)$")

# iShares labels some funds' sector "Communication"; GICS calls it this.
SECTOR_ALIASES = {"Communication": "Communication Services"}


def holding_key(ticker: str, us_listed: bool) -> str:
    """A holding's identity across funds: its ticker, within its market."""
    return ("US:" if us_listed else "XUS:") + ticker_key(ticker)


def resolve_symbols(tickers: pd.Series, known: list[str]) -> pd.Series:
    """Map issuer tickers onto this build's own symbols where they match one,
    so a holding can be priced and joined; anything else keeps its own ticker."""
    lookup = {ticker_key(symbol): symbol for symbol in known}
    return tickers.map(lambda t: lookup.get(ticker_key(t), str(t).upper()))


def effective_n(weights: pd.Series) -> float | None:
    """1 / sum of squared weights: the number of equal holdings with the same
    concentration. SPY's 503 lines behave like ~50."""
    w = weights.dropna()
    total = w.sum()
    if total <= 0:
        return None
    return float(1.0 / ((w / total) ** 2).sum())


def top_weight(weights: pd.Series, lines: int = TOP_WEIGHT_LINES) -> float:
    return float(weights.nlargest(lines).sum())


def breakdown(frame: pd.DataFrame, column: str) -> list[dict]:
    """Weight by label, largest first. A missing label is counted, not dropped."""
    if column not in frame:
        return []
    labels = frame[column].fillna(UNCLASSIFIED).replace({"": UNCLASSIFIED, "-": UNCLASSIFIED})
    grouped = frame["weight"].groupby(labels).sum().sort_values(ascending=False)
    return [{"label": str(label), "weight": float(weight)} for label, weight in grouped.items()]


def overlap(a: pd.Series, b: pd.Series) -> float:
    """Sum over common holdings of the smaller weight, each fund's weights taken
    as shares of its own listed holdings. 1.0 is the same basket."""
    a = a.groupby(level=0).sum()
    b = b.groupby(level=0).sum()
    a, b = a / a.sum(), b / b.sum()
    common = a.index.intersection(b.index)
    return float(np.minimum(a[common], b[common]).sum())


def attribution(weights: pd.Series, returns: pd.Series) -> dict:
    """Each priced holding's weight times its return, in percentage points of the fund.

    ``covered`` is the share of the fund that could be priced: for a small-cap
    or international fund it is small, and the sum explains only that part.
    """
    priced = returns.reindex(weights.index).dropna()
    contribution = (weights[priced.index] * priced).sort_values()
    return {
        "covered": float(weights[priced.index].sum()),
        "priced": int(len(priced)),
        "sum": float(contribution.sum()),
        "contribution": contribution,
    }


def bond_profile(frame: pd.DataFrame, as_of: str | None) -> dict:
    """Weighted duration, yield, coupon and remaining maturity of a bond fund.

    Averages run over every line that states the figure, cash included -- that
    is how the issuer computes its own fund duration -- and each carries the
    share of the fund it covers.
    """
    def weighted(column: str) -> tuple[float | None, float]:
        if column not in frame:
            return None, 0.0
        rows = frame.dropna(subset=[column])
        total = rows["weight"].sum()
        return (float((rows[column] * rows["weight"]).sum() / total) if total > 0 else None), float(total)

    duration, duration_cover = weighted("duration")
    ytm, ytm_cover = weighted("ytm")
    coupon, _ = weighted("coupon")

    years = None
    buckets: list[dict] = []
    if "maturity" in frame and as_of:
        remaining = (frame["maturity"] - pd.Timestamp(as_of)).dt.days / DAYS_PER_YEAR
        dated = remaining.notna()
        if dated.any():
            years = float((remaining[dated] * frame.loc[dated, "weight"]).sum() / frame.loc[dated, "weight"].sum())
        bounds = [0.0] + [upper for _, upper in MATURITY_BUCKETS]
        labels = [label for label, _ in MATURITY_BUCKETS]
        bucket = pd.cut(remaining.clip(lower=0), bins=bounds, labels=labels, include_lowest=True)
        bucket = bucket.astype(object).where(dated, CASH_LABEL)
        sums = frame["weight"].groupby(bucket).sum()
        buckets = [{"label": label, "weight": float(sums.get(label, 0.0))} for label in labels + [CASH_LABEL]]

    return {
        "duration": duration,
        "duration_covered": duration_cover,
        "ytm": ytm,
        "ytm_covered": ytm_cover,
        "coupon": coupon,
        "maturity_years": years,
        "maturity_buckets": buckets,
    }
