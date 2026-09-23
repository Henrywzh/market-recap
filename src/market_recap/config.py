"""Paths, cache policy and the parsed dashboard contract.

Every panel reads its universe and labels from ``config/dashboard.toml``. A
builder that hard-codes a ticker or a series id is a bug: the contract is the
single place that says what this dashboard claims to cover.

Numbers that are *definitions* live here as named constants -- a trading year
is 252 sessions whatever the user wants the page to show. Numbers that are
*choices* live in the TOML, because someone should be able to change what the
page covers without editing Python.
"""

from __future__ import annotations

from datetime import time, timedelta
from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "dashboard.toml"

CACHE_DIR = REPO_ROOT / "data" / "cache"
ARTIFACT_DIR = REPO_ROOT / "artifacts"
TICKER_ARTIFACT_DIR = ARTIFACT_DIR / "tickers"
DCF_ARTIFACT_DIR = ARTIFACT_DIR / "dcf"
FINANCIALS_ARTIFACT_DIR = ARTIFACT_DIR / "financials"
VALUATION_ARTIFACT_DIR = ARTIFACT_DIR / "valuation"
ETF_ARTIFACT_DIR = ARTIFACT_DIR / "etfs"
XRAY_ARTIFACT_DIR = ARTIFACT_DIR / "xray"

# Identify this client honestly. Sending a Chrome User-Agent from a Python
# process is actively counter-productive: FRED's edge accepts curl's own
# identifier instantly and stalls the same request when it claims to be a
# browser, because the claim contradicts the TLS fingerprint. SEC additionally
# requires a contactable identifier from automated clients.
USER_AGENT = "market-recap/0.1 (research; henrywzh88@gmail.com)"
SEC_USER_AGENT = USER_AGENT

# --- Calendar definitions ---------------------------------------------------
# A US trading year, used wherever a per-session figure is annualised. It is a
# convention, not a preference, so it is not in the TOML.
TRADING_DAYS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# Period windows shared by every multi-period table and heat map in the site.
# Trading-day counts, not calendar days: a return labelled 1M must be measured
# the same way on every panel or the tabs disagree with each other. ``YTD`` is
# deliberately ``None`` -- it is a calendar rule, not a fixed window, and every
# helper that walks this table has to branch on it anyway.
PERIOD_TRADING_DAYS: dict[str, int | None] = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "YTD": None,
    "1Y": TRADING_DAYS_PER_YEAR,
    "2Y": TRADING_DAYS_PER_YEAR * 2,
    "3Y": TRADING_DAYS_PER_YEAR * 3,
    "5Y": TRADING_DAYS_PER_YEAR * 5,
    "10Y": TRADING_DAYS_PER_YEAR * 10,
}

# The longest window any chart offers, and therefore how much history a baked
# per-ticker artifact needs to carry. One number, so the technicals chart, the
# flow chart and the cross-listing chart cannot drift apart.
CHART_SESSIONS = PERIOD_TRADING_DAYS["2Y"]


def period_sessions(label: str) -> int | None:
    """Sessions in a named window. Raises on an unknown label rather than
    silently returning ``None``, which a caller would read as "YTD"."""
    if label not in PERIOD_TRADING_DAYS:
        raise KeyError(f"unknown period {label!r}; known: {', '.join(PERIOD_TRADING_DAYS)}")
    return PERIOD_TRADING_DAYS[label]


# --- Freshness --------------------------------------------------------------
# A quote older than one session is not a "latest" value; a daily history may
# legitimately span a weekend or an exchange holiday.
#
# ``monthly_release`` is dated by the observation's *reference month*, not by
# when it was published. July PCE is the current print through late September
# because BEA publishes it with a two-month lag, so a window sized to the
# reference date has to carry that lag or it labels a perfectly current series
# stale every single month.
FRESHNESS = {
    "daily_close": {"stale_after_calendar_days": 7},
    "published_curve": {"stale_after_calendar_days": 7},
    "monthly_release": {"stale_after_calendar_days": 100},
    "fund_holdings": {"stale_after_calendar_days": 10},
    # The newest 10-K/10-Q across the whole universe. Some member files one in
    # almost every week of the year; three without any means the check broke.
    "filings": {"stale_after_calendar_days": 21},
    # Vanguard publishes holdings monthly, a few weeks after month end.
    "monthly_holdings": {"stale_after_calendar_days": 60},
}
DEFAULT_FRESHNESS_POLICY = "daily_close"

# How old the *build itself* may be before the page stops calling itself
# current. Published into the manifest so the browser reads one set of
# thresholds rather than a second copy hard-coded in JavaScript.
BUILD_AGE_HOURS = {"current": 24, "recent": 72}

# --- Cache policy -----------------------------------------------------------
# One table instead of a TTL invented separately inside each source module.
# The key names the *kind* of thing being cached, because the right lifetime
# follows from how often the publisher changes it, not from which vendor it is.
#
# ``missing`` is the negative cache: how long to believe a 404. An issuer that
# does not publish a file for a fund today will not start within the week, and
# re-probing thirty-four funds on every build cost more than the fetches that
# succeeded.
CACHE_TTL = {
    "intraday_snapshot": timedelta(hours=12),   # quotes / fund facts
    "daily_file": timedelta(days=1),            # per session: see SESSION_KINDS
    "macro_series": timedelta(hours=12),        # FRED, revised on a publication schedule
    "reference_data": timedelta(days=7),        # ticker maps, screeners, GICS labels
    # SEC company facts are refetched when the filer's submissions index shows
    # a newer 10-K/10-Q, or when they pass a backstop age staggered by filer
    # (sources.sec); this lifetime is only the last resort behind both.
    "filings": timedelta(days=40),
    "missing": timedelta(days=7),               # negative cache for a 404
}


# A session is "complete" when nearly the whole panel has printed a close.
# Anything less is a session in progress: the provider serves an intraday bar
# for whatever it refreshed most recently, and a few hundred cached symbols
# still end on the prior close. The same share decides when a basket return
# still describes the basket rather than part of it.
SESSION_COVERAGE_THRESHOLD = 0.90

# A "daily" file is stale once a new session has been published, not 24 hours
# after it was fetched. With a pure TTL, a nightly run that starts a few minutes
# earlier than the night before finds yesterday's closes still "fresh", never
# fetches today's session, and passes validation a day behind. So these kinds
# are also invalidated at every rollover: the weekday time in New York by which
# the evening publishers (State Street holdings/NAV, Treasury's par curve, the
# settled close) have posted. The nightly job runs after it for the same reason.
SESSION_KINDS = frozenset({"daily_file"})
MARKET_TIMEZONE = "America/New_York"
SESSION_ROLLOVER = time(18, 30)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def ensure_dirs() -> None:
    for path in (CACHE_DIR, ARTIFACT_DIR, TICKER_ARTIFACT_DIR, DCF_ARTIFACT_DIR, FINANCIALS_ARTIFACT_DIR, VALUATION_ARTIFACT_DIR, ETF_ARTIFACT_DIR,
                 XRAY_ARTIFACT_DIR):
        path.mkdir(parents=True, exist_ok=True)
