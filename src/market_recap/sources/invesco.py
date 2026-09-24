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
