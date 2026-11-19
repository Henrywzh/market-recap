#!/usr/bin/env python3
"""Freeze the S&P 500's past breadth on the index's own members, once.

INDICES draws the share of S&P 500 members above their 50- and 200-day
averages. Rebuilt from today's members, its past is survivorship-biased: names
that joined later count in years they were not in the index. The research repo
(quantamental-lab, docs/spx_breadth_proxy_v1.md) reconstructed the members on
each day from public change lists (fja05680/sp500) and counted, each day, the
members with a full moving-average window. This script copies only those
derived daily shares -- no membership list, no prices -- into
config/spx_pit_breadth.json. The live build continues from the day after.

    python scripts/freeze_spx_pit_breadth.py RESULT_DIR [--start 2021-01-01]

RESULT_DIR is the reviewed result, e.g.
quantamental-lab/data/medium-horizon-systematic/spx_breadth_proxy_v1/results/20261103T123735412225Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

# The pinned fja05680/sp500 commit the study read (its input manifest).
MEMBERSHIP_COMMIT = "a2430f2af0c79ddf0748e91de11bdeb1616ab5a7"
OUT = Path(__file__).resolve().parents[1] / "config" / "spx_pit_breadth.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--start", default="2021-01-01")
    args = parser.parse_args()
    source = args.result / "proxy_daily_breadth.csv"
    manifest = json.loads((args.result / "manifest.json").read_text())
    frame = pd.read_csv(source, parse_dates=["date"]).set_index("date").sort_index()
    frame = frame.loc[args.start:]
    rounded = lambda s: [None if pd.isna(v) else round(float(v), 1) for v in s]
    payload = {
        "description": "S&P 500 members above their 50- and 200-day averages, counted on the members of each day",
        "method": ("Members on each day from a public reconstruction of S&P 500 changes (fja05680/sp500, "
                   "from Wikipedia's change tables; not S&P's own files). Share = members above their average "
                   "/ members with a full window of closes. Members without price history (mostly names that "
                   "were acquired or delisted) are left out; coverage is the share of members counted."),
        "source": {"study": "quantamental-lab spx_breadth_proxy_v1", "result": args.result.name,
                   "file": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "membership_commit": manifest.get("commit") or MEMBERSHIP_COMMIT},
        "start": frame.index[0].date().isoformat(),
        "through": frame.index[-1].date().isoformat(),
        "dates": [d.date().isoformat() for d in frame.index],
        "above_50d": rounded(frame["observed_50"]),
        "above_200d": rounded(frame["observed_200"]),
        "coverage": rounded(frame["coverage_200"] * 100),
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"{OUT}: {len(frame)} sessions {payload['start']} → {payload['through']}, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
