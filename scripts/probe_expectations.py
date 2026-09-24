"""Probe the free sources of US macro expectations.

Research tooling, not part of the build. For each candidate source it records
whether it answered (and how fast, over several rounds), how fresh its data
is, what it says about a fixed set of upcoming releases, how far ahead it
carries an expectation at all, and -- where it quotes a "previous" print --
whether that print matches the official series on FRED.

    python scripts/probe_expectations.py [--rounds 3] [--out data/probes]

Each run writes one JSON file; `--summarize DIR` aggregates many runs (the
scheduled probe workflow) into success rates and latency percentiles.

Needs httpx, pandas, openpyxl and yfinance >= 1.7 (for Yahoo's economic
calendar), which is newer than the version the build pins, so it runs in its
own environment.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Callable

import httpx
import pandas as pd

UA = "market-recap/0.1 (source evaluation)"
TIMEOUT = 60.0

# The releases every source is asked about: near ones (which a point-consensus
# calendar should already carry) and far ones (which only a market carries).
TARGETS = {
    "claims": ("Initial jobless claims (k)", "2026-09-24"),
    "durables": ("Durable goods orders m/m, Aug (%)", "2026-09-25"),
    "core_pce_yoy": ("Core PCE y/y, Aug (%)", "2026-09-30"),
    "gdp_final": ("Real GDP q/q saar, Q2 final (%)", "2026-09-30"),
    "nfp": ("Nonfarm payrolls, Sep (k)", "2026-10-02"),
    "unrate": ("Unemployment rate, Sep (%)", "2026-10-02"),
    "cpi_mom": ("CPI m/m, Sep (%)", "2026-10-14"),
    "cpi_yoy": ("CPI y/y, Sep (%)", "2026-10-14"),
    "core_cpi_yoy": ("Core CPI y/y, Sep (%)", "2026-10-14"),
    "fomc_hike": ("FOMC Oct 28: P(hike)", "2026-10-28"),
}


class Probe:
    """One source: a function returning (content, meta), timed and retried."""

    def __init__(self, name: str, category: str, fn: Callable, *, auth: str, terms: str, history: str, rounds: int | None = None):
        self.name, self.category, self.fn = name, category, fn
        self.auth, self.terms, self.history, self.rounds = auth, terms, history, rounds


def _get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    return response


def _num(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(",", "").replace("%", "")
    mult = 1.0
    if s.endswith("K"):
        s, mult = s[:-1], 1.0
    elif s.endswith("M"):
        s, mult = s[:-1], 1000.0
    try:
        return float(s) * mult
    except ValueError:
        return None


def _match(title: str, patterns: dict[str, str]) -> str | None:
    for key, pattern in patterns.items():
        if re.search(pattern, title, re.I):
            return key
    return None


def _lead_buckets(rows: list[tuple[date, bool]], today: date) -> dict:
    """Share of events carrying an expectation, by days until release."""
    buckets = {"0-2d": [], "3-7d": [], "8-14d": [], "15-30d": []}
    for day, has in rows:
        ahead = (day - today).days
        key = "0-2d" if ahead <= 2 else "3-7d" if ahead <= 7 else "8-14d" if ahead <= 14 else "15-30d" if ahead <= 30 else None
        if key:
            buckets[key].append(has)
    return {k: (f"{sum(v)}/{len(v)}" if v else "-") for k, v in buckets.items()}


# --- Market-implied ---------------------------------------------------------------

KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
KALSHI_SERIES = {
    "cpi_yoy": ["KXCPIYOY"], "cpi_mom": ["KXCPI"], "core_cpi_yoy": ["KXCPICOREYOY", "KXECONSTATCORECPIYOY"],
    "nfp": ["KXPAYROLLS", "KXUSNFP"], "unrate": ["KXU3"], "core_pce_yoy": ["KXPCECORE", "KXCOREPCE"],
    "gdp_final": ["KXGDP"], "claims": ["KXJOBLESSCLAIMS", "KXCLAIMS"], "fomc_hike": ["KXFEDDECISION"],
}


def _kalshi_probability(market: dict) -> float | None:
    bid, ask = _num(market.get("yes_bid_dollars")), _num(market.get("yes_ask_dollars"))
    if bid is not None and ask is not None and ask > 0 and ask - bid <= 0.10:
        return (bid + ask) / 2
    return _num(market.get("last_price_dollars"))


def _ladder_quantiles(ladder: list[tuple[float, float]]) -> dict:
    """From P(value > x) at each x, the values where it crosses 0.9, 0.5, 0.1."""
    ladder = sorted(ladder)
    out = {}
    for name, level in (("p10", 0.9), ("median", 0.5), ("p90", 0.1)):
        value = None
        for (x0, p0), (x1, p1) in zip(ladder, ladder[1:]):
            if p0 >= level >= p1 and p0 != p1:
                value = x0 + (p0 - level) / (p0 - p1) * (x1 - x0)
                break
        out[name] = round(value, 3) if value is not None else None
    return out


def kalshi(client: httpx.Client, today: date):
    content, freshest, liquidity = {}, None, {}
    for target, series_list in KALSHI_SERIES.items():
        release = TARGETS[target][1]
        for series in series_list:
            data = _get(client, KALSHI_URL, params={"series_ticker": series, "status": "open", "with_nested_markets": "true"}).json()
            events = [e for e in data.get("events") or [] if e.get("markets")]
            # The event settling on the target release: the earliest closing on or after it.
            events = [e for e in events if min(m["close_time"][:10] for m in e["markets"]) >= release] or []
            if not events:
                continue
            event = min(events, key=lambda e: min(m["close_time"] for m in e["markets"]))
            markets = event["markets"]
            freshest = max([freshest or ""] + [m.get("updated_time") or "" for m in markets])
            oi = sum(_num(m.get("open_interest_fp")) or 0 for m in markets)
            if target == "fomc_hike":
                probs = {m.get("yes_sub_title"): _kalshi_probability(m) for m in markets}
                hike = sum(p or 0 for k, p in probs.items() if k and "hike" in k.lower())
                content[target] = {"value": round(hike, 3), "detail": {k: v for k, v in probs.items()}, "series": series,
                                   "event": event.get("title"), "open_interest": round(oi)}
            else:
                ladder = []
                for m in markets:
                    match = re.search(r"above\s+([-\d.,]+)", m.get("yes_sub_title") or "", re.I)
                    p = _kalshi_probability(m)
                    if match and p is not None:
                        ladder.append((_num(match.group(1)), p))
                q = _ladder_quantiles(ladder)
                scale = 0.001 if target == "nfp" else 1.0
                content[target] = {"value": q["median"] * scale if q["median"] is not None else None,
                                   "p10": q["p10"] * scale if q["p10"] is not None else None,
                                   "p90": q["p90"] * scale if q["p90"] is not None else None,
                                   "series": series, "event": event.get("title"), "strikes": len(ladder),
                                   "open_interest": round(oi)}
            liquidity[target] = round(oi)
            break
    return content, {"source_asof": freshest, "depth": "full probability ladder", "open_interest": liquidity}


POLY_URL = "https://gamma-api.polymarket.com/events"


def polymarket(client: httpx.Client, today: date):
    content, freshest, found = {}, None, []
    for tag in ("fed-rates", "fed", "economy", "inflation"):
        events = _get(client, POLY_URL, params={"closed": "false", "limit": 100, "tag_slug": tag}).json()
        for event in events:
            title = event.get("title") or ""
            found.append(title)
            freshest = max(freshest or "", event.get("updatedAt") or "")
            if re.search(r"fed decision.*october", title, re.I) and "fomc_hike" not in content:
                hike = 0.0
                detail = {}
                for m in event.get("markets") or []:
                    prices = json.loads(m.get("outcomePrices") or "[]")
                    yes = float(prices[0]) if prices else None
                    detail[m.get("groupItemTitle") or m.get("question")] = yes
                    if yes is not None and re.search(r"increase|hike", m.get("question") or "", re.I):
                        hike += yes
                content["fomc_hike"] = {"value": round(hike, 3), "detail": detail, "event": title,
                                        "volume": round(float(event.get("volume") or 0))}
            if re.search(r"\bcpi\b|inflation", title, re.I) and re.search(r"september", title, re.I) and "cpi_yoy" not in content:
                content.setdefault("_cpi_markets", []).append(title)
    return content, {"source_asof": freshest, "depth": "binary markets per outcome",
                     "macro_events_seen": len(set(found))}


def fed_funds_futures(client: httpx.Client, today: date):
    import yfinance as yf
    # November's contract averages the whole month after the Oct 28 meeting.
    history = yf.Ticker("ZQX26.CBT").history(period="5d")["Close"].dropna()
    effr = _fred_series(client, "DFF")
    effr_rate = float(effr.iloc[-1])
    implied = 100 - float(history.iloc[-1])
    p_hike = (implied - effr_rate) / 0.25
    return ({"fomc_hike": {"value": round(p_hike, 3), "detail": {"nov_contract_implied": round(implied, 4), "effr": effr_rate,
                                                                 "effr_date": str(effr.index[-1].date())}}},
            {"source_asof": str(history.index[-1].date()), "depth": "one implied rate per contract month (delayed quotes)"})


FRED_EXPECTATIONS = {"T5YIE": "5y breakeven", "T10YIE": "10y breakeven", "MICH": "UMich 1y expected inflation",
                     "EXPINF1YR": "Cleveland Fed 1y expected inflation (model)", "GDPNOW": "Atlanta Fed GDPNow"}
FRED_OFFICIAL = {  # target -> (series, transform) used to check sources' "previous" prints
    "claims": ("ICSA", "level_k"), "durables": ("DGORDER", "mom"), "core_pce_yoy": ("PCEPILFE", "yoy"),
    "gdp_final": ("A191RL1Q225SBEA", "level"), "nfp": ("PAYEMS", "change"), "unrate": ("UNRATE", "level"),
    "cpi_mom": ("CPIAUCSL", "mom"), "cpi_yoy": ("CPIAUCNS", "yoy"), "core_cpi_yoy": ("CPILFENS", "yoy"),
}


def _fred_text(series: str) -> str:
    """FRED's edge stalls Python's TLS handshake but answers curl at once (the
    build routes it through curl for the same reason), and it holds open any
    request whose User-Agent carries no contact address -- measured: 15 s
    timeouts without one, under 2 s with the project's."""
    import subprocess
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from market_recap.config import USER_AGENT as CONTACT_UA
    out = subprocess.run(["curl", "-sS", "--http1.1", "--fail", "--max-time", "30", "--retry", "1", "-A", CONTACT_UA,
                          f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"FRED {series}: {out.stderr.strip()[:120]}")
    return out.stdout


def _fred_series(client: httpx.Client, series: str) -> pd.Series:
    frame = pd.read_csv(io.StringIO(_fred_text(series)))
    s = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(frame.iloc[:, 0])
    return s.dropna()


def fred(client: httpx.Client, today: date):
    content, meta = {}, {}
    for series, label in FRED_EXPECTATIONS.items():
        s = _fred_series(client, series)
        meta[series] = {"label": label, "latest": round(float(s.iloc[-1]), 3), "date": str(s.index[-1].date()),
                        "lag_days": (today - s.index[-1].date()).days}
    official = {}
    for target, (series, how) in FRED_OFFICIAL.items():
        s = _fred_series(client, series)
        v = {"level": s, "level_k": s / 1000, "mom": s.pct_change() * 100, "yoy": s.pct_change(12) * 100,
             "change": s.diff()}[how].dropna()
        official[target] = {"value": round(float(v.iloc[-1]), 3), "period": str(v.index[-1].date()), "series": series}
    content["gdp_nowcast_q3"] = {"value": meta["GDPNOW"]["latest"], "date": meta["GDPNOW"]["date"]}
    return content, {"source_asof": max(m["date"] for m in meta.values()), "depth": "one number per series",
                     "series": meta, "official_previous": official}


# --- Point consensus calendars --------------------------------------------------------

TV_PATTERNS = {"claims": r"^initial jobless claims$", "durables": r"^durable goods orders mom$",
               "core_pce_yoy": r"^core pce price index yoy$", "gdp_final": r"^gdp growth rate qoq final$",
               "nfp": r"^non farm payrolls$", "unrate": r"^unemployment rate$", "cpi_mom": r"^inflation rate mom$",
               "cpi_yoy": r"^inflation rate yoy$", "core_cpi_yoy": r"^core inflation rate yoy$"}


def tradingview(client: httpx.Client, today: date):
    params = {"from": f"{today}T00:00:00.000Z", "to": f"{today + timedelta(days=30)}T23:59:59.000Z", "countries": "US"}
    rows = _get(client, "https://economic-calendar.tradingview.com/events", params=params,
                headers={"Origin": "https://www.tradingview.com"}).json().get("result", [])
    content, lead = {}, []
    for r in rows:
        day = date.fromisoformat(r["date"][:10])
        lead.append((day, r.get("forecast") is not None))
        key = _match(r.get("title") or "", TV_PATTERNS)
        if key and r["date"][:10] == TARGETS[key][1] and key not in content:
            content[key] = {"value": r.get("forecast"), "previous": r.get("previous"), "period": r.get("period")}
    return content, {"source_asof": None, "depth": "single forecast + previous", "events": len(rows),
                     "lead_coverage": _lead_buckets(lead, today)}


NASDAQ_PATTERNS = {"claims": r"^initial jobless claims$", "durables": r"^durable goods orders( \(mom\))?$",
                   "core_pce_yoy": r"^core pce price index \(yoy\)$", "gdp_final": r"^gdp \(qoq\)$",
                   "nfp": r"^nonfarm payrolls$", "unrate": r"^unemployment rate$", "cpi_mom": r"^cpi \(mom\)$",
                   "cpi_yoy": r"^cpi \(yoy\)$", "core_cpi_yoy": r"^core cpi \(yoy\)$"}


def nasdaq(client: httpx.Client, today: date):
    content, lead, names = {}, [], set()
    days = sorted({date.fromisoformat(d) for _, d in TARGETS.values()} | {today + timedelta(days=k) for k in (1, 3, 7, 14)})
    for day in days:
        data = _get(client, "https://api.nasdaq.com/api/calendar/economicevents", params={"date": str(day)},
                    headers={"Accept": "application/json", "User-Agent": "market-recap/0.1"}).json().get("data")
        if data is None:
            # Seen overnight: HTTP 200 with "data": null. Counted, not parsed.
            raise RuntimeError(f"HTTP 200 with no data for {day}")
        for r in data.get("rows") or []:
            if r.get("country") != "United States":
                continue
            name = (r.get("eventName") or "").strip()
            names.add(name)
            consensus = (r.get("consensus") or "").strip()
            lead.append((day, bool(consensus)))
            key = _match(name, NASDAQ_PATTERNS)
            if key and str(day) == TARGETS[key][1] and key not in content:
                content[key] = {"value": _num(consensus), "previous": _num(r.get("previous"))}
    return content, {"source_asof": None, "depth": "single consensus + previous", "lead_coverage": _lead_buckets(lead, today),
                     "_names": sorted(names)[:80]}


FF_PATTERNS = {"claims": r"^unemployment claims$", "durables": r"^durable goods orders m/m$",
               "core_pce_yoy": r"^core pce price index y/y$", "gdp_final": r"^final gdp q/q$",
               "nfp": r"^non-farm employment change$", "unrate": r"^unemployment rate$", "cpi_mom": r"^cpi m/m$",
               "cpi_yoy": r"^cpi y/y$", "core_cpi_yoy": r"^core cpi y/y$"}


def forexfactory(client: httpx.Client, today: date):
    content, lead, weeks = {}, [], {}
    for week in ("thisweek", "nextweek"):
        try:
            rows = _get(client, f"https://nfs.faireconomy.media/ff_calendar_{week}.json").json()
            weeks[week] = len(rows)
        except httpx.HTTPStatusError as exc:
            weeks[week] = f"HTTP {exc.response.status_code}"
            continue
        for r in rows:
            if r.get("country") != "USD":
                continue
            day = date.fromisoformat(r["date"][:10])
            lead.append((day, bool(r.get("forecast"))))
            key = _match(r.get("title") or "", FF_PATTERNS)
            if key and r["date"][:10] == TARGETS[key][1] and key not in content:
                content[key] = {"value": _num(r.get("forecast")), "previous": _num(r.get("previous"))}
    return content, {"source_asof": None, "depth": "single forecast + previous", "weeks": weeks,
                     "lead_coverage": _lead_buckets(lead, today)}


YAHOO_PATTERNS = {"claims": r"^initial jobless clm", "durables": r"^durable goods$", "core_pce_yoy": r"^core pce price index yy",
                  "gdp_final": r"^gdp final$", "nfp": r"^non-farm payrolls$", "unrate": r"^unemployment rate$",
                  "cpi_mom": r"^cpi mm, sa$", "cpi_yoy": r"^cpi yy, nsa$", "core_cpi_yoy": r"^core cpi yy, nsa$"}


def yahoo_calendar(client: httpx.Client, today: date):
    import yfinance as yf
    frame = yf.Calendars(start=str(today), end=str(today + timedelta(days=30))).get_economic_events_calendar(limit=500)
    frame = frame[frame["Region"] == "US"] if "Region" in frame else frame
    content, lead = {}, []
    for event, r in frame.iterrows():
        day = pd.Timestamp(r["Event Time"]).date()
        lead.append((day, pd.notna(r.get("Expected"))))
        key = _match(str(event), YAHOO_PATTERNS)
        if key and str(day) == TARGETS[key][1] and key not in content:
            content[key] = {"value": None if pd.isna(r.get("Expected")) else float(r["Expected"]),
                            "previous": None if pd.isna(r.get("Last")) else float(r["Last"])}
    return content, {"source_asof": None, "depth": "single expected + last", "events": len(frame),
                     "lead_coverage": _lead_buckets(lead, today)}


def finnhub(client: httpx.Client, today: date):
    sys.path.insert(0, str(Path.home() / "Desktop/Quant/alternative-data/src"))
    from event_consensus.credentials import resolve_credential  # the user's own resolver; the key is not printed
    key = resolve_credential("FINNHUB_API_KEY", Path.home() / "Desktop/Quant/alternative-data")
    if not key:
        raise RuntimeError("no FINNHUB_API_KEY configured")
    response = client.get("https://finnhub.io/api/v1/calendar/economic",
                          params={"from": str(today), "to": str(today + timedelta(days=30)), "token": key})
    if response.status_code in (401, 403):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:120]}")
    response.raise_for_status()
    rows = response.json().get("economicCalendar") or []
    us = [r for r in rows if r.get("country") == "US"]
    return {}, {"source_asof": None, "depth": "estimate + prev", "events": len(us),
                "sample": [{k: r.get(k) for k in ("event", "time", "estimate", "prev")} for r in us[:5]]}


