"""ETF creations and redemptions, measured from issuers' published unit counts.

Net flow is the change in shares outstanding priced at that day's NAV: the
primary-market (authorised participant) creations less redemptions. It says how
much money moved through each fund's creation mechanism, not who the end buyer
was. This module is arithmetic only; fetching lives in the sources and the
payload assembly in panels/flows_etf.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clean_float

# (ticker, short label, group). The page lists them in this order. US equity
# funds are grouped by the index they track, so a group's total is that
# index's money, and the US equity total is every covered index fund once.
FUNDS = (
    ("SPY", "S&P 500 · SPDR", "S&P 500"),
    ("IVV", "S&P 500 · iShares", "S&P 500"),
    ("SPYM", "S&P 500 · SPDR Portfolio", "S&P 500"),
    ("QQQ", "Nasdaq-100 · Invesco", "Nasdaq-100"),
    ("QQQM", "Nasdaq-100 · Invesco M", "Nasdaq-100"),
    ("QNDX", "Nasdaq-100 · SPDR", "Nasdaq-100"),
    ("ITOT", "Total market · iShares", "Total market"),
    ("SPTM", "Total market · SPDR", "Total market"),
    ("IWV", "Russell 3000", "Total market"),
    ("IWB", "Russell 1000", "Total market"),
    ("IWF", "Russell 1000 Growth", "Growth"),
    ("IVW", "S&P 500 Growth · iShares", "Growth"),
    ("SPYG", "S&P 500 Growth · SPDR", "Growth"),
    ("IWD", "Russell 1000 Value", "Value"),
    ("IVE", "S&P 500 Value · iShares", "Value"),
    ("SPYV", "S&P 500 Value · SPDR", "Value"),
    ("IJH", "S&P MidCap 400 · iShares", "Mid cap"),
    ("MDY", "S&P MidCap 400 · SPDR", "Mid cap"),
    ("SPMD", "S&P MidCap 400 · SPDR Portfolio", "Mid cap"),
    ("IWM", "Russell 2000", "Small cap"),
    ("IJR", "S&P SmallCap 600 · iShares", "Small cap"),
    ("SPSM", "S&P SmallCap 600 · SPDR", "Small cap"),
    ("RSP", "S&P 500 equal weight", "Equal weight"),
    ("DIA", "Dow Jones", "Dow"),
    ("XLK", "Technology", "Sectors"),
    ("XLF", "Financials", "Sectors"),
    ("XLV", "Health care", "Sectors"),
    ("XLI", "Industrials", "Sectors"),
    ("XLE", "Energy", "Sectors"),
    ("XLP", "Staples", "Sectors"),
    ("XLY", "Discretionary", "Sectors"),
    ("XLU", "Utilities", "Sectors"),
    ("XLB", "Materials", "Sectors"),
    ("XLRE", "Real estate", "Sectors"),
    ("XLC", "Communication", "Sectors"),
    ("SOXX", "Semiconductors", "Sectors"),
    ("SHY", "1-3yr Treasuries", "Treasuries"),
    ("IEF", "7-10yr Treasuries", "Treasuries"),
    ("TLT", "20yr+ Treasuries", "Treasuries"),
    ("LQD", "Investment grade", "Credit"),
    ("HYG", "High yield", "Credit"),
    ("AGG", "Broad bonds", "Broad bonds"),
    ("GLD", "Gold", "Gold"),
    ("EFA", "Developed ex-US", "International"),
    ("EEM", "Emerging markets", "International"),
)

US_EQUITY_GROUPS = ("S&P 500", "Nasdaq-100", "Total market", "Growth", "Value", "Mid cap", "Small cap",
                    "Equal weight", "Dow")

# Large funds with no share-count history on any file this page reads, with the
# group they would belong to: listed with the reason, and their assets counted
# against each group's coverage, never dropped silently.
VANGUARD = "Vanguard publishes no daily share count; only month-end share-class assets, rounded"
SCHWAB = "Schwab's fund pages refuse automated requests"
NOT_COVERED = (
    ("VOO", "Vanguard S&P 500", "S&P 500", VANGUARD),
    ("VTI", "Vanguard Total Market", "Total market", VANGUARD),
    ("VUG", "Vanguard Growth", "Growth", VANGUARD),
    ("VTV", "Vanguard Value", "Value", VANGUARD),
    ("VO", "Vanguard Mid-Cap", "Mid cap", VANGUARD),
    ("VB", "Vanguard Small-Cap", "Small cap", VANGUARD),
    ("SCHX", "Schwab U.S. Large-Cap", "Total market", SCHWAB),
    ("SCHB", "Schwab U.S. Broad Market", "Total market", SCHWAB),
    ("VEA", "Vanguard Developed Markets", "International", VANGUARD),
    ("VWO", "Vanguard Emerging Markets", "International", VANGUARD),
)

# Aggregate name -> member tickers: one per US equity group, the US equity
# total, and the cross-asset groups.
AGGREGATES = (
    ("US equity", tuple(t for t, _, g in FUNDS if g in US_EQUITY_GROUPS)),
    *((group, tuple(t for t, _, g in FUNDS if g == group)) for group in US_EQUITY_GROUPS if group not in ("Equal weight", "Dow")),
    ("Treasuries", ("SHY", "IEF", "TLT")),
    ("Credit", ("LQD", "HYG")),
    ("Gold", ("GLD",)),
)

# Trading-session windows for the fund table; the labels match config's period names.
WINDOW_SESSIONS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}
AGGREGATE_WINDOW = 252
ROLLING_SESSIONS = 20
RANK_YEARS = 3
MIN_RANK_HISTORY_DAYS = 365
# Lookback for the page's day-by-day history and for excluded-day reporting.
HISTORY_YEARS = 3

# A split multiplies the unit count by a whole number k (or divides by k) and
# the NAV by the inverse, so market value does not move. A creation changes
# market value, so it cannot pass the second test.
SPLIT_MAX_FACTOR = 20
SPLIT_UNITS_TOLERANCE = 0.05  # relative distance of the unit ratio from k or 1/k
SPLIT_VALUE_TOLERANCE = 0.10  # |units ratio x NAV ratio - 1|: room for the day's market move

# Without a session calendar, a row more than this many calendar days after the
# one before it is a gap: the next flow would span more than one session.
MAX_GAP_DAYS = 4


def split_mask(shares: pd.Series, nav: pd.Series) -> pd.Series:
    """True on a day the units and NAV moved the way a split moves them."""
    units = (shares / shares.shift(1)).to_numpy(dtype=float)
    value = ((shares / shares.shift(1)) * (nav / nav.shift(1))).to_numpy(dtype=float)
    near = np.zeros(len(units), dtype=bool)
    for k in range(2, SPLIT_MAX_FACTOR + 1):
        near |= np.abs(units - k) <= SPLIT_UNITS_TOLERANCE * k
        near |= np.abs(units - 1.0 / k) <= SPLIT_UNITS_TOLERANCE / k
    flat_value = np.abs(value - 1.0) <= SPLIT_VALUE_TOLERANCE
    return pd.Series(near & flat_value, index=shares.index)


def _consecutive(index: pd.DatetimeIndex, sessions: pd.DatetimeIndex | None) -> np.ndarray:
    """True where a row directly follows the row before it.

    With a session calendar, no session may lie strictly between the two rows,
    so a holiday is not a gap and a missing session is. Without one, a row more
    than MAX_GAP_DAYS calendar days after its predecessor is a gap.
    """
    if len(index) == 0:
        return np.zeros(0, dtype=bool)
    if sessions is None or len(sessions) == 0:
        gaps = pd.Series(index).diff().dt.days.to_numpy(dtype=float)
        return np.nan_to_num(gaps, nan=np.inf) <= MAX_GAP_DAYS
    calendar = pd.DatetimeIndex(sessions).sort_values().unique().to_numpy()
    values = index.to_numpy()
    between = np.searchsorted(calendar, values[1:], side="left") - np.searchsorted(calendar, values[:-1], side="right")
    return np.r_[False, between == 0]


def daily_flow(shares: pd.Series, nav: pd.Series, *, sessions: pd.DatetimeIndex | None = None) -> pd.Series:
    """Change in units priced at that day's NAV: creations less redemptions, in dollars.

    Null on a split day, after a gap in the record, and wherever either value is
    missing. Nothing is forward-filled: a missing count is a missing flow.
    """
    shares = pd.to_numeric(shares, errors="coerce")
    nav = pd.to_numeric(nav, errors="coerce")
    flow = shares.diff() * nav
    bad = split_mask(shares, nav).to_numpy() | ~_consecutive(shares.index, sessions)
    return flow.mask(bad)


def excluded_days(shares: pd.Series, nav: pd.Series, *, sessions: pd.DatetimeIndex | None = None) -> list[tuple[pd.Timestamp, str]]:
    """Days whose flow is withheld, and why. Used for the page's audit list."""
    shares = pd.to_numeric(shares, errors="coerce")
    nav = pd.to_numeric(nav, errors="coerce")
    out: list[tuple[pd.Timestamp, str]] = []
    splits = split_mask(shares, nav)
    consecutive = _consecutive(shares.index, sessions)
    moved = shares.diff().notna().to_numpy()
    for i, stamp in enumerate(shares.index):
        if splits.iloc[i]:
            out.append((stamp, "split: units and NAV moved inversely"))
        elif moved[i] and not consecutive[i]:
            out.append((stamp, "gap in the issuer's record"))
    return out


