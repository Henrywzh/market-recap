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

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from ..config import CACHE_DIR
from .http import FetchError, get_text

PROFILE_URL = "https://investor.vanguard.com/vmf/api/{ticker}/profile"
PRICE_URL = "https://investor.vanguard.com/vmf/api/{ticker}/price"
_TTL = timedelta(hours=12)


def _cached_json(url: str, path: Path, *, use_cache: bool) -> Any:
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < _TTL:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    text = get_text(url, timeout=45.0, headers={"Accept": "application/json"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return json.loads(text)


def fetch_fund_facts(ticker: str, *, use_cache: bool = True) -> dict:
    """Profile and price facts for one Vanguard ETF.

    Raises FetchError(not_found=True) for a ticker Vanguard does not serve, so
    a caller probing a mixed universe can skip it cheaply.
    """
    ticker = ticker.upper()
    base = CACHE_DIR / "vanguard"
    profile = _cached_json(
        PROFILE_URL.format(ticker=ticker), base / f"profile-{ticker}.json", use_cache=use_cache
    )
    fund = (profile or {}).get("fundProfile") or {}
    # Vanguard is a brokerage as well as an issuer, so this endpoint answers
    # for funds it merely carries: QQQ comes back as "Invesco QQQ Trust" with
    # isExternalFund set and no premium. Only an internal fund is Vanguard
    # publishing about its own product, and only that is usable as a source.
    if not fund.get("ticker") or not fund.get("isInternalFund"):
        raise FetchError(f"{ticker}: not a Vanguard-issued fund", not_found=True)

    price = _cached_json(
        PRICE_URL.format(ticker=ticker), base / f"price-{ticker}.json", use_cache=use_cache
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
