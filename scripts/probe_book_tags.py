"""Show what a filer's SEC facts say about tangible book, tag by tag.

Research tooling, not part of the build. For each ticker: every us-gaap tag whose
name mentions goodwill, intangibles, preferred stock or shareholders' equity,
with its latest balance-sheet instants (form, period end, value, filed), then
the figures the trailing snapshot actually used and the tangible book they gave.
It answers why a company has no tangible book (nothing tagged in the 10-Qs? a
tag the reader does not know?) or an implausible one.

    python scripts/probe_book_tags.py BLK AXP AFL --out data/probes/book
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import valuation as V  # noqa: E402
from market_recap.sources import sec  # noqa: E402

TAG = re.compile(r"goodwill|intangible|preferred|stockholdersequity|equity$", re.I)
KEEP = 6


def instants(concept: dict) -> list[dict]:
    rows = []
    for unit, entries in (concept.get("units") or {}).items():
        for row in entries:
            if row.get("start") is None and row.get("end"):
                rows.append({"form": row.get("form"), "end": row["end"], "val": row.get("val"), "filed": row.get("filed"), "unit": unit})
    rows.sort(key=lambda r: (r["end"], r["filed"] or ""))
    return rows[-KEEP:]


def probe(ticker: str, cik_map: dict) -> dict:
    cik = cik_map.get(ticker) or cik_map.get(ticker.replace("-", "."))
    if cik is None:
        return {"ticker": ticker, "error": "no CIK"}
    facts, ciks = sec.fetch_filer_facts(int(cik))
    gaap = facts.get("facts", {}).get("us-gaap", {})
    tags = {name: instants(concept) for name, concept in gaap.items() if TAG.search(name)}
    tags = {name: rows for name, rows in tags.items() if rows}
    snapshot = sec.trailing_snapshot(facts)
    balance = (snapshot or {}).get("balance") or {}
    return {
        "ticker": ticker, "ciks": ciks, "period_end": (snapshot or {}).get("period_end"),
        "tags": tags,
        "snapshot_balance": {k: balance.get(k) for k in ("equity", "goodwill", "intangibles", "preferred")},
        "tangible_book": V.tangible_book(balance),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--out", default="data/probes/book")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cik_map = sec.fetch_ticker_cik_map()
    results = []
    for ticker in args.tickers:
        try:
            results.append(probe(ticker, cik_map))
        except Exception as exc:  # noqa: BLE001 -- one name must not stop the rest
            results.append({"ticker": ticker, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        print(ticker, "ok" if "error" not in results[-1] else results[-1]["error"], flush=True)
    (out / "book_tags.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
