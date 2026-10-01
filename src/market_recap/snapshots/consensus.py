"""Once-a-day consensus snapshot: each covered company's EPS estimates.

Free sources publish today's consensus, never yesterday's, so a forward P/E
can only have a history if the consensus is recorded as it stands each
evening. One file per New York date:

- ``consensus/YYYY/YYYY-MM-DD.csv.gz``: one row per company and fiscal
  period (this and next quarter, this and next year) from Yahoo's
  earningsTrend: the period's end, consensus EPS and its range, analysts,
  revenue, and the 30-day revision counts.

The universe is the published VALUATION table, so the snapshot covers the
companies the site values. A second run on a date that already has most of
the universe is skipped.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import json
import math
from typing import Any, Mapping

from ..config import load_config
from ..sources import estimates
from ..sources.http import FetchError, get_text
from . import store

COLUMNS = ("fetched_at", "symbol", "period", "end", "eps", "eps_low", "eps_high", "analysts",
           "revenue", "up_30d", "down_30d")
# A day already recorded for this share of the universe is not fetched again.
COMPLETE_SHARE = 0.8


def published_universe(base_url: str) -> list[str]:
    text = get_text(f"{base_url.rstrip('/')}/artifacts/valuation.json", timeout=45.0, retries=1)
    return sorted({row["ticker"] for row in json.loads(text).get("rows") or [] if row.get("ticker")})


def rows_for(fetched_at: str, symbol: str, trend: Mapping[str, Any]) -> list[dict]:
    out = []
    for period in estimates.PERIODS:
        row = trend.get(period) or {}
        if row.get("eps") is None:
            continue
        out.append({"fetched_at": fetched_at, "symbol": symbol, "period": period, "end": row.get("end"),
                    "eps": row.get("eps"), "eps_low": row.get("low"), "eps_high": row.get("high"),
                    "analysts": row.get("analysts"), "revenue": row.get("revenue"),
                    "up_30d": row.get("up_30d"), "down_30d": row.get("down_30d")})
    return out


def _recorded(path) -> list[dict]:
    """Rows an earlier run already wrote for the day; empty if none or unreadable."""
    if not path.exists():
        return []
    try:
        with gzip.open(path, "rt", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, EOFError, csv.Error):
        return []


def run(*, root=None, now: datetime | None = None, symbols: list[str] | None = None) -> dict:
    config = load_config()
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(store.NEW_YORK)
    today = local.date()
    if local.weekday() >= 5:
        return {"status": "skipped", "reason": f"{local:%a} is not a weekday"}
    if symbols is None:
        base_url = config.get("monitor", {}).get("published_base_url")
        try:
            symbols = published_universe(base_url)
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            return {"status": "failed", "reason": f"published valuation table: {exc}"}
    folder = store.day_dir(store.root_dir(root), "consensus", local)
    path = folder / f"{today}.csv.gz"
    meta = folder / f"{today}.json"
    if meta.exists():
        try:
            prior = json.loads(meta.read_text())
            if int(prior.get("companies", 0)) >= math.ceil(COMPLETE_SHARE * len(symbols)):
                return {"status": "skipped", "reason": f"{today} already has {prior['companies']} companies"}
        except (OSError, ValueError, TypeError):
            pass

    fetched_at = store.utc_stamp(now)
    trends, failed = estimates.fetch_trends(symbols, use_cache=False)
    rows = [row for symbol in sorted(trends) for row in rows_for(fetched_at, symbol, trends[symbol])]
    # A second run the same day adds to the first: a company it could not
    # reach keeps the earlier run's estimates instead of losing them.
    fresh = {row["symbol"] for row in rows}
    kept = [row for row in _recorded(path) if row.get("symbol") not in fresh] if rows else []
    rows = sorted(rows + kept, key=lambda r: (r["symbol"], r["period"]))
    companies = len({row["symbol"] for row in rows})
    record = {"session": today.isoformat(), "fetched_at": fetched_at, "universe": len(symbols),
              "companies": companies, "fetched": len(trends), "kept_from_earlier": len({r["symbol"] for r in kept}), "rows": len(rows), "failed": dict(list(failed.items())[:50]),
              "failed_count": len(failed)}
    if not rows:
        return {"status": "failed", "reason": "no estimates answered", **record}
    store.write_csv(path, rows, COLUMNS, compress=True)
    meta.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    status = "ok" if companies >= COMPLETE_SHARE * len(symbols) else "partial"
    return {"status": status, **record}
