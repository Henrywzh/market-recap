"""Point forecasts, market distributions and nowcasts for one scheduled release.

A number is attached only when it is about that release. Nasdaq lists a US
print on the next calendar day's page. Kalshi's next open contract is often
a later quarter or the monthly change rather than the yearly one; those stay
off the event. Cleveland's nowcast is kept only for the month the release
covers. Anything a source did not say is absent, not zero.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import re

MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_YOY = re.compile(r"yoy|y/y|year[- ]over[- ]year", re.I)
_QUARTER = re.compile(
    r"(?:q([1-4])|([1-4])(?:st|nd|rd|th)|first|second|third|fourth)", re.I,
)
_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}

# How each question is asked of each source. The release config names the
# questions; the patterns are the sources' own titles.
CATALOG = {
    "claims": {
        "label": "Claims", "unit": "k", "decimals": 0,
        "tv": r"^initial jobless claims$", "ff": r"^unemployment claims$",
        "kalshi": {"series": "KXJOBLESSCLAIMS", "scale": 0.001},
    },
    "durables": {
        "label": "Orders m/m", "unit": "%", "decimals": 1,
        "tv": r"^durable goods orders mom$", "ff": r"^durable goods orders m/m$",
    },
    "nfp": {
        "label": "Payrolls", "unit": "k", "decimals": 0,
        "tv": r"^non farm payrolls$", "ff": r"^non-farm employment change$",
        "kalshi": {"series": "KXPAYROLLS", "scale": 0.001},
    },
    "unrate": {
        "label": "Unemployment", "unit": "%", "decimals": 1,
        "tv": r"^unemployment rate$", "ff": r"^unemployment rate$",
        "kalshi": {"series": "KXU3"},
    },
    "cpi_yoy": {
        "label": "CPI y/y", "unit": "%", "decimals": 2,
        "tv": r"^inflation rate yoy$", "ff": r"^cpi y/y$",
        "kalshi": {"series": "KXCPIYOY", "yoy": True}, "cleveland": "cpi_yoy",
    },
    "cpi_mom": {
        "label": "CPI m/m", "unit": "%", "decimals": 2,
        "tv": r"^inflation rate mom$", "ff": r"^cpi m/m$",
        "kalshi": {"series": "KXCPI", "yoy": False}, "cleveland": "cpi_mom",
    },
    "core_cpi_yoy": {
        "label": "Core CPI y/y", "unit": "%", "decimals": 2,
        "tv": r"^core inflation rate yoy$", "ff": r"^core cpi y/y$",
        "kalshi": {"series": "KXCPICOREYOY", "yoy": True}, "cleveland": "core_cpi_yoy",
    },
    "core_cpi_mom": {
        "label": "Core CPI m/m", "unit": "%", "decimals": 2,
        "tv": r"^core inflation rate mom$",
        "kalshi": {"series": "KXCPICORE", "yoy": False}, "cleveland": "core_cpi_mom",
    },
    "pce_yoy": {
        "label": "PCE y/y", "unit": "%", "decimals": 2, "cleveland": "pce_yoy",
    },
    "core_pce_yoy": {
        "label": "Core PCE y/y", "unit": "%", "decimals": 2,
        "tv": r"^core pce price index yoy$", "ff": r"^core pce price index y/y$",
        "cleveland": "core_pce_yoy",
    },
    "core_pce_mom": {
        "label": "Core PCE m/m", "unit": "%", "decimals": 2,
        "kalshi": {"series": "KXPCECORE", "yoy": False}, "cleveland": "core_pce_mom",
    },
    "gdp": {
        "label": "Real GDP q/q", "unit": "%", "decimals": 1,
        "tv": r"^gdp growth rate qoq", "ff": r"gdp q/q$",
        "kalshi": {"series": "KXGDP", "quarter": True},
    },
    "fomc": {
        "label": "P(hike)", "unit": "p", "decimals": 1,
        "kalshi": {"series": "KXFEDDECISION", "hike": True}, "polymarket": True,
    },
}

NASDAQ_EXACT = {
    "initial jobless claims": "claims", "durable goods orders": "durables",
    "nonfarm payrolls": "nfp", "unemployment rate": "unrate", "gdp": "gdp",
}
NASDAQ_PAIRS = {
    "cpi": ("cpi_mom", "cpi_yoy"),
    "core cpi": ("core_cpi_mom", "core_cpi_yoy"),
    "core pce price index": ("core_pce_mom", "core_pce_yoy"),
}
SOURCE_LABEL = {
    "tradingview": "TradingView", "nasdaq": "Nasdaq", "forexfactory": "ForexFactory",
    "kalshi": "Kalshi", "polymarket": "Polymarket", "cleveland": "Cleveland",
}
SURVEY_SOURCES = ("tradingview", "nasdaq", "forexfactory")


def actuals_for(event: dict, keys: list[str], book: dict) -> list[dict]:
    """Released values for this event, each with the survey point it beat or missed."""
    out = []
    for key in keys:
        spec = CATALOG.get(key)
        actual = (book.get("actuals") or {}).get(("tradingview", event["date"], key))
        if spec is None or not actual or actual.get("value") is None:
            continue
        forecast = (book["points"].get(("tradingview", event["date"], key)) or {}).get("value")
        row = _reading("actual", "tradingview", spec, actual["value"])
        row["forecast"] = forecast
        row["surprise"] = round(actual["value"] - forecast, 4) if forecast is not None else None
        out.append(row)
    return out


def empty_book() -> dict:
    return {"points": {}, "actuals": {}, "markets": {}, "models": {}, "polymarket": []}


def num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.lower() in {"&nbsp;", "n/a", "-"}:
        return None
    if text.endswith(("K", "k")):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def cleveland_period(reference: str | None) -> str | None:
    """'September 2026' to the '2026-9' caption Cleveland uses. Quarters do not map."""
    if not reference:
        return None
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        reference, re.I,
    )
    if not match:
        return None
    return f"{match.group(2)}-{MONTHS.index(match.group(1).lower()) + 1}"


def quarter_number(reference: str | None) -> str | None:
    if not reference:
        return None
    match = _QUARTER.search(reference)
    if not match:
        return None
    if match.group(1) or match.group(2):
        return match.group(1) or match.group(2)
    return _QUARTER_WORD[match.group(0).lower()]


def nasdaq_release_day(query_day: date) -> date:
    """The US release date. Nasdaq's date parameter is the day after."""
    return query_day - timedelta(days=1)