def window_sum(flow: pd.Series, sessions: int) -> float | None:
    """Sum of the last ``sessions`` flows. None when history is short or any day in it is withheld."""
    tail = flow.tail(sessions)
    if len(tail) < sessions or tail.isna().any():
        return None
    return clean_float(tail.sum(), 0)


def percentile_1w(flow: pd.Series) -> float | None:
    """Where the latest 5-session flow sits among every 5-session flow of the last three years.

    None without a year of history: a percentile of a few months measures the
    recent regime, not the fund's usual flow.
    """
    sums = flow.rolling(WINDOW_SESSIONS["1W"], min_periods=WINDOW_SESSIONS["1W"]).sum()
    if sums.empty or pd.isna(sums.iloc[-1]) or flow.index[0] > sums.index[-1] - pd.Timedelta(days=MIN_RANK_HISTORY_DAYS):
        return None
    last = sums.index[-1]
    recent = sums[sums.index > last - pd.DateOffset(years=RANK_YEARS)].dropna()
    return clean_float(100.0 * (recent <= sums.iloc[-1]).mean(), 0)


def fund_summary(flow: pd.Series, *, aum: float | None) -> dict:
    """Window flows, flow as a share of assets, and the 1-week percentile for one fund."""
    windows = {name: window_sum(flow, sessions) for name, sessions in WINDOW_SESSIONS.items()}
    month = windows["1M"]
    return {
        "aum": clean_float(aum, 0),
        "flow_1d": windows["1D"],
        "flow_1w": windows["1W"],
        "flow_1m": month,
        "flow_3m": windows["3M"],
        "flow_1m_pct_aum": clean_float(month / aum, 6) if month is not None and aum else None,
        "pct_rank_1w": percentile_1w(flow),
    }


