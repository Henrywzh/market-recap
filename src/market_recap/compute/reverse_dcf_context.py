"""Dated revenue expectations for context, never long-horizon DCF defaults."""
from datetime import date, datetime, timezone
import math
from zoneinfo import ZoneInfo

from ..config import MARKET_TIMEZONE


def _number(value):
    return float(value) if not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) else None


def revenue_context(trend: dict | None, observed_at: str | None) -> dict | None:
    """Keep Yahoo FY revenue estimates, dates and dispersion, not EPS proxies.

    Observation time is the local cache fetch time, not a publisher revision
    timestamp. Growth uses the same vendor's prior-year revenue denominator;
    it is not a ratio of unverified Yahoo/SEC reporting currencies.
    """
    if not trend or not isinstance(observed_at, str) or not observed_at:
        return None
    try:
        stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
    except (ValueError, TypeError):
        return None
    periods = []
    for key in ("0y", "+1y"):
        source = trend.get(key) or {}
        try:
            end = date.fromisoformat(source.get("end", "")).isoformat()
        except (ValueError, TypeError):
            continue
        avg = _number(source.get("revenue"))
        if avg is None or avg < 0:
            continue
        base = _number(source.get("revenue_year_ago"))
        base = base if base is not None and base > 0 else None
        low, high = (_number(source.get(k)) for k in ("revenue_low", "revenue_high"))
        range_issue = None
        if (low is not None and (low < 0 or low > avg)) or (high is not None and high < avg):
            low, high = None, None
            range_issue = "Vendor range does not bracket its mean; range withheld."
        analysts = _number(source.get("revenue_analysts"))
        analysts = int(analysts) if analysts is not None and analysts >= 0 and analysts.is_integer() else None
        growth = lambda amount: (amount / base - 1) * 100 if amount is not None and base else None
        periods.append({"period": key, "end": end, "revenue": avg, "low": low, "high": high,
                        "year_ago_revenue": base, "growth_pct": growth(avg),
                        "growth_low_pct": growth(low), "growth_high_pct": growth(high),
                        "analysts": analysts, "range_issue": range_issue})
    if not periods:
        return None
    return {"source": "Yahoo earningsTrend (unofficial)",
            "observed_at": stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "observed_market_date": stamp.astimezone(ZoneInfo(MARKET_TIMEZONE)).date().isoformat(),
            "periods": periods,
            "note": "FY estimates, not a long-run forecast. Low/high are analyst dispersion, not confidence bounds. Reporting currency is not supplied; growth uses the vendor's own denominator."}
