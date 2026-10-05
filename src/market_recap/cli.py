"""Command line entry point.

``refresh`` is the whole pipeline: fetch, build, validate, prune. It is what
the scheduler runs, so it exits non-zero on anything that would put a wrong
number on the page.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import build as build_module
from . import cache, site, validate

MANIFEST_PREVIEW_KEYS = (
    "as_of", "build_seconds", "timings", "indices", "panels", "skipped_panels", "errors",
    # What the build had to repair, and whether the night's session was cross-checked:
    # the first things to read in a scheduled run's log.
    "filled_sessions", "session_check", "sec_filings",
)


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-recap", description="Build the dashboard artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="Fetch sources, write artifacts and validate them.")
    refresh.add_argument("--panels", nargs="*", help="Subset of panels to rebuild.")
    # The forward-return table on TECHNICALS is only as good as its sample:
    # three years leaves the extreme z-score bands with single-digit counts.
    # Ten years costs a slower first build and nothing on later ones, because
    # the day's closes are cached.
    refresh.add_argument("--history", default="10y", help="yfinance history period for constituents.")
    refresh.add_argument("--skip-sec", action="store_true", help="Skip the SEC panels (FINANCIALS, VALUATION, DCF).")
    refresh.add_argument("--keep-cache", action="store_true", help="Do not prune expired cache entries.")
    refresh.add_argument(
        "--allow-warnings", action="store_true",
        help="Exit 0 when validation reports warnings but no errors (the default).",
    )
    refresh.add_argument(
        "--strict", action="store_true",
        help="Treat validation warnings as failures. For the scheduled run.",
    )

    sub.add_parser("validate", help="Re-check the artifacts already on disk.")
    sub.add_parser("site", help="Assemble dist/ from the artifacts already on disk.")

    auctions = sub.add_parser("auction-results", help="Collect completed coupon auctions into the existing Treasury source's private evidence store.")
    auctions.add_argument("--days", type=int, default=90, help="Bounded recent window (1..365 calendar days).")
    auctions.add_argument("--query", action="store_true", help="Read the local latest snapshot without network access.")

    snapshot = sub.add_parser("snapshot", help="Record option chains, market expectations, risk inputs or consensus as published (see snapshots/).")
    snapshot.add_argument("kind", choices=("options", "expectations", "risk", "consensus"))
    snapshot.add_argument("--root", help="Directory to write under (default: [snapshots] root).")
    snapshot.add_argument(
        "--force", action="store_true",
        help="options: snapshot even outside the configured New York window.",
    )
    snapshot.add_argument(
        "--baseline", action="store_true",
        help="risk: also write a new full-history (current-vintage) baseline.",
    )

    prune = sub.add_parser("prune", help="Delete expired cache entries.")
    prune.add_argument("--all", action="store_true", help="Delete every cache entry, not just expired ones.")

    args = parser.parse_args(argv)

    if args.command == "auction-results":
        from .config import REPO_ROOT
        from .sources import treasury
        if args.query:
            path = REPO_ROOT / "data" / "private" / "treasury_auctions" / "latest.json"
            _print({"network": False, "snapshot": json.loads(path.read_text()) if path.exists() else None,
                    "last_attempt": json.loads(path.with_name("last_attempt.json").read_text()) if path.with_name("last_attempt.json").exists() else None})
            return 0
        try:
            result = treasury.collect_auction_results(days=args.days)
        except Exception as exc:
            _print({"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
            return 1
        _print({"status": result["status"], "rows": len(result["rows"]), "run_id": result["run_id"],
                "latest": str(REPO_ROOT / "data" / "private" / "treasury_auctions" / "latest.json")})
        return 0

    if args.command == "refresh":
        manifest = build_module.run(
            panels=args.panels or None,
            history_period=args.history,
            skip_sec=args.skip_sec,
            prune_cache=not args.keep_cache,
        )
        _print({k: manifest[k] for k in MANIFEST_PREVIEW_KEYS if k in manifest})
        report = validate.run()
        _print(report)
        if report["errors"]:
            return 1
        return 1 if args.strict and report["warnings"] else 0

    if args.command == "site":
        _print(site.build())
        return 0

    if args.command == "validate":
        report = validate.run()
        _print(report)
        return 0 if report["ok"] else 1

    if args.command == "snapshot":
        if args.kind == "options":
            from .snapshots import options as snap
            result = snap.run(root=args.root, force=args.force)
        elif args.kind == "risk":
            from .snapshots import risk as snap
            result = snap.run(root=args.root, baseline=True if args.baseline else None)
        elif args.kind == "consensus":
            from .snapshots import consensus as snap
            result = snap.run(root=args.root)
        else:
            from .snapshots import expectations as snap
            result = snap.run(root=args.root)
        _print(result)
        # A skipped run (outside the window, market closed) is not a failure.
        return 1 if result["status"] == "failed" else 0

    if args.command == "prune":
        from datetime import timedelta

        _print(cache.prune(keep=timedelta(0) if args.all else None))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
