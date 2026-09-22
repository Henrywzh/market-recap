"""One HTTP entry point for every upstream feed.

Some publishers (FRED behind Akamai, notably) gate on TLS fingerprint rather
than on headers: the exact same request succeeds from ``curl`` and times out
from Python's TLS stack. Routing every fetch through curl first, with httpx as
the fallback, keeps those feeds working without adding a scraping dependency
and without pretending to be a browser beyond a plain User-Agent.
"""

from __future__ import annotations

import shutil
import subprocess

import httpx

from ..config import USER_AGENT

_CURL = shutil.which("curl")

# Seconds between curl's own retries. Long enough that a short IP throttle has
# cleared, short enough that four of them fit inside one build.
RETRY_DELAY_SECONDS = 5
# Statuses that mean "this will never exist", as opposed to "try again later".
# 410 Gone is as final as 404; a 403 is not -- some publishers answer 403 while
# rate-limiting, and caching that as permanent would drop a live feed.
NOT_FOUND_STATUSES = frozenset({404, 410})
_STATUS_PREFIX = "market-recap-status:"


def _status_from(stderr: str) -> int | None:
    for line in reversed(stderr.splitlines()):
        if line.startswith(_STATUS_PREFIX):
            try:
                return int(line[len(_STATUS_PREFIX):].strip())
            except ValueError:
                return None
    return None


class FetchError(RuntimeError):
    """A fetch that failed. ``not_found`` separates 'never will exist' from
    'try again later', so a caller probing for an optional file can cache the
    absence instead of re-asking every build."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


def get_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
    user_agent: str | None = None,
    retries: int = 4,
) -> bytes:
    merged = {"User-Agent": user_agent or USER_AGENT}
    merged.update(headers or {})

    if _CURL:
        # HTTP/1.1 is forced deliberately: FRED's edge intermittently aborts an
        # HTTP/2 stream mid-response ("stream not closed cleanly"), which curl
        # surfaces as a hard failure rather than a retryable status. The retry
        # backoff covers the short IP throttles the same edge applies to a
        # build that fetches a dozen series in a row.
        # --retry without --retry-all-errors: curl then retries timeouts and
        # transient 5xx/408/429 but treats a 404 as final. Retrying a 404 is
        # never useful -- it is the server stating the file does not exist --
        # and probing a list of funds for an optional file turned into minutes
        # of dead waiting when every miss was retried four times.
        # %{stderr} sends what follows to stderr, so the status code arrives
        # out of band and the body on stdout stays exactly what the server
        # sent. Reading the code this way rather than looking for "404" in an
        # error message is the difference between a fact and a coincidence: a
        # URL containing "404" would otherwise be permanently negative-cached.
        args = [
            _CURL, "-sSL", "--http1.1", "--max-time", str(int(timeout)), "--fail",
            "--retry", str(retries), "--retry-delay", str(RETRY_DELAY_SECONDS),
            "--write-out", "%{stderr}\n" + _STATUS_PREFIX + "%{http_code}",
        ]
        for key, value in merged.items():
            args += ["-H", f"{key}: {value}"]
        args.append(url)
        result = subprocess.run(args, capture_output=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout
        stderr = result.stderr.decode(errors="replace").strip()
        status = _status_from(stderr)
        curl_error = "\n".join(
            line for line in stderr.splitlines() if not line.startswith(_STATUS_PREFIX)
        ).strip()
        if status in NOT_FOUND_STATUSES:
            raise FetchError(f"{url}: not found ({status})", not_found=True)
    else:
        curl_error = "curl not available"

    try:
        response = httpx.get(url, headers=merged, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except Exception as exc:
        raise FetchError(f"{url}: curl failed ({curl_error}); httpx failed ({exc})") from exc


def get_text(url: str, **kwargs) -> str:
    return get_bytes(url, **kwargs).decode("utf-8", errors="replace")
