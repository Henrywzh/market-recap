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

    for source in ARTIFACT_DIR.rglob("*.json"):
        _link_or_copy(source, dist / "artifacts" / source.relative_to(ARTIFACT_DIR))
        assets += 1

    # Cloudflare Pages serves _headers from the site root.
    #
    # Only the JS may be cached hard, and only because its URLs carry the
    # build stamp (`app.js?v=<generated_at>`): a new build is a new URL, so an
    # immutable copy of the old one is never consulted again.
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
        "/css/*\n"
        "  Cache-Control: no-cache\n"
        "/artifacts/*\n"
        "  Cache-Control: no-cache\n"
        "/js/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n",
        encoding="utf-8",
    )

    bytes_total = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    return {"dir": str(dist), "pages": pages, "artifacts": assets, "bytes": bytes_total}
