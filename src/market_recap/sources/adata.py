"""ADATA Industrial's monthly Memory & Flash Market Watch.

A memory-module maker's monthly note on DRAM and NAND: a one-line headline
(the page's meta description, with the figures it leads on) and, in fixed
sections, its read of supply sufficiency and the price trend for NAND and
for DRAM. The charts on the page are images and are not read here. This is a
supplier's view, quoted as written, not a price series.

Published early in the month at ``MarketWatch_YYYYMM``; a past month never
changes and is cached as an archive, the current month is re-read daily until
it appears.
"""

from __future__ import annotations

from datetime import date
import re

from bs4 import BeautifulSoup

from .. import cache
from .http import FetchError, get_text

PAGE_URL = "https://industrial.adata.com/en/edm/MarketWatch_{month}"
NAMESPACE = "adata"
_END = ("e-Catalog", "Contact Sales", "Subscription", "Insights\nView all")


def _between(text: str, start: str, end: str | None) -> str | None:
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i) if end else -1
    return re.sub(r"\s+", " ", text[i: j if j >= 0 else None]).strip(" :.") or None


def _block(text: str, pattern: str, until: list[str]) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    rest = text[match.end():]
    cut = min([k for k in (rest.find(u) for u in until) if k >= 0], default=len(rest))
    return rest[:cut]


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": "description"})
    headline = (meta.get("content") or "").strip() if meta else ""
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    nand = _block(text, r"NAND Price Trend\s*&\s*Sufficiency Ratio", ["Price Trend & Sufficiency Ratio\n", *_END])
    dram = _block(text, r"DDR\d Price Trend\s*&\s*Sufficiency Ratio", list(_END))
    # The NAND block stops at the DDR heading's "Price Trend & Sufficiency
    # Ratio"; the years and "DDR5" in front of it are dropped here.
    if nand:
        nand = re.sub(r"[\d\s\u2013-]*DDR\d\s*$", "", nand.rstrip())
    out = {"headline": headline or None}
    for key, block in (("nand", nand), ("dram", dram)):
        out[f"{key}_sufficiency"] = _between(block, "Sufficiency", "Price Trend") if block else None
        out[f"{key}_price"] = _between(block, "Price Trend", None) if block else None
    out["figures"] = re.findall(r"[+-]?\d+(?:\.\d+)?%", headline)
    return out


def fetch_month(month: str, *, current: bool, use_cache: bool = True) -> dict | None:
    """One month's note, or None when the page does not exist (yet)."""
    key = month.replace("-", "")
    url = PAGE_URL.format(month=key)
    try:
        html = cache.fetch_text(NAMESPACE, key, lambda: get_text(url, user_agent="Mozilla/5.0", retries=1),
                                kind="daily_file" if current else "archive", suffix=".html",
                                use_cache=use_cache, remember_missing=not current)
    except FetchError:
        return None
    parsed = parse(html)
    if not any(parsed[k] for k in ("headline", "nand_price", "dram_price")):
        return None
    return {"month": month, "url": url, **parsed}


def fetch_recent(today: date, months: int = 6, *, use_cache: bool = True) -> list[dict]:
    """The last ``months`` notes, newest first."""
    out, year, month = [], today.year, today.month
    for k in range(months):
        label = f"{year:04d}-{month:02d}"
        note = fetch_month(label, current=k == 0, use_cache=use_cache)
        if note:
            out.append(note)
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out