def _row_scale(row: dict) -> float | None:
    for field in ("previous", "consensus", "forecast"):
        value = num(row.get(field))
        if value is not None:
            return abs(value)
    return None


def split_inflation(rows: list[dict]) -> dict[str, dict]:
    """Two rows, one name. The yearly print is at least twice the monthly one."""
    scaled = []
    for row in rows:
        scale = _row_scale(row)
        if scale is not None:
            scaled.append((scale, row))
    if len(scaled) != 2:
        return {}
    scaled.sort(key=lambda item: item[0])
    small, large = scaled
    if large[0] < small[0] * 2:
        return {}
    return {"mom": small[1], "yoy": large[1]}


def nasdaq_points(query_day: date, rows: list[dict]) -> dict[tuple[str, str], dict]:
    release = nasdaq_release_day(query_day).isoformat()
    found: dict[str, float] = {}
    grouped: dict[str, list] = {}
    for row in rows:
        if row.get("country") != "United States":
            continue
        name = (row.get("eventName") or "").strip().casefold()
        exact = NASDAQ_EXACT.get(name)
        if exact:
            value = num(row.get("consensus"))
            if value is not None:
                found[exact] = value
            continue
        if name in NASDAQ_PAIRS:
            grouped.setdefault(name, []).append(row)
    for name, group in grouped.items():
        mom_key, yoy_key = NASDAQ_PAIRS[name]
        split = split_inflation(group)
        for side, key in (("mom", mom_key), ("yoy", yoy_key)):
            value = num((split.get(side) or {}).get("consensus"))
            if value is not None:
                found[key] = value
    return {(release, key): {"value": value} for key, value in found.items()}


def _titled_points(rows: list[dict], *, date_field: str, title_field: str, value_field: str,
                   pattern_field: str, country: str | None = None, country_field: str = "country") -> dict:
    out = {}
    for row in rows:
        if country is not None and row.get(country_field) != country:
            continue
        day = str(row.get(date_field) or "")[:10]
        if len(day) != 10:
            continue
        title = row.get(title_field) or ""
        value = num(row.get(value_field))
        if value is None:
            continue
        for key, spec in CATALOG.items():
            pattern = spec.get(pattern_field)
            if pattern and re.search(pattern, title, re.I):
                out.setdefault((day, key), {"value": value})
                break
    return out


