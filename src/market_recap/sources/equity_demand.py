"""Public demand inputs, with exact downloaded bytes and fetch provenance."""
from __future__ import annotations

import hashlib
from io import BytesIO, StringIO
import json
from zipfile import ZipFile

import pandas as pd

from .. import cache
from ..util import utc_now_iso
from .http import FetchError, get_bytes

NAMESPACE = "equity_demand"


def download(key: str, url: str, *, offline: bool = False, zip_member: str | None = None) -> tuple[str, dict]:
    """Offline reads never fetch. A fallback retains its original fetch timestamp."""
    path = cache.path_for(NAMESPACE, key, ".json")

    def fetch() -> bytes:
        body = get_bytes(url, timeout=60, retries=1)
        if zip_member:
            with ZipFile(BytesIO(body)) as archive:
                matches = [n for n in archive.namelist() if n.rsplit("/", 1)[-1].lower() == zip_member.lower()]
                if len(matches) != 1:
                    raise FetchError(f"{url}: expected one {zip_member}, found {len(matches)}")
                body = archive.read(matches[0])
        text = body.decode("utf-8-sig")
        if "<html" in text[:500].lower() or not text.strip():
            raise FetchError(f"{url}: expected data, received empty/HTML body")
        return json.dumps({"text": text, "source_url": url, "member": zip_member,
                           "fetched_at": utc_now_iso(), "sha256": hashlib.sha256(body).hexdigest()}).encode()

    if offline:
        if not path.exists():
            raise FileNotFoundError(f"no local demand input: {key}")
        envelope = json.loads(path.read_bytes())
    else:
        envelope = json.loads(cache.fetch_bytes(NAMESPACE, key, fetch, kind="macro_series", suffix=".json"))
    if envelope["source_url"] != url or envelope.get("member") != zip_member:
        raise ValueError(f"{key}: cached source differs from configuration")
    return envelope["text"], {k: v for k, v in envelope.items() if k != "text"}


def quarterly_table(text: str, *, first_quarter: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text), dtype=str)
    if "date" not in frame:
        raise ValueError("Fed table missing date column")
    frame = frame[frame.date.str.fullmatch(r"\d{4}:Q[1-4]", na=False)].copy()
    frame.index = pd.PeriodIndex(frame.pop("date").str.replace(":", "", regex=False), freq="Q")
    frame = frame.loc[frame.index >= pd.Period(first_quarter, freq="Q")]
    if frame.index.has_duplicates:
        raise ValueError("duplicate Fed quarter")
    return frame.apply(pd.to_numeric, errors="coerce").sort_index() / 1000.0


def tic_monthly(text: str, *, country_code: str, field: str) -> pd.DataFrame:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("country\tcountry_code\tdate\t")), None)
    if start is None:
        raise ValueError("TIC header not found")
    frame = pd.read_csv(StringIO("\n".join(lines[start:])), sep="\t", dtype=str)
    frame = frame[frame.country_code.eq(str(country_code))].copy()
    frame["value_bn"] = pd.to_numeric(frame[field], errors="coerce") / 1000.0
    frame = frame[frame.date.str.fullmatch(r"\d{4}-\d{2}", na=False)].sort_values("date")
    if frame.date.duplicated().any():
        raise ValueError("duplicate TIC Grand Total month; country subtotals must not be added")
    # Pre-2023-02 SLT transaction fields are absent, not reconstructed from holdings.
    return frame[["date", "value_bn"]].dropna(subset=["value_bn"])
