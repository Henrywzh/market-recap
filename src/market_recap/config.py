"""Paths and the parsed dashboard contract.

Every panel reads its universe and labels from ``config/dashboard.toml``. A
builder that hard-codes a ticker or a series id is a bug: the contract is the
single place that says what this dashboard claims to cover.
"""

from __future__ import annotations

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
ETF_ARTIFACT_DIR = ARTIFACT_DIR / "etfs"

# Identify this client honestly. Sending a Chrome User-Agent from a Python
# process is actively counter-productive: FRED's edge accepts curl's own
# identifier instantly and stalls the same request when it claims to be a
# browser, because the claim contradicts the TLS fingerprint. SEC additionally
# requires a contactable identifier from automated clients.
USER_AGENT = "market-recap/0.1 (research; henrywzh88@gmail.com)"
SEC_USER_AGENT = USER_AGENT

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
}

# Period windows shared by every multi-period table and heat map in the site.
# Trading-day counts, not calendar days: a return labelled 1M must be measured
# the same way on every panel or the tabs disagree with each other.
PERIOD_TRADING_DAYS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
    "3Y": 756,
    "5Y": 1260,
    "10Y": 2520,
}


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def ensure_dirs() -> None:
    for path in (CACHE_DIR, ARTIFACT_DIR, TICKER_ARTIFACT_DIR, DCF_ARTIFACT_DIR, ETF_ARTIFACT_DIR):
        path.mkdir(parents=True, exist_ok=True)
