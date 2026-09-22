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


class FetchError(RuntimeError):
    pass


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
        args = [
            _CURL, "-sSL", "--http1.1", "--max-time", str(int(timeout)), "--fail",
            "--retry", str(retries), "--retry-delay", "10", "--retry-all-errors",
        ]
        for key, value in merged.items():
            args += ["-H", f"{key}: {value}"]
        args.append(url)
        result = subprocess.run(args, capture_output=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout
        curl_error = result.stderr.decode(errors="replace").strip()
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
