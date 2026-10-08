"""One on-disk cache for every upstream feed.

Before this module each source hand-rolled its own "is the file recent enough"
block, and they disagreed: some compared mtime against a ``timedelta``, some
encoded the date into the filename, and the lifetimes were invented per module
(12 hours here, 7 days there) with no statement of why. Three consequences,
all of them real:

* a date-stamped filename never expires, it only accumulates -- the cache had
  grown to 498 MB of files no build would ever read again;
* the same class of data was refreshed on different schedules depending on
  which vendor happened to serve it;
* a 404 was remembered in one module and re-probed on every build in another.

So the lifetime now comes from :data:`market_recap.config.CACHE_TTL`, keyed by
what the data *is*, and pruning is part of the build rather than something a
human is expected to remember.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from .config import CACHE_DIR, CACHE_TTL, MARKET_TIMEZONE, SESSION_KINDS, SESSION_ROLLOVER
from .sources.http import FetchError

MISSING_SUFFIX = ".missing"
GZIP_SUFFIX = ".gz"


def ttl(kind: str) -> timedelta:
    """Lifetime for a cache kind. Unknown kinds raise rather than defaulting:
    a typo silently meaning "one week" is how caches go stale unnoticed."""
    if kind not in CACHE_TTL:
        raise KeyError(f"unknown cache kind {kind!r}; known: {', '.join(CACHE_TTL)}")
    return CACHE_TTL[kind]


def path_for(namespace: str, name: str, suffix: str = "") -> Path:
    return CACHE_DIR / namespace / f"{name}{suffix}"


def modified(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def last_rollover(now: datetime | None = None) -> datetime:
    """The most recent weekday SESSION_ROLLOVER in New York at or before ``now``.

    Holidays are not modelled: on one, the rollover still passes and the next
    build re-fetches a file that has not changed. That costs a request, never a
    stale page, which is the direction to be wrong in.
    """
    market = ZoneInfo(MARKET_TIMEZONE)
    now = (now or datetime.now(timezone.utc)).astimezone(market)
    day = now.date()
    while True:
        candidate = datetime.combine(day, SESSION_ROLLOVER, tzinfo=market)
        if candidate <= now and candidate.weekday() < 5:
            return candidate
        day -= timedelta(days=1)


def is_fresh(path: Path, kind: str, *, now: datetime | None = None) -> bool:
    modified_at = modified(path)
    if modified_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now - modified_at >= ttl(kind):
        return False
    return kind not in SESSION_KINDS or modified_at >= last_rollover(now)


def _write(path: Path, payload: bytes, *, compress: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: a build interrupted mid-download must not leave a
    # truncated file that the next build reads as a complete one.
    temporary = path.with_suffix(path.suffix + ".part")
    if compress:
        # mtime=0 so the same bytes produce the same file: the gzip header
        # otherwise embeds a timestamp and every cache entry looks changed.
        with gzip.GzipFile(temporary, "wb", compresslevel=6, mtime=0) as handle:
            handle.write(payload)
    else:
        temporary.write_bytes(payload)
    temporary.replace(path)


def _read(path: Path, *, compress: bool) -> bytes:
    if compress:
        with gzip.open(path, "rb") as handle:
            return handle.read()
    return path.read_bytes()


def fetch_bytes(
    namespace: str,
    name: str,
    fetch: Callable[[], bytes],
    *,
    kind: str,
    suffix: str = ".bin",
    use_cache: bool = True,
    remember_missing: bool = False,
    compress: bool = False,
) -> bytes:
    """Return cached bytes if they are within their lifetime, else fetch.

    ``remember_missing`` turns a 404 into a marker file honoured for
    ``CACHE_TTL["missing"]``. Whether an issuer publishes an optional file is a
    property of the fund rather than of today, and re-probing every miss on
    every build cost more than every successful fetch put together.

    ``compress`` stores the response gzipped. Use it for large text documents
    kept only so the parse can be redone: SEC company facts are 3-4 MB of JSON
    each and 121 of them filled 472 MB, which compresses to roughly 30 MB. The
    raw document is still what is stored, so nothing about reproducibility
    changes -- only how much disk a scheduled job quietly consumes.
    """
    path = path_for(namespace, name, suffix + (GZIP_SUFFIX if compress else ""))
    if use_cache and is_fresh(path, kind):
        try:
            return _read(path, compress=compress)
        except (OSError, EOFError):
            pass  # A truncated entry is a reason to refetch, not to fail.

    marker = path_for(namespace, name, suffix + MISSING_SUFFIX)
    if use_cache and remember_missing and is_fresh(marker, "missing"):
        raise FetchError(f"{namespace}/{name}: not published (cached)", not_found=True)

    try:
        payload = fetch()
    except FetchError as exc:
        if remember_missing and exc.not_found:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(exc), encoding="utf-8")
        # A stale copy beats no copy when the publisher is briefly unreachable,
        # but the caller is told how old it is by the source record's own
        # observation date, which comes out of the file's contents.
        if path.exists() and not exc.not_found:
            try:
                return _read(path, compress=compress)
            except (OSError, EOFError):
                pass
        raise
    _write(path, payload, compress=compress)
    return payload


def fetch_text(namespace: str, name: str, fetch: Callable[[], str], **kwargs) -> str:
    suffix = kwargs.pop("suffix", ".txt")
    payload = fetch_bytes(
        namespace, name, lambda: fetch().encode("utf-8"), suffix=suffix, **kwargs
    )
    return payload.decode("utf-8", errors="replace")


def frame(
    namespace: str,
    name: str,
    build: Callable[[], pd.DataFrame],
    *,
    kind: str,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Cache a *parsed* frame, not just the bytes it came from.

    Re-reading a 5,700-row xlsx through openpyxl on every build cost more than
    downloading it did: 411 s cold against 27.7 s once the parsed frames were
    kept. Parquet round-trips the dtypes, so this is a cache of the result
    rather than a second parse of the same input.
    """
    path = path_for(namespace, name, ".parquet")
    if use_cache and is_fresh(path, kind):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass  # A corrupt cache entry is a reason to refetch, not to fail.
    result = build()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(path)
    except Exception:
        pass  # Caching is an optimisation; failing to cache is not a build error.
    return result


def prune(*, keep: timedelta | None = None) -> dict[str, int]:
    """Delete cache entries older than the longest lifetime any kind declares.

    Called from the build. A cache that only grows is not a cache, and the one
    thing nobody does on a scheduled job is log in to clear disk.
    """
    horizon = keep or max(CACHE_TTL.values())
    removed = bytes_freed = 0
    if not CACHE_DIR.exists():
        return {"files_removed": 0, "bytes_freed": 0}
    cutoff = datetime.now() - horizon
    for path in CACHE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
            continue
        size = path.stat().st_size
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        bytes_freed += size
    return {"files_removed": removed, "bytes_freed": bytes_freed}