# --- Official nowcasts and surveys -------------------------------------------------------

def cleveland_nowcast(client: httpx.Client, today: date):
    charts = _get(client, "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json",
                  timeout=120.0).json()
    names = {"CPI Inflation": "cpi_mom", "Core CPI Inflation": "core_cpi_mom", "PCE Inflation": "pce_mom",
             "Core PCE Inflation": "core_pce_mom"}
    content, asof = {}, None
    for chart in charts:
        period = chart.get("chart", {}).get("subcaption")
        asof = max(asof or "", (chart.get("chart", {}).get("_comment") or "")[:10])
        if period != "2026-9":
            continue
        for ds in chart.get("dataset", []):
            key = names.get(ds.get("seriesname"))
            vals = [d.get("value") for d in ds.get("data") or [] if str(d.get("value", "")).strip()]
            if key and vals:
                content[key if key != "cpi_mom" else "cpi_mom"] = {"value": float(vals[-1]), "period": period}
    year = _get(client, "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_year.json",
                timeout=120.0).json()
    for chart in year:
        if chart.get("chart", {}).get("subcaption") != "2026-9":
            continue
        for ds in chart.get("dataset", []):
            vals = [d.get("value") for d in ds.get("data") or [] if str(d.get("value", "")).strip()]
            if ds.get("seriesname") == "CPI Inflation" and vals:
                content["cpi_yoy"] = {"value": float(vals[-1]), "period": "2026-9"}
            if ds.get("seriesname") == "Core CPI Inflation" and vals:
                content["core_cpi_yoy"] = {"value": float(vals[-1]), "period": "2026-9"}
    return content, {"source_asof": asof, "depth": "model point nowcast, updated daily"}


