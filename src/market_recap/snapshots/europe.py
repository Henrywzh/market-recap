"""Once-a-day snapshot of the European names' multiples and consensus.

Free sources publish today's forward P/E, never yesterday's, so a history can
only exist if it is recorded as it stands each day. Yahoo's own forward and
trailing P/E are recorded as served (Yahoo converts between a company's price
currency and its reporting currency, which an EPS divided into a London price
in pence would get wrong), beside the consensus EPS for this and next fiscal
year and the price and market cap they were read against. One file per New
York date:

- ``europe/YYYY/YYYY-MM-DD.csv.gz``: one row per symbol.

The universe is the published EUROPE artifact's names (the FTSE 100 and EURO
STOXX 50 members and the named groups). A second run on a date that already has
most of the universe is skipped; a name it could not reach keeps the earlier
run's row.
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
from ..sources import europe as source
from ..sources.http import FetchError, get_text
from . import store

COLUMNS = ("fetched_at", "symbol", "currency", "price", "market_cap", "forward_pe", "trailing_pe", "forward_eps",
           "trailing_eps", "eps_0y", "eps_0y_end", "eps_0y_year_ago", "eps_1y", "analysts_0y")
COMPLETE_SHARE = 0.8


def published_universe(base_url: str) -> list[str]:
    text = get_text(f"{base_url.rstrip('/')}/artifacts/europe.json", timeout=45.0, retries=1)
    payload = json.loads(text)
    names = [n["symbol"] for u in (payload.get("universes") or {}).values() for n in u.get("names") or []]
    names += [n["symbol"] for g in payload.get("groups") or [] for n in g.get("names") or []]
    return sorted({s for s in names if s})


def row_for(fetched_at: str, symbol: str, multiples: Mapping[str, Any] | None, trend: Mapping[str, Any] | None) -> dict | None:
    """One recorded row, or None when neither source answered."""
    m, t = multiples or {}, trend or {}
    this, nxt = t.get("0y") or {}, t.get("+1y") or {}
    if not m and not this:
        return None
    return {"fetched_at": fetched_at, "symbol": symbol, "currency": m.get("currency"), "price": m.get("price"),
            "market_cap": m.get("market_cap"), "forward_pe": m.get("forward_pe"), "trailing_pe": m.get("trailing_pe"),
            "forward_eps": m.get("forward_eps"), "trailing_eps": m.get("trailing_eps"),
            "eps_0y": this.get("eps"), "eps_0y_end": this.get("end"), "eps_0y_year_ago": this.get("year_ago_eps"),
            "eps_1y": nxt.get("eps"), "analysts_0y": this.get("analysts")}


def _recorded(path) -> list[dict]:
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
            return {"status": "failed", "reason": f"published europe artifact: {exc}"}
    if not symbols:
        return {"status": "failed", "reason": "the published europe artifact lists no names"}
    folder = store.day_dir(store.root_dir(root), "europe", local)
    path = folder / f"{today}.csv.gz"
    meta = folder / f"{today}.json"
    if meta.exists():
        try:
            prior = json.loads(meta.read_text())
            if int(prior.get("companies", 0)) >= math.ceil(COMPLETE_SHARE * len(symbols)):
                return {"status": "skipped", "reason": f"{today} already has {prior['companies']} names"}
        except (OSError, ValueError, TypeError):
            pass

    fetched_at = store.utc_stamp(now)
    multiples, failed = source.fetch_multiples(symbols, use_cache=False)
    trends, _ = estimates.fetch_trends(symbols, use_cache=False)
    rows = [r for s in sorted(set(multiples) | set(trends)) if (r := row_for(fetched_at, s, multiples.get(s), trends.get(s)))]
    fresh = {r["symbol"] for r in rows}
    kept = [r for r in _recorded(path) if r.get("symbol") not in fresh] if rows else []
    rows = sorted(rows + kept, key=lambda r: r["symbol"])
    companies = len({r["symbol"] for r in rows})
    record = {"session": today.isoformat(), "fetched_at": fetched_at, "universe": len(symbols), "companies": companies,
              "fetched": len(fresh), "kept_from_earlier": len({r["symbol"] for r in kept}), "rows": len(rows),
              "failed": dict(list(failed.items())[:50]), "failed_count": len(failed)}
    if not rows:
        return {"status": "failed", "reason": "no multiples or estimates answered", **record}
    store.write_csv(path, rows, COLUMNS, compress=True)
    meta.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    status = "ok" if companies >= COMPLETE_SHARE * len(symbols) else "partial"
    return {"status": status, **record}
