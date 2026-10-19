"""US Treasury daily par yield curve rates -- the official published curve.

"Latest published" is deliberately not "today". Treasury usually posts the
same day but sometimes not until the evening ET, so a refresh run shortly
after the close can legitimately show the prior business day. The artifact
carries the published date so the page can say which one it is showing
instead of implying the curve is stale or broken.

Each year's XML is cached: this year's as a daily file (refetched after the
18:30 rollover, when the day's curve has posted), last year's for a week,
older years for good. Four panels read the curve; uncached, each fetch took
about 20 s a year and a build spent some 150 s downloading the same two files.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from lxml import etree

from .http import get_bytes
from .. import cache
from ..config import REPO_ROOT
from ..util import write_json

XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

# Treasury's element names -> the tenors the curve panel plots, in order.
TENORS = [
    ("BC_1MONTH", "1M", 1),
    ("BC_2MONTH", "2M", 2),
    ("BC_3MONTH", "3M", 3),
    ("BC_4MONTH", "4M", 4),
    ("BC_6MONTH", "6M", 6),
    ("BC_1YEAR", "1Y", 12),
    ("BC_2YEAR", "2Y", 24),
    ("BC_3YEAR", "3Y", 36),
    ("BC_5YEAR", "5Y", 60),
    ("BC_7YEAR", "7Y", 84),
    ("BC_10YEAR", "10Y", 120),
    ("BC_20YEAR", "20Y", 240),
    ("BC_30YEAR", "30Y", 360),
]
_D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"


NAMESPACE = "treasury/par"


def _year_xml(year: int, today: date) -> bytes:
    kind = "daily_file" if year >= today.year else ("reference_data" if year == today.year - 1 else "archive")
    return cache.fetch_bytes(NAMESPACE, f"par-{year}", lambda: get_bytes(XML_URL.format(year=year), timeout=90.0),
                             kind=kind, suffix=".xml", compress=True)


def fetch_par_yield_curve(years: list[int] | None = None) -> tuple[pd.DataFrame, str]:
    """Tidy (date, tenor, tenor_months, yield_pct) across the requested years."""
    today = date.today()
    frame, url = _curve(tuple(years or [today.year - 1, today.year]), today)
    return frame.copy(), url


# Parsed once per build and day: CATALYSTS, FIXED INCOME, DCF and OVERVIEW all read it.
@lru_cache(maxsize=8)
def _curve(years: tuple[int, ...], today: date) -> tuple[pd.DataFrame, str]:
    rows: list[dict] = []
    for year in years:
        tree = etree.fromstring(_year_xml(year, today))
        for entry in tree.iter("{http://www.w3.org/2005/Atom}entry"):
            props = entry.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
            if props is None:
                continue
            stamp = props.findtext(f"{_D}NEW_DATE")
            if not stamp:
                continue
            observed = pd.Timestamp(stamp).strftime("%Y-%m-%d")
            for element, tenor, months in TENORS:
                text = props.findtext(f"{_D}{element}")
                if text is None or text == "":
                    continue
                try:
                    value = float(text)
                except ValueError:
                    continue
                rows.append(
                    {"date": observed, "tenor": tenor, "tenor_months": months, "yield_pct": value}
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, XML_URL.format(year=years[-1])
    frame = frame.drop_duplicates(["date", "tenor"], keep="last")
    return frame.sort_values(["date", "tenor_months"]).reset_index(drop=True), XML_URL.format(year=years[-1])


# Results belong to this existing Treasury source, alongside the calendar's
# announcement feed; they are not another risk score or a second calendar.
AUCTIONS_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
AUCTIONS_PAGE = "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/"
AUCTION_FIELDS = (
    "cusip", "auction_date", "security_type", "security_term", "original_security_term", "issue_date",
    "record_date", "reopening", "high_yield", "bid_to_cover_ratio", "comp_accepted",
    "direct_bidder_accepted", "indirect_bidder_accepted", "primary_dealer_accepted",
    "pdf_filenm_comp_results", "xml_filenm_comp_results",
)


def _auction_value(value) -> float | None:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a Treasury numeric value")
    if value is None or str(value).strip().lower() in {"null", "", "nan", "n/a"}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite Treasury value")
    return number


def parse_auction_results(payload: dict, *, observed_at: str, since: str, until: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Treasury response has no data array")
    rows, seen = [], set()
    for item in payload["data"]:
        if not isinstance(item, dict) or any(field not in item for field in AUCTION_FIELDS):
            raise ValueError("Treasury auction schema changed")
        auction_date = date.fromisoformat(item["auction_date"]).isoformat()
        if not since <= auction_date <= until or item["security_type"] not in {"Note", "Bond", "TIPS", "FRN"}:
            continue
        # API also contains future announcements. Missing results are not a
        # completed auction with zero demand; FRN's null high_yield is valid.
        filename = item["pdf_filenm_comp_results"]
        cover = _auction_value(item["bid_to_cover_ratio"])
        if filename in {None, "", "null"} or cover is None:
            continue
        if cover <= 0:
            raise ValueError("Invalid Treasury bid-to-cover ratio")
        if not isinstance(item["cusip"], str) or not item["cusip"].strip():
            raise ValueError("Treasury missing CUSIP identity")
        key = (item["cusip"], auction_date)
        if key in seen:
            raise ValueError("Duplicate Treasury CUSIP/auction-date grain")
        seen.add(key)
        row = {field: None if item[field] == "null" else item[field] for field in AUCTION_FIELDS}
        for field in ("high_yield", "bid_to_cover_ratio", "comp_accepted", "direct_bidder_accepted",
                      "indirect_bidder_accepted", "primary_dealer_accepted"):
            row[field] = _auction_value(item[field])
        total = row["comp_accepted"]
        allocation = [row[f] for f in ("direct_bidder_accepted", "indirect_bidder_accepted", "primary_dealer_accepted")]
        if any(v is not None and v < 0 for v in allocation) or (total is not None and total <= 0):
            raise ValueError("Invalid Treasury competitive allocation")
        if total is not None and all(v is not None for v in allocation) and abs(sum(allocation) - total) > 1:
            raise ValueError("Treasury bidder allocations do not reconcile to competitive accepted")
        for field in ("direct_bidder_accepted", "indirect_bidder_accepted", "primary_dealer_accepted"):
            row[field.removesuffix("_accepted") + "_share_pct"] = None if total is None or row[field] is None else 100 * row[field] / total
        row.update(observed_at=observed_at, release_time=None, vintage_class="current_vintage",
                   source_url=AUCTIONS_PAGE, tail_bps=None,
                   comparison_group=f"{row['security_type']}|{row['original_security_term']}|reopening={row['reopening']}")
        rows.append(row)
    return rows


def fetch_auction_history(*, since: str = "2008-01-01", use_cache: bool = True) -> list[dict]:
    """Every completed coupon auction from ``since``, for RISK's auction-demand
    cell: the same schema checks as the private collection, read through the
    build cache (twice a day), never written to the private snapshots."""
    until = date.today().isoformat()
    rows: list[dict] = []
    for page in range(1, 6):
        query = urlencode({"filter": f"security_type:in:(Note,Bond),auction_date:gte:{since},auction_date:lte:{until}",
                           "fields": ",".join(AUCTION_FIELDS + ("inflation_index_security", "floating_rate")),
                           "sort": "auction_date,cusip", "page[size]": 1000, "page[number]": page})
        body = cache.fetch_bytes("treasury", f"auctions-nominal-{since}-p{page}",
                                 lambda q=query: get_bytes(AUCTIONS_URL + "?" + q, timeout=60),
                                 kind="macro_series", suffix=".json", use_cache=use_cache)
        payload = json.loads(body)
        # TIPS and floating-rate notes are listed as notes too: only fixed-rate nominal coupons compare.
        nominal = [item for item in payload.get("data") or []
                   if item.get("inflation_index_security") != "Yes" and item.get("floating_rate") != "Yes"]
        rows.extend(parse_auction_results({**payload, "data": nominal}, observed_at=until, since=since, until=until))
        pages = int((payload.get("meta") or {}).get("total-pages") or 1)
        if page >= pages:
            return rows
    raise ValueError("Treasury auction history exceeded five pages")


def collect_auction_results(*, days: int = 90, root: Path | None = None) -> dict:
    """Explicit bounded collection; private snapshots, no dashboard rebuild."""
    if not 1 <= days <= 365:
        raise ValueError("days must be 1..365")
    root = root or REPO_ROOT / "data" / "private" / "treasury_auctions"
    started_at = datetime.now(timezone.utc).isoformat()
    until = date.today().isoformat()
    since = (date.today() - timedelta(days=days)).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "runs" / run_id
    rows, evidence, seen = [], [], set()
    try:
        for page in range(1, 6):
            query = urlencode({"filter": f"auction_date:gte:{since},auction_date:lte:{until}",
                               "fields": ",".join(AUCTION_FIELDS), "sort": "-auction_date,cusip",
                               "page[size]": 1000, "page[number]": page})
            url = AUCTIONS_URL + "?" + query
            body = get_bytes(url, timeout=30, retries=1)
            observed = datetime.now(timezone.utc).isoformat()
            digest = hashlib.sha256(body).hexdigest()
            raw = directory / f"page-{page}-{digest}.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(body)
            payload = json.loads(body)
            evidence.append({"request_url": url, "raw_path": str(raw), "raw_sha256": digest, "observed_at": observed})
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(meta, dict) or "total-pages" not in meta or isinstance(meta["total-pages"], bool):
                raise ValueError("Treasury pagination metadata missing")
            total_pages = int(meta["total-pages"])
            if total_pages < 1 or total_pages > 5:
                raise ValueError("Treasury pagination exceeded budget or is invalid")
            for row in parse_auction_results(payload, observed_at=observed, since=since, until=until):
                key = (row["cusip"], row["auction_date"])
                if key in seen:
                    raise ValueError("Treasury duplicate across result pages")
                seen.add(key)
                rows.append(row)
            if page >= total_pages:
                break
        else:
            raise ValueError("Treasury pagination exceeded budget; partial data not published")
        if not rows:
            raise ValueError("No completed coupon auction results in requested window")
        result = {"schema_version": 1, "source_id": "treasury_auction_results", "owner": "market-recap",
                  "status": "ok", "run_id": run_id, "started_at": started_at,
                  "observed_at": datetime.now(timezone.utc).isoformat(),
                  "window_start": since, "window_end": until, "rows": rows, "evidence": evidence,
                  "caveats": ["Indirect bidders are not identical to foreign buyers.",
                              "Compare within original maturity/type/reopening, not all auctions pooled.",
                              "record_date/issue_date are not publication timestamps; historical rows are current vintage.",
                              "Tail is unavailable without a same-auction pre-result when-issued yield."]}
        prior_path = root / "latest.json"
        prior = json.loads(prior_path.read_text()) if prior_path.exists() else {}
        key = lambda r: (r["cusip"], r["auction_date"])
        expected = {key(r) for r in prior.get("rows", []) if since <= r["auction_date"] <= until}
        if expected - seen:
            raise ValueError(f"Treasury coverage regressed: {len(expected - seen)} missing in-window auctions; last-good retained")
        # Immutable run = this fetch only; latest = retained history. Row
        # timestamps/evidence still describe their own genuine retrieval.
        write_json(directory / "snapshot.json", result)
        merged = {key(r): r for r in prior.get("rows", [])}
        merged.update({key(r): r for r in rows})
        result = {**result, "rows": sorted(merged.values(), key=lambda r: (r["auction_date"], r["cusip"]), reverse=True),
                  "captured_row_count": len(rows)}
        result["stored_coverage"] = {"start": min(r["auction_date"] for r in result["rows"]),
                                     "end": max(r["auction_date"] for r in result["rows"]), "rows": len(result["rows"])}
        # Keep immutable runs and replace only the local latest pointer.
        temporary = root / "latest.json.tmp"
        write_json(temporary, result)
        temporary.replace(root / "latest.json")
        write_json(root / "last_attempt.json", {"run_id": run_id, "status": "ok", "observed_at": result["observed_at"],
                                               "rows": len(rows), "stored_rows": len(result["rows"])})
        return result
    except Exception as exc:
        failure = {"run_id": run_id, "status": "failed", "observed_at": datetime.now(timezone.utc).isoformat(),
                   "error": f"{type(exc).__name__}: {str(exc)[:400]}", "evidence": evidence}
        write_json(directory / "failure.json", failure)
        write_json(root / "last_attempt.json", failure)
        raise


def public_auction_summary(root: Path | None = None) -> dict:
    """A small, official-data view for the rates page. Missing data stays missing.

    This reads only the local validated snapshot. It never fetches, and the
    result is deliberately limited to fields Treasury publishes openly.
    """
    path = root or REPO_ROOT / "data" / "private" / "treasury_auctions" / "latest.json"
    attempt_path = path.with_name("last_attempt.json")
    attempt = json.loads(attempt_path.read_text()) if attempt_path.exists() else None
    if not path.exists():
        return {"status": "missing", "groups": [], "rows": [], "last_attempt": attempt,
                "note": "No local Treasury auction-result snapshot."}
    snapshot = json.loads(path.read_text())
    rows = snapshot.get("rows") or []
    groups = {}
    for row in rows:
        groups.setdefault(row["comparison_group"], []).append(row)
    summaries = []
    for group, events in sorted(groups.items()):
        events = sorted(events, key=lambda r: (r["auction_date"], r["cusip"]))
        latest, previous = events[-1], events[-2] if len(events) > 1 else None
        def delta(field):
            if previous is None or latest.get(field) is None or previous.get(field) is None:
                return None
            return latest[field] - previous[field]
        summaries.append({
            "group": group,
            "type": latest["security_type"],
            "original_term": latest["original_security_term"],
            "reopening": latest["reopening"],
            "latest_date": latest["auction_date"],
            "previous_date": None if previous is None else previous["auction_date"],
            "high_yield": latest["high_yield"],
            "high_yield_change_bps": None if delta("high_yield") is None else round(delta("high_yield") * 100, 1),
            "bid_to_cover": latest["bid_to_cover_ratio"],
            "bid_to_cover_change": None if delta("bid_to_cover_ratio") is None else round(delta("bid_to_cover_ratio"), 2),
            "direct_share_pct": latest["direct_bidder_share_pct"],
            "indirect_share_pct": latest["indirect_bidder_share_pct"],
            "dealer_share_pct": latest["primary_dealer_share_pct"],
            "events": len(events),
            "observed_at": latest["observed_at"],
            "tail_bps": None,
        })
    return {
        "status": snapshot.get("status", "ok"),
        "source_url": AUCTIONS_PAGE,
        "coverage": snapshot.get("stored_coverage"),
        "last_attempt": attempt,
        "groups": summaries,
        "caveats": snapshot.get("caveats", []),
    }