def aggregate(flows: dict[str, pd.Series], *, window: int = AGGREGATE_WINDOW) -> dict:
    """One total across funds, day by day, over the last ``window`` dates.

    The day-by-day line and its rank keep to the funds whose history starts on
    or before the window's first date, so a fund listed partway through does
    not look like a jump in the total (``funds``; ``count`` per date). The
    latest 1D/1W/1M sums count every fund whose record covers that window, so
    a fund recorded for weeks (QQQ) is in the week's total (``latest_funds``).
    """
    empty = {"funds": [], "excluded": list(flows), "dates": [], "flow": [], "rolling_20": [], "count": [],
             "latest_date": None, "latest": {}, "latest_funds": []}
    if not flows:
        return empty
    frame = pd.concat(flows, axis=1).sort_index()
    frame = frame[frame.notna().any(axis=1)]
    if frame.empty:
        return empty
    starts = {t: (series.first_valid_index() if series.first_valid_index() is not None else series.index[-1])
              for t, series in flows.items()}
    lasts = {t: series.last_valid_index() for t, series in flows.items()}

    window_start = frame.index[-window] if len(frame.index) >= window else frame.index[0]
    included = [t for t in flows if flows[t].index[0] <= window_start]
    excluded = [t for t in flows if t not in included]
    # The windows end on the long-history funds' latest date: a fund whose
    # issuer publishes a day earlier or later does not move the week.
    end = frame[included].dropna(how="all").index[-1] if included else frame.index[-1]
    upto = frame.loc[:end]

    def recent(sessions: int) -> tuple[float | None, list[str]]:
        rows = upto.iloc[-sessions:]
        if len(rows) < sessions:
            return None, []
        # A fund counts only if its record spans the window: one whose issuer
        # record stopped before the window's end would be a partial week.
        members = [t for t in flows if starts[t] <= rows.index[0] and lasts[t] is not None and lasts[t] >= rows.index[-1]]
        if not members:
            return None, []
        return clean_float(rows[members].sum(axis=1, min_count=1).sum(min_count=1), 0), members

    week, week_funds = recent(WINDOW_SESSIONS["1W"])
    latest = {"flow_1d": recent(1)[0], "flow_1w": week, "flow_1m": recent(WINDOW_SESSIONS["1M"])[0],
              "pct_rank_1w": None, "rolling_20": None}
    out = {**empty, "excluded": excluded, "latest_date": end.strftime("%Y-%m-%d"),
           "latest": latest, "latest_funds": week_funds}
    if not included:
        return out

    members = frame[included]
    total = members.sum(axis=1, min_count=1)
    count = members.notna().sum(axis=1)
    keep = count > 0
    total, count = total[keep], count[keep]
    rolling = total.rolling(ROLLING_SESSIONS, min_periods=ROLLING_SESSIONS).sum()
    tail = slice(-window, None)
    # The rank compares like with like: the long-history funds' week against their own past weeks.
    latest["pct_rank_1w"] = percentile_1w(total)
    latest["rolling_20"] = clean_float(rolling.iloc[-1], 0) if not rolling.empty else None
    return {
        **out,
        "funds": included,
        "dates": [d.strftime("%Y-%m-%d") for d in total.index[tail]],
        "flow": [clean_float(v, 0) for v in total.iloc[tail]],
        "rolling_20": [clean_float(v, 0) for v in rolling.iloc[tail]],
        "count": [int(v) for v in count.iloc[tail]],
    }