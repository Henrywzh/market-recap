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

from pathlib import Path
import shutil

from .config import ARTIFACT_DIR, REPO_ROOT

WEB_DIR = REPO_ROOT / "web"
DIST_DIR = REPO_ROOT / "dist"


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
    for source in WEB_DIR.rglob("*"):
        if source.is_file():
            _link_or_copy(source, dist / source.relative_to(WEB_DIR))
            pages += 1

    for source in ARTIFACT_DIR.rglob("*.json"):
        _link_or_copy(source, dist / "artifacts" / source.relative_to(ARTIFACT_DIR))
        assets += 1

    # Cloudflare Pages serves _headers from the site root. The artifacts are
    # rebuilt every session and the module URLs are already build-stamped, so
    # the page itself must never be cached: a stale index.html would load the
    # previous build's code against the current build's data.
    (dist / "_headers").write_text(
        "/\n"
        "  Cache-Control: no-cache\n"
        "/index.html\n"
        "  Cache-Control: no-cache\n"
        "/artifacts/*\n"
        "  Cache-Control: no-cache\n"
        "/js/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
        "/css/*\n"
        "  Cache-Control: public, max-age=3600\n",
        encoding="utf-8",
    )

    bytes_total = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    return {"dir": str(dist), "pages": pages, "artifacts": assets, "bytes": bytes_total}
