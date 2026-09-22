"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import build as build_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-recap", description="Build the dashboard artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="Fetch sources and write artifacts.")
    refresh.add_argument("--panels", nargs="*", help="Subset of panels to rebuild.")
    # The forward-return table on TECHNICALS is only as good as its sample:
    # three years leaves the extreme z-score bands with single-digit counts.
    # Ten years costs a slower first build and nothing on later ones, because
    # the day's closes are cached.
    refresh.add_argument("--history", default="10y", help="yfinance history period for constituents.")
    refresh.add_argument("--skip-dcf", action="store_true", help="Skip the SEC fundamentals bake.")

    args = parser.parse_args(argv)
    if args.command == "refresh":
        manifest = build_module.run(
            panels=args.panels or None, history_period=args.history, skip_dcf=args.skip_dcf
        )
        print(json.dumps({k: v for k, v in manifest.items() if k != "sources"}, indent=2)[:2000])
        failed = manifest.get("errors") or {}
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
