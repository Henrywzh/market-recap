"""Invesco ETF holdings, from the JSON API behind invesco.com's fund pages.

The fund is named by CUSIP: asked by ticker, the API answers for QQQ but
returns HTTP 500 for RSP and most other funds. Weights are the issuer's
percent of total net assets, so cash, futures and money-market lines keep
their share of the fund and the stock sleeve sums below 100%.
"""

from __future__ import annotations

import json

import pandas as pd

from .. import cache
from .http import FetchError, get_text

NAMESPACE = "invesco"
HOLDINGS_URL = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{cusip}"
                "/holdings/fund?idType=cusip&productType=ETF")
HOME_URL = "https://www.invesco.com/us/en/financial-products/etfs.html"
# The contact-free project UA, as for Nasdaq; the API needs no browser headers.
USER_AGENT = "market-recap/0.1"
# Listed shares, however Invesco types them: common stock, ADRs, NY-registry
# shares, REITs. Everything else (currency, futures, their synthetic cash
# offset, money-market funds, rights) is not an equity holding.
EQUITY_TYPES = frozenset({"COM", "ADR", "DRNY", "REIT"})


def parse_holdings(payload: dict) -> tuple[pd.DataFrame, str | None]:
    lines = payload.get("holdings") or []
    frame = pd.DataFrame({
        "ticker": [str(h.get("ticker") or "").strip().upper() for h in lines],
        "name": [h.get("issuerName") for h in lines],
        "cusip": [h.get("cusip") for h in lines],
        "weight": pd.to_numeric([h.get("percentageOfTotalNetAssets") for h in lines], errors="coerce") / 100.0,
        "asset_class": ["Equity" if h.get("securityTypeCode") in EQUITY_TYPES else "Other" for h in lines],
    })
    frame["name"] = frame["name"].astype(str).str.replace("&amp;", "&", regex=False)
    return frame.dropna(subset=["weight"]), payload.get("effectiveDate")


def fetch_holdings(cusip: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str | None, str]:
    url = HOLDINGS_URL.format(cusip=cusip)
    text = cache.fetch_text(NAMESPACE, f"holdings-{cusip}",
                            lambda: get_text(url, user_agent=USER_AGENT, timeout=30.0, retries=2),
                            kind="daily_file", suffix=".json", use_cache=use_cache)
    frame, as_of = parse_holdings(json.loads(text))
    if frame.empty:
        raise FetchError(f"{cusip}: Invesco returned no holdings")
    return frame, as_of, url


# --- Published NAV, units and premium ----------------------------------------
# Invesco publishes today's NAV and shares outstanding, but no history of the
# units: a flow series for its funds can only be built by recording the daily
# figure (snapshots/risk.py) and differencing the record. Its premium/discount
# history, by contrast, is published for the current and previous year.
PRICES_URL = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{cusip}"
              "/prices?idType=cusip&variationType=priceListing&productType=ETF&productSubType=ETF")
PREMIUM_URL = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{cusip}"
               "/navs?idType=cusip&productType=ETF&variationType=premiumDiscounts")


def cusip_for(holdings_source: str | None) -> str | None:
    """The CUSIP in an ``invesco:<CUSIP>`` holdings entry, else None."""
    if not holdings_source or not holdings_source.startswith("invesco:"):
        return None
    return holdings_source.split(":", 1)[1].strip() or None


def parse_units(payload: dict) -> dict:
    return {
        "date": payload.get("effectiveDate"),
        "nav": payload.get("nav"),
        "shares_outstanding": payload.get("sharesOutstanding"),
    }


def fetch_units(cusip: str) -> dict:
    """Today's published NAV and shares outstanding, with their effective date.
    Never cached: a stale answer recorded as today's would be a false flow."""
    payload = json.loads(get_text(PRICES_URL.format(cusip=cusip), user_agent=USER_AGENT, timeout=30.0, retries=2))
    units = parse_units(payload)
    if not units["date"] or units["shares_outstanding"] is None or units["nav"] is None:
        raise FetchError(f"{cusip}: Invesco returned no NAV or shares outstanding")
    return units


def parse_premium(payload: dict) -> pd.DataFrame:
    rows = [
        {"date": row.get("effectiveDate"), "premium_pct": row.get("bidAskMidpointPremiumDiscountPercentage")}
        for period in (payload.get("premiumDiscounts") or {}).values()
        for row in period or []
    ]
    frame = pd.DataFrame(rows, columns=["date", "premium_pct"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["premium_pct"] = pd.to_numeric(frame["premium_pct"], errors="coerce")
    return frame.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_premium_history(cusip: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """The issuer's premium/discount of the bid/ask midpoint to NAV, in percent."""
    url = PREMIUM_URL.format(cusip=cusip)
    text = cache.fetch_text(NAMESPACE, f"premium-{cusip}",
                            lambda: get_text(url, user_agent=USER_AGENT, timeout=30.0, retries=2),
                            kind="daily_file", suffix=".json", use_cache=use_cache)
    return parse_premium(json.loads(text)), url