def philly_spf(client: httpx.Client, today: date):
    raw = _get(client, "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
               "survey-of-professional-forecasters/historical-data/medianlevel.xlsx").content
    sheet = pd.read_excel(io.BytesIO(raw), sheet_name="CPI")
    last = sheet.dropna(subset=["CPI2"]).iloc[-1]
    return ({"_spf_cpi_next_quarters": {"value": [last.get(f"CPI{i}") for i in range(1, 7)]}},
            {"source_asof": f"{int(last['YEAR'])}Q{int(last['QUARTER'])}", "depth": "median + dispersion files; quarterly"})


CHALLENGE = re.compile(r"just a moment|cf-chl|challenge-platform|captcha-delivery|enable javascript and cookies", re.I)


def blocked(url: str):
    """A page fetched once: refused, a bot challenge, or real content."""
    def fn(client: httpx.Client, today: date):
        response = client.get(url)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:100]!r}")
        if CHALLENGE.search(response.text[:20000]):
            raise RuntimeError(f"HTTP {response.status_code} but a bot challenge page")
        return {}, {"source_asof": None, "depth": "HTML page",
                    "mentions_consensus": bool(re.search(r"consensus|forecast", response.text, re.I))}
    return fn


PROBES = [
    Probe("kalshi", "market-implied", kalshi, auth="none (public market data)", terms="API terms allow data use; attribute",
          history="yes: per-market price history + settled events"),
    Probe("polymarket", "market-implied", polymarket, auth="none", terms="public API", history="yes: CLOB price history"),
    Probe("fed_funds_futures", "market-implied", fed_funds_futures, auth="none (Yahoo, delayed)", terms="Yahoo personal use",
          history="yes: daily closes"),
    Probe("fred", "official", fred, auth="none (CSV export)", terms="public domain / source terms per series",
          history="yes, plus ALFRED vintages (needs key)"),
    Probe("cleveland_nowcast", "official nowcast", cleveland_nowcast, auth="none", terms="public",
          history="yes: each target's revision path", rounds=1),
    Probe("philly_spf", "official survey", philly_spf, auth="none", terms="public", history="yes since 1968", rounds=1),
    Probe("tradingview", "point consensus", tradingview, auth="none (Origin header)", terms="unofficial widget endpoint",
          history="no: current window only"),
    Probe("nasdaq_econ", "point consensus", nasdaq, auth="none", terms="unofficial endpoint", history="past dates return actuals"),
    Probe("forexfactory", "point consensus", forexfactory, auth="none", terms="published JSON feed; this/next week only",
          history="no"),
    Probe("yahoo_calendar", "point consensus", yahoo_calendar, auth="none (yfinance >= 1.7)", terms="Yahoo personal use",
          history="past dates return actuals"),
    Probe("finnhub", "point consensus", finnhub, auth="API key", terms="free tier limits", history="-", rounds=1),
    Probe("econoday", "point consensus", blocked("https://us.econoday.com/byweek.asp?cust=us"), auth="none",
          terms="HTML; consensus ranges on detail pages; ToS restricts scraping", history="-", rounds=1),
    Probe("investing_com", "point consensus", blocked("https://www.investing.com/economic-calendar/"), auth="-",
          terms="bot protection; ToS forbids scraping", history="-", rounds=1),
    Probe("marketwatch", "point consensus", blocked("https://www.marketwatch.com/economy-politics/calendar"), auth="-",
          terms="captcha wall", history="-", rounds=1),
    Probe("cme_fedwatch", "market-implied", blocked("https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"),
          auth="-", terms="blocks scripts; ToS forbids scraping", history="-", rounds=1),
]