def tradingview_points(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return _titled_points(rows, date_field="date", title_field="title", value_field="forecast", pattern_field="tv")


def tradingview_actuals(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """What TradingView printed as the actual once a release is out.

    Third-party and fast: the agency's own figure (and FRED's copy of it) can
    arrive later and can differ; the page says which this is.
    """
    return _titled_points(rows, date_field="date", title_field="title", value_field="actual", pattern_field="tv")


def forexfactory_points(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return _titled_points(
        rows, date_field="date", title_field="title", value_field="forecast",
        pattern_field="ff", country="USD",
    )


def _strike(subtitle: str) -> float | None:
    match = re.search(r"(?:above|at least)\s+([-\d.,]+)", subtitle or "", re.I)
    return num(match.group(1)) if match else None


def _probability(market: dict) -> tuple[float | None, float | None]:
    bid, ask = num(market.get("yes_bid_dollars")), num(market.get("yes_ask_dollars"))
    spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
    if spread is not None and spread <= 0.10 and ask and ask > 0:
        return (bid + ask) / 2, spread
    return num(market.get("last_price_dollars")), spread


def _quantiles(ladder: list[tuple[float, float]]) -> dict[str, float | None]:
    ordered = sorted(ladder)
    out: dict[str, float | None] = {}
    for name, level in (("low", 0.9), ("value", 0.5), ("high", 0.1)):
        value = None
        for (left, p_left), (right, p_right) in zip(ordered, ordered[1:]):
            if p_left >= level >= p_right and p_left != p_right:
                value = left + (p_left - level) / (p_left - p_right) * (right - left)
                break
        out[name] = round(value, 3) if value is not None else None
    return out


def kalshi_close(event: dict) -> str | None:
    markets = event.get("markets") or []
    if not markets:
        return None
    return min(str(market["close_time"])[:10] for market in markets)


def kalshi_quote(event: dict, spec: dict) -> dict | None:
    markets = event.get("markets") or []
    interest = round(sum(num(market.get("open_interest_fp")) or 0 for market in markets))
    if spec.get("hike"):
        total, seen = 0.0, False
        for market in markets:
            probability, _spread = _probability(market)
            label = market.get("yes_sub_title") or ""
            if probability is not None and re.search(r"hike|increase", label, re.I):
                total += probability
                seen = True
        if not seen:
            return None
        return {"value": round(total, 3), "title": event.get("title"), "open_interest": interest}
    ladder = []
    for market in markets:
        strike = _strike(market.get("yes_sub_title") or "")
        probability, spread = _probability(market)
        if strike is not None and probability is not None:
            ladder.append((strike, probability, spread))
    if len(ladder) < 2:
        return None
    quantiles = _quantiles([(strike, probability) for strike, probability, _spread in ladder])
    if quantiles["value"] is None:
        return None
    nearest = min(ladder, key=lambda item: abs(item[0] - quantiles["value"]))
    scale = spec.get("scale", 1.0)

    def scaled(value):
        return round(value * scale, 3) if value is not None else None

    quote = {
        "value": scaled(quantiles["value"]), "low": scaled(quantiles["low"]), "high": scaled(quantiles["high"]),
        "title": event.get("title"), "open_interest": interest,
    }
    if nearest[2] is not None:
        quote["spread"] = round(nearest[2], 4)
    return quote


def kalshi_fits(event: dict, spec: dict, release: str, reference: str | None = None) -> bool:
    """True when the contract closes on this release and is this print."""
    if kalshi_close(event) != release:
        return False
    title = event.get("title") or ""
    yoy = spec.get("yoy")
    if yoy is True and _YOY.search(title) is None:
        return False
    if yoy is False and _YOY.search(title) is not None:
        return False
    if spec.get("quarter"):
        quarter = quarter_number(reference)
        if quarter is None or re.search(rf"q{quarter}", title, re.I) is None:
            return False
    return True


def index_kalshi(events: list[dict], key: str) -> dict[tuple[str, str, str], dict]:
    spec = CATALOG[key]["kalshi"]
    loose = {name: value for name, value in spec.items() if name != "quarter"}
    out = {}
    for event in events:
        release = kalshi_close(event)
        if release is None or not kalshi_fits(event, loose, release):
            continue
        quote = kalshi_quote(event, spec)
        if quote is not None:
            out.setdefault(("kalshi", release, key), quote)
    return out


def cleveland_models(charts: list[dict], basis: str) -> dict[tuple[str, str], dict]:
    """basis is yoy or mom. The 'Actual' series in the same file is not the nowcast."""
    names = {
        "CPI Inflation": f"cpi_{basis}", "Core CPI Inflation": f"core_cpi_{basis}",
        "PCE Inflation": f"pce_{basis}", "Core PCE Inflation": f"core_pce_{basis}",
    }
    out = {}
    for chart in charts:
        period = (chart.get("chart") or {}).get("subcaption")
        if not period:
            continue
        for series in chart.get("dataset") or []:
            model_key = names.get(series.get("seriesname"))
            if not model_key:
                continue
            values = [value for value in (num(point.get("value")) for point in series.get("data") or []) if value is not None]
            if values:
                out[(period, model_key)] = {"value": values[-1]}
    return out


def polymarket_hike(event: dict) -> float | None:
    total, seen = 0.0, False
    for market in event.get("markets") or []:
        raw = market.get("outcomePrices")
        try:
            prices = raw if isinstance(raw, list) else json.loads(raw or "[]")
            yes = float(prices[0]) if prices else None
        except (TypeError, ValueError, IndexError):
            yes = None
        if yes is not None and re.search(r"increase|hike", market.get("question") or "", re.I):
            total += yes
            seen = True
    return round(total, 3) if seen else None


def pick_polymarket(release: str, events: list[dict]) -> dict | None:
    """The Fed decision in this meeting's month, preferring the contract that ends that day."""
    when = date.fromisoformat(release)
    month = MONTHS[when.month - 1]
    candidates = []
    for event in events:
        title = event.get("title") or ""
        folded = title.lower()
        if "fed decision" not in folded or month not in folded:
            continue
        end = str(event.get("endDate") or event.get("end") or "")[:10]
        if str(when.year) not in title and not end.startswith(str(when.year)):
            continue
        value = polymarket_hike(event)
        if value is None:
            continue
        candidates.append({"value": value, "title": title, "end": end})
    exact = [item for item in candidates if item["end"] == release]
    return (exact or candidates or [None])[0]


def _reading(kind: str, source: str, spec: dict, value: float, extra: dict | None = None) -> dict:
    row = {
        "kind": kind, "source": source, "source_label": SOURCE_LABEL[source],
        "label": spec["label"], "value": round(float(value), 4), "unit": spec["unit"], "decimals": spec["decimals"],
    }
    for field in ("low", "high", "open_interest", "spread"):
        if extra and extra.get(field) is not None:
            row[field] = extra[field]
    return row


def expectations_for(event: dict, keys: list[str], book: dict) -> list[dict]:
    """Forecasts that are about this event. Empty when none are."""
    rows = []
    period = cleveland_period(event.get("reference_period"))
    for key in keys:
        spec = CATALOG.get(key)
        if spec is None:
            continue
        for source in SURVEY_SOURCES:
            point = book["points"].get((source, event["date"], key))
            if point and point.get("value") is not None:
                rows.append(_reading("survey", source, spec, point["value"]))
        quote = book["markets"].get(("kalshi", event["date"], key))
        kalshi = spec.get("kalshi") or {}
        if quote and quote.get("value") is not None and kalshi_fits(
                {"title": quote.get("title"), "markets": [{"close_time": event["date"]}]},
                kalshi, event["date"], event.get("reference_period")):
            rows.append(_reading("market", "kalshi", spec, quote["value"], quote))
        if spec.get("polymarket"):
            picked = pick_polymarket(event["date"], book.get("polymarket") or [])
            if picked and picked.get("value") is not None:
                rows.append(_reading("market", "polymarket", spec, picked["value"]))
        model_key = spec.get("cleveland")
        model = book["models"].get((period, model_key)) if period and model_key else None
        if model and model.get("value") is not None:
            rows.append(_reading("model", "cleveland", spec, model["value"]))
    return rows
