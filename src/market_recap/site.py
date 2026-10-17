"""Assemble the deployable site.

The page and its artifacts have to sit in one directory tree, and that tree has
to be the same one in development and in production. Serving the page from
``/web/index.html`` locally and from ``/`` in production would mean the deploy
step rewrites asset paths -- and a path rewrite is the kind of build-time magic
that works until the day it silently does not, on the copy nobody runs locally.

So there is one layout: ``dist/index.html`` with ``dist/artifacts`` beside it.
``make serve`` serves it and ``make deploy`` uploads it, both looking at
exactly the same bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from . import mcp_slices
from .config import ARTIFACT_DIR, REPO_ROOT, load_config

WEB_DIR = REPO_ROOT / "web"
DIST_DIR = REPO_ROOT / "dist"
CODE_VERSION_PLACEHOLDER = "__CODE_VERSION__"
IMPORTMAP_PLACEHOLDER = "<!--IMPORTMAP-->"


def code_version(web: Path = WEB_DIR) -> str:
    """A short hash of every script, in path order."""
    digest = hashlib.sha256()
    for source in sorted((web / "js").rglob("*.js")):
        digest.update(source.relative_to(web).as_posix().encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()[:12]


def import_map(web: Path = WEB_DIR) -> str:
    """Map every script to its URL plus a hash of its own bytes.

    Tabs import shared modules by plain relative path (``../fmt.js``), and the
    JS is served immutable, so without the map a browser that once loaded
    ``fmt.js`` keeps that copy for a year whatever is deployed after it.
    """
    imports = {}
    for source in sorted((web / "js").rglob("*.js")):
        path = f"./{source.relative_to(web).as_posix()}"
        imports[path] = f"{path}?h={hashlib.sha256(source.read_bytes()).hexdigest()[:10]}"
    return '<script type="importmap">' + json.dumps({"imports": imports}, separators=(",", ":")) + "</script>"


def live_contract(config: dict | None = None, *, weighted_names: list[str] | None = None) -> dict:
    """What the intraday quotes may fetch, derived from the dashboard contract.

    The quote function reads this file and fetches nothing else, so it is an
    allowlist as much as a list: the endpoint cannot be used to proxy
    arbitrary symbols. ``weighted_names`` are the heat map's members, heaviest
    first; they are the heat-map board and the trade desk's pre-market scan.
    """
    config = config or load_config()
    live = config.get("live", {})
    strip: list[dict] = [{"symbol": e["symbol"], "label": e["label"], "kind": e.get("kind", "index")}
                         for e in live.get("strip", [])]
    strip += [{"symbol": t, "label": t, "kind": "watch"} for t in live.get("strip_names", [])]
    seen: set[str] = set()
    strip = [e for e in strip if not (e["symbol"] in seen or seen.add(e["symbol"]))]
    limit = max(0, min(int(live.get("premarket_top_weight_names", 0)), 50))
    candidates = (weighted_names or [])[:limit] if weighted_names else live.get("premarket_movers", [])
    candidates = list(dict.fromkeys([*candidates, *(e["ticker"] for e in config.get("watchlist", []))]))
    board = {"refresh_seconds": live.get("board_refresh_seconds", 300),
             "closed_refresh_seconds": live.get("board_closed_refresh_seconds", 900)}
    boards = {"indices": {**board, "series": True, "symbols": [e["symbol"] for e in live.get("index_board", [])],
                          "labels": {e["symbol"]: e["label"] for e in live.get("index_board", [])}}}
    if weighted_names:
        boards["heatmap"] = {**board, "series": False, "symbols": list(dict.fromkeys(weighted_names))}
    # Asked for only on REFRESH (SECTORS, MACRO, the Treasury table).
    etfs = live.get("sector_etfs", [])
    if etfs:
        bench = live.get("sector_benchmark", "SPY")
        boards["sector_etfs"] = {**board, "series": False, "symbols": [e["symbol"] for e in etfs] + [bench],
                                 "labels": {**{e["symbol"]: e["sector"] for e in etfs}, bench: "benchmark"}}
    commodities = config.get("macro", {}).get("commodities", {})
    if commodities:
        boards["macro"] = {**board, "series": False, "symbols": list(dict.fromkeys(commodities.values())),
                           "labels": {symbol: label for label, symbol in commodities.items()}}
    if live.get("yield_board"):
        boards["yields"] = {**board, "source": "cnbc", "symbols": [e["symbol"] for e in live["yield_board"]],
                            "labels": {e["symbol"]: e["label"] for e in live["yield_board"]}}
    return {
        "refresh_seconds": live.get("refresh_seconds", 60),
        "closed_refresh_seconds": live.get("closed_refresh_seconds", 300),
        "server_cache_seconds": live.get("server_cache_seconds", 15),
        "board_cache_seconds": live.get("board_cache_seconds", 60),
        "manual_min_seconds": live.get("manual_min_seconds", 30),
        "stale_after_seconds": live.get("stale_after_seconds", 1200),
        "strip": strip,
        "boards": boards,
        "overnight": [{"symbol": r["symbol"], "label": r["label"], "kind": "overnight", "region": r["region"]}
                      for r in live.get("overnight", [])],
        "premarket_movers": [{"symbol": symbol, "label": symbol, "kind": "premarket"} for symbol in candidates],
        "rates": [{"symbol": r["symbol"], "label": r["label"], "kind": "rate", "source": r.get("source", "cnbc")}
                  for r in live.get("rates", [])],
    }


def _link_or_copy(source: Path, target: Path) -> None:
    """Hard-link where the filesystem allows it, copy where it does not.

    A hard link is a real directory entry, so anything reading ``dist`` -- a
    web server, wrangler -- sees an ordinary file. It just avoids duplicating
    31 MB of artifacts on every build.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        target.hardlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def build(*, dist: Path | None = None) -> dict:
    """Write the deployable tree. Returns what it contains."""
    dist = dist or DIST_DIR
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    pages = assets = 0
    # Source files are copied, never hard-linked: a link makes the page's
    # source and a disposable build output one file on disk, and on
    # 2026-09-23 every hard-linked web/ file vanished together with its dist/
    # twin (a sync client resolving what it took for duplicates, most likely).
    # The source is small; only the regenerable artifacts are linked.
    for source in WEB_DIR.rglob("*"):
        if source.is_file():
            target = dist / source.relative_to(WEB_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            pages += 1

    # The JS is cached as immutable under a versioned URL; the version has to
    # move when the code does, not only when the data is rebuilt.
    index = dist / "index.html"
    page = index.read_text(encoding="utf-8")
    page = page.replace(CODE_VERSION_PLACEHOLDER, code_version()).replace(IMPORTMAP_PLACEHOLDER, import_map())
    index.write_text(page, encoding="utf-8")

    for source in ARTIFACT_DIR.rglob("*.json"):
        _link_or_copy(source, dist / "artifacts" / source.relative_to(ARTIFACT_DIR))
        assets += 1

    # The MCP server's per-call slices, cut from the artifacts just copied, so
    # they describe these bytes and no others (src/market_recap/mcp_slices.py).
    mcp = mcp_slices.write(dist / "artifacts")

    # Beside the page rather than under artifacts/: it is the contract the
    # quote function enforces, written from config on every site build, not a
    # data product of the refresh.
    try:
        heatmap = json.loads((ARTIFACT_DIR / "heatmaps.json").read_text())
        weighted_names = [r["ticker"] for r in sorted(heatmap["constituents"],
                          key=lambda r: r.get("weight") or 0, reverse=True) if r.get("ticker")]
        # The other index maps' members go after, so LIVE colours them too;
        # the pre-market scan still reads the heaviest S&P 500 names first.
        for extra in heatmap.get("index_maps") or []:
            weighted_names += [r["ticker"] for r in extra.get("constituents", []) if r.get("ticker")]
        weighted_names = list(dict.fromkeys(weighted_names))
    except (OSError, ValueError, KeyError, TypeError):
        weighted_names = None
    (dist / "live.json").write_text(json.dumps(live_contract(weighted_names=weighted_names), indent=1), encoding="utf-8")

    # Cloudflare Pages serves _headers from the site root.
    #
    # Only the JS may be cached hard, and only because its URLs carry the
    # build stamp (`app.js?v=<generated_at>-<code hash>`): a new build or a
    # code change is a new URL, so an immutable copy of the old one is never
    # consulted again.
    #
    # Everything else is `no-cache`, which still revalidates against the ETag
    # and answers 304 when nothing changed -- it costs a round trip, not a
    # download. The stylesheet had `max-age=3600` and is *not* build-stamped,
    # which meant a deployed CSS fix was invisible to anyone who had loaded
    # the page in the previous hour. A cache lifetime longer than the deploy
    # interval, on a file whose URL never changes, is a way to ship a fix that
    # does not arrive.
    # The paths must not overlap. Pages applies *every* matching rule and
    # concatenates the results, so a "/*" catch-all alongside a "/js/*" rule
    # produced "no-cache, public, max-age=31536000, immutable" on the same
    # response -- a header that contradicts itself and leaves the behaviour up
    # to whichever directive a given browser decides to honour.
    (dist / "_headers").write_text(
        "/\n"
        "  Cache-Control: no-cache\n"
        "/index.html\n"
        "  Cache-Control: no-cache\n"
        "/_headers\n"
        "  Cache-Control: no-cache\n"
        "/live.json\n"
        "  Cache-Control: no-cache\n"
        "/css/*\n"
        "  Cache-Control: no-cache\n"
        "/artifacts/*\n"
        "  Cache-Control: no-cache\n"
        "/js/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n",
        encoding="utf-8",
    )

    bytes_total = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    return {"dir": str(dist), "pages": pages, "artifacts": assets, "mcp_slices": mcp["files"], "bytes": bytes_total}