def run(rounds: int, only: set[str] | None) -> dict:
    today = datetime.now(timezone.utc).date()
    results = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "today": str(today),
               "targets": TARGETS, "sources": {}}
    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True) as client:
        for probe in PROBES:
            if only and probe.name not in only:
                continue
            attempts, content, meta = [], {}, {}
            for _ in range(probe.rounds or rounds):
                start = time.monotonic()
                try:
                    content, meta = probe.fn(client, today)
                    attempts.append({"ok": True, "seconds": round(time.monotonic() - start, 2)})
                except Exception as exc:
                    attempts.append({"ok": False, "seconds": round(time.monotonic() - start, 2),
                                     "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            results["sources"][probe.name] = {
                "category": probe.category, "auth": probe.auth, "terms": probe.terms, "history": probe.history,
                "attempts": attempts, "content": content, "meta": meta,
            }
            ok = sum(a["ok"] for a in attempts)
            print(f"{probe.name:<18} {ok}/{len(attempts)} ok  median {statistics.median(a['seconds'] for a in attempts):6.2f}s  "
                  f"{attempts[-1].get('error', '')[:70]}", file=sys.stderr)
    return results


def summarize(directory: Path) -> None:
    runs = [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]
    rows = {}
    for r in runs:
        for name, s in r["sources"].items():
            rows.setdefault(name, []).extend(s["attempts"])
    print(f"{len(runs)} runs")
    for name, attempts in rows.items():
        secs = sorted(a["seconds"] for a in attempts if a["ok"])
        p95 = secs[int(0.95 * (len(secs) - 1))] if secs else None
        print(f"{name:<18} {sum(a['ok'] for a in attempts)}/{len(attempts)}  median {statistics.median(secs) if secs else '-'}  p95 {p95}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--out", default="data/probes")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--skip", nargs="*", default=[])
    parser.add_argument("--summarize")
    args = parser.parse_args()
    if args.summarize:
        summarize(Path(args.summarize))
        return
    names = set(args.only) if args.only else {p.name for p in PROBES}
    results = run(args.rounds, names - set(args.skip))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"expectations-{results['run_at'].replace(':', '')}.json"
    path.write_text(json.dumps(results, indent=1, default=str))
    print(path)


if __name__ == "__main__":
    main()
