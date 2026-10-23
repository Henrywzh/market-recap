"""Risk inputs as they were published each day.

Some risk histories cannot be read back later as they stood at the time:
OFR's Financial Stress Index is revised and served only as its current
vintage; FRED now serves the ICE BofA spreads for the last three years only;
Cboe back-calculates newer indices. Recording what each publisher served on
a given evening is the only way to build a true point-in-time history of
them (quantamental-lab's risk re-audit names this as its first blocker).

Each run writes the last ``tail`` observations of every series -- not just
the newest -- so a revision to a recent value shows up as a difference
between two evenings' files. Rows: fetched_at, source, series, date, value.

The first run also writes a baseline: every observation each publisher
served that evening, under ``risk/baseline/``. That is current-vintage
history -- today's view of the past, revisions included -- not what was
known at the time, and its sidecar says so. It keeps what FRED will drop
from the ICE spreads' three-year window, and gives the daily files a
history to extend.

The same evening run records the units of ETFs whose issuer publishes only
today's figure (Invesco: QQQ, RSP). Rows: source "invesco", series
"<TICKER> shares_outstanding" and "<TICKER> nav", dated by the issuer's own
effective date. Differencing the record is the only way to a flow history
for these funds; the record starts on the first evening it ran.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
from typing import Any, Callable, Mapping

import pandas as pd

from ..config import load_config
from ..sources import cboe, fred, invesco
from ..sources.http import get_text
from . import store

COLUMNS = ("fetched_at", "source", "series", "date", "value")
OFR_FSI_URL = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
DEFAULT_FRED = [
    "BAMLH0A0HYM2", "BAMLC0A0CM", "BAMLH0A3HYC", "BAMLH0A1HYBB", "BAMLH0A2HYB", "BAMLC0A4CBBB",
    "NFCI", "ANFCI",
]
DEFAULT_CBOE = ["VIX", "VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "COR1M"]


def fetch_ofr_fsi() -> pd.DataFrame:
    """OFR FSI and its components, one column per series, indexed by date."""
    frame = pd.read_csv(StringIO(get_text(OFR_FSI_URL, timeout=45.0)))
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame.dropna(subset=["Date"]).set_index("Date").sort_index()


def _fred(series_id: str) -> pd.Series:
    frame, _ = fred.fetch_series(series_id, use_cache=False)
    return frame.set_index("date")["value"].sort_index()


def _cboe(symbol: str) -> pd.Series:
    return cboe.fetch_index(symbol, use_cache=False)


def rows_for(fetched_at: str, source: str, series: str, values: pd.Series, tail: int | None) -> list[dict]:
    clean = pd.to_numeric(values, errors="coerce").dropna().sort_index()
    clean = clean.tail(tail) if tail else clean
    return [{"fetched_at": fetched_at, "source": source, "series": series,
             "date": pd.Timestamp(day).strftime("%Y-%m-%d"), "value": float(value)}
            for day, value in clean.items()]


BASELINE_NOTE = (
    "Current-vintage history: every observation each publisher served at fetched_at, "
    "revisions included. Not point-in-time; do not use it as what was known on a past date."
)


# Invesco funds recorded beside those in config ([snapshots.risk] invesco), by
# CUSIP: QQQM, the other Nasdaq-100 fund, added for the FLOWS tab's coverage.
INVESCO_RECORDED = {"QQQM": "46138G649"}


def _etf_units(settings: Mapping[str, Any], config: Mapping[str, Any],
               fetch_units: Callable[[str], dict]) -> tuple[list[tuple[str, str, pd.Series]], dict, dict]:
    """(series, answered, failed) for the ETFs whose units are recorded here."""
    holdings = config.get("etf_xray", {}).get("holdings", {})
    series, answered, failed = [], {}, {}
    for ticker in dict.fromkeys([*settings.get("invesco", []), *INVESCO_RECORDED]):
        cusip = invesco.cusip_for(holdings.get(ticker)) or INVESCO_RECORDED.get(ticker)
        if not cusip:
            failed[f"invesco {ticker}"] = "no invesco:<CUSIP> entry under [etf_xray.holdings]"
            continue
        try:
            units = fetch_units(cusip)
        except Exception as exc:
            failed[f"invesco {ticker}"] = str(exc)[:200]
            continue
        day = pd.Timestamp(units["date"])
        for field in ("shares_outstanding", "nav"):
            series.append(("invesco", f"{ticker} {field}", pd.Series([units[field]], index=[day], dtype=float)))
        answered[f"invesco {ticker}"] = 1
    return series, answered, failed


def run(*, root=None, now: datetime | None = None, baseline: bool | None = None,
        fetch_ofr: Callable[[], pd.DataFrame] = fetch_ofr_fsi,
        fetch_fred: Callable[[str], pd.Series] = _fred,
        fetch_cboe: Callable[[str], pd.Series] = _cboe,
        fetch_units: Callable[[str], dict] = invesco.fetch_units) -> dict:
    """Record tonight's tail of every series. ``baseline``: None writes the
    full-history baseline only if none exists yet; True forces a new one."""
    config = load_config()
    settings: Mapping[str, Any] = config.get("snapshots", {}).get("risk", {})
    tail = int(settings.get("tail", 30))
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(store.NEW_YORK)
    fetched_at = store.utc_stamp(now)
    series: list[tuple[str, str, pd.Series]] = []
    failed: dict[str, str] = {}
    answered: dict[str, int] = {}

    try:
        ofr = fetch_ofr()
        for column in ofr.columns:
            series.append(("ofr", f"FSI {column}" if column != "OFR FSI" else "FSI", ofr[column]))
        answered["ofr"] = len(ofr.columns)
    except Exception as exc:
        failed["ofr fsi"] = str(exc)[:200]
    for source, names, fetch in (("fred", settings.get("fred", DEFAULT_FRED), fetch_fred),
                                 ("cboe", settings.get("cboe", DEFAULT_CBOE), fetch_cboe)):
        for name in names:
            try:
                values = fetch(name)
                series.append((source, name, values))
                answered[f"{source} {name}"] = int(pd.to_numeric(values, errors="coerce").notna().sum())
            except Exception as exc:
                failed[f"{source} {name}"] = str(exc)[:200]
    units, units_answered, units_failed = _etf_units(settings, config, fetch_units)
    series += units
    answered |= units_answered
    failed |= units_failed

    rows = [row for source, name, values in series for row in rows_for(fetched_at, source, name, values, tail)]
    base = store.root_dir(root) / "risk"
    folder = store.day_dir(store.root_dir(root), "risk", local)
    if rows:
        store.write_csv(folder / f"{local:%Y-%m-%d}.csv.gz", rows, COLUMNS, compress=True)

    baseline_dir = base / "baseline"
    wrote_baseline = None
    if series and (baseline or (baseline is None and not any(baseline_dir.glob("*.csv.gz")))):
        baseline_dir.mkdir(parents=True, exist_ok=True)
        full = [row for source, name, values in series for row in rows_for(fetched_at, source, name, values, None)]
        path = baseline_dir / f"{local:%Y-%m-%d}.csv.gz"
        store.write_csv(path, full, COLUMNS, compress=True)
        (baseline_dir / f"{local:%Y-%m-%d}.json").write_text(
            json.dumps({"fetched_at": fetched_at, "rows": len(full), "note": BASELINE_NOTE}, indent=2) + "\n")
        wrote_baseline = {"path": str(path.relative_to(store.root_dir(root))), "rows": len(full)}

    record = {"fetched_at": fetched_at, "rows": len(rows), "answered": answered, "failed": failed,
              "baseline": wrote_baseline}
    store.append_jsonl(folder / "runs.jsonl", record)
    status = "failed" if not rows else ("partial" if failed else "ok")
    return {"status": status, **record}
