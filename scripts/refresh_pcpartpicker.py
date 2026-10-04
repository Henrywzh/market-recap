"""Refresh the committed PCPartPicker ratio snapshot.

Run this on a home connection. Cloudflare answers GitHub Actions with HTTP 403,
and that refusal is not worked around. The file keeps ratios and a weekly
index only; the chart images are not stored.
"""

from __future__ import annotations

from datetime import date
import sys

from market_recap.sources import pcpartpicker


def main() -> int:
    payload = pcpartpicker.snapshot(use_cache=False)
    empty = [kind for kind in ("memory", "cpu") if not (payload.get(kind) or {}).get("rows")]
    if empty or payload.get("failed"):
        print("incomplete snapshot" + (": no charts read for " + ", ".join(empty) if empty else ""), file=sys.stderr)
        for item in payload.get("failed") or []:
            print(item, file=sys.stderr)
        return 1
    dates = pcpartpicker._chart_dates(payload)
    age = (date.today() - date.fromisoformat(min(dates))).days
    if age > pcpartpicker.STALE_DAYS:
        print(f"stale snapshot: oldest chart is {min(dates)} ({age} days old)", file=sys.stderr)
        return 1
    path = pcpartpicker.write_feed(payload)
    print(f"wrote {path}")
    print("chart dates " + ", ".join(sorted(set(dates))))
    for kind in ("memory", "cpu"):
        section = payload[kind]
        print(f"{kind}: {len(section['rows'])} charts, families {', '.join(section['families'])}")
    if payload.get("failed"):
        print("partial: " + "; ".join(payload["failed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
