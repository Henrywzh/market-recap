"""OFR Hedge Fund Monitor: SEC Form PF aggregates for qualifying hedge funds.

The Office of Financial Research publishes the Form PF statistics as one
keyless JSON dataset (``series/dataset?dataset=fpf``). One request carries
every series' observations and its own metadata (description, unit, last
update), so the units printed on the page come from the source rather than
from this file.

The data are the *current vintage*: the OFR's own metadata reads "Current
vintage, as of last update". A quarter is revised when a later filing round
restates it, so these values are never a point-in-time model input.

The endpoint answers gzip-encoded bodies whatever the request asks for, so
the bytes are decoded here by their magic number, not by trusting headers.
"""

from __future__ import annotations

import gzip
import json

from .. import cache
from .http import FetchError, get_bytes

NAMESPACE = "ofr"
BASE_URL = "https://data.financialresearch.gov/hf/v1"
DATASET = "fpf"
DATASET_URL = f"{BASE_URL}/series/dataset?dataset={DATASET}"
HOME_URL = "https://www.financialresearch.gov/hedge-fund-monitor/"
GZIP_MAGIC = b"\x1f\x8b"


def _decoded(raw: bytes) -> bytes:
    return gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw


def _dataset_bytes(url: str) -> bytes:
    """The dataset body, checked before it is cached: a 200 that is not the
    dataset (a maintenance page, an error object) must never replace a good copy."""
    body = _decoded(get_bytes(url, headers={"Accept-Encoding": "gzip"}, timeout=60.0))
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FetchError(f"{url}: not JSON ({exc})") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("timeseries"), dict):
        message = parsed.get("message", "no timeseries in response") if isinstance(parsed, dict) else "not an object"
        raise FetchError(f"{url}: {message}")
    return body


def fetch_dataset(*, use_cache: bool = True) -> dict:
    """The Form PF dataset as parsed JSON: {"short_name", "long_name", "timeseries": {mnemonic: {...}}}.

    Cached as the decoded JSON under the macro-series lifetime: OFR updates the
    dataset at most once a day, so an hourly build would re-download a megabyte
    for nothing.
    """
    body = cache.fetch_bytes(
        NAMESPACE,
        DATASET,
        lambda: _dataset_bytes(DATASET_URL),
        kind="macro_series",
        suffix=".json",
        use_cache=use_cache,
    )
    return json.loads(body)
