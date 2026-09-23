"""Vanguard fund profile and published price.

Vanguard does not expose a daily shares-outstanding history, so its ETFs get
no measured flow series here. Two things it does publish are worth having:

* ``premiumOrDiscount`` -- the issuer's own premium to NAV.
* ``hasMoreThan1ShareClass`` and ``associatedFundIds`` -- which say, from the
  issuer, that a Vanguard ETF is one share class of a fund that also has
  investor, admiral and institutional classes. That matters because the
  "total assets" a price vendor reports for VTI spans all of them: $2.3tn
  against an ETF share class a fraction of that size. Sizing a treemap tile
  with that number makes VTI the largest fund on the map, which is false.
  The flag is what lets the page say so instead of quietly drawing it.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .. import cache
from .http import FetchError, get_text

PROFILE_URL = "https://investor.vanguard.com/vmf/api/{ticker}/profile"
PRICE_URL = "https://investor.vanguard.com/vmf/api/{ticker}/price"
HOLDINGS_URL = "https://investor.vanguard.com/vmf/api/{ticker}/portfolio-holding/stock?start={start}&count={count}"
# Vanguard answers up to this many holdings per request; VTI has ~3,500.
HOLDINGS_PAGE = 1000
HOME_URL = "https://investor.vanguard.com"
NAMESPACE = "vanguard"


def _cached_json(url: str, name: str, *, use_cache: bool, kind: str = "intraday_snapshot") -> Any:
    text = cache.fetch_text(
        NAMESPACE,
        name,
        lambda: get_text(url, timeout=45.0, headers={"Accept": "application/json"}),
        kind=kind,
        suffix=".json",
        use_cache=use_cache,
    )
    return json.loads(text)


def fetch_fund_facts(ticker: str, *, use_cache: bool = True) -> dict:
    """Profile and price facts for one Vanguard ETF.

    Raises FetchError(not_found=True) for a ticker Vanguard does not serve, so
    a caller probing a mixed universe can skip it cheaply.
    """
    ticker = ticker.upper()
    profile = _cached_json(
        PROFILE_URL.format(ticker=ticker), f"profile-{ticker}", use_cache=use_cache
    )
    fund = (profile or {}).get("fundProfile") or {}
    # Vanguard is a brokerage as well as an issuer, so this endpoint answers
    # for funds it merely carries: QQQ comes back as "Invesco QQQ Trust" with
    # isExternalFund set and no premium. Only an internal fund is Vanguard
    # publishing about its own product, and only that is usable as a source.
    if not fund.get("ticker") or not fund.get("isInternalFund"):
        raise FetchError(f"{ticker}: not a Vanguard-issued fund", not_found=True)

    price = _cached_json(
        PRICE_URL.format(ticker=ticker), f"price-{ticker}", use_cache=use_cache
    )
    current = (price or {}).get("currentPrice") or {}
    nav = ((current.get("dailyPrice") or {}).get("regular") or {})

    def _float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "ticker": ticker,
        "fund_id": fund.get("fundId"),
        "is_etf": bool(fund.get("isETF")),
        "inception_date": str(fund.get("inceptionDate") or "")[:10] or None,
        "expense_ratio": fund.get("expenseRatio"),
        "multi_share_class": bool(fund.get("hasMoreThan1ShareClass")),
        "associated_fund_ids": fund.get("associatedFundIds") or {},
        "nav": _float(nav.get("price")),
        "nav_as_of": str(nav.get("asOfDate") or "")[:10] or None,
        "premium_pct": _float(current.get("premiumOrDiscount")),
        "source_url": PRICE_URL.format(ticker=ticker),
    }


def fetch_holdings(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str | None, str]:
    """(stock holdings, as-of date, url) for one Vanguard ETF.

    Vanguard publishes holdings monthly, a few weeks after month end, so the
    as-of date is shown beside every figure built on them. ``percentWeight``
    comes rounded to two decimals -- thousands of VWO's lines read 0.00, and
    summing them undercounts the stock sleeve by 9% -- so weights are market
    value over the total: shares of the fund's *stock holdings*, with its cash
    unseen. No sector or country is published.
    """
    ticker = ticker.upper()
    entities: list[dict] = []
    start, size = 1, None
    while size is None or start <= size:
        url = HOLDINGS_URL.format(ticker=ticker, start=start, count=HOLDINGS_PAGE)
        page = _cached_json(url, f"holdings-{ticker}-{start}", use_cache=use_cache, kind="reference_data")
        size = int(page.get("size") or 0)
        batch = ((page.get("fund") or {}).get("entity")) or []
        if not batch:
            break
        entities.extend(batch)
        start += HOLDINGS_PAGE
    if not entities:
        raise FetchError(f"{ticker}: no Vanguard holdings", not_found=True)
    frame = pd.DataFrame({
        "ticker": [str(e.get("ticker") or "").strip().upper() for e in entities],
        "name": [e.get("longName") for e in entities],
        "isin": [e.get("isin") for e in entities],
        "market_value": pd.to_numeric([e.get("marketValue") for e in entities], errors="coerce"),
    })
    frame["weight"] = frame["market_value"] / frame["market_value"].sum()
    frame["asset_class"] = "Equity"
    as_of = str(entities[0].get("asOfDate") or "")[:10] or None
    return frame, as_of, HOLDINGS_URL.format(ticker=ticker, start=1, count=HOLDINGS_PAGE)
