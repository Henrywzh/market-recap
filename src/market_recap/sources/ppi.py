"""Official dated BLS PPI final-demand release; no inferred effects or weights."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re

from lxml import html

from .. import cache
from ..util import utc_now_iso
from .cpi import MONTHS, _text, release_time
from .http import get_text

LATEST_URL = "https://www.bls.gov/news.release/ppi.nr0.htm"
ARCHIVE_URL = "https://www.bls.gov/news.release/archives/ppi_{stamp}.htm"


def _number(value: str) -> float | None:
    text = re.sub(r"\(\s*[pr]\s*\)", "", value, flags=re.I).replace(",", "").strip()
    return float(text) if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text) else None


def parse(text: str, *, expected_release: datetime | None = None) -> dict:
    doc = html.fromstring(text)
    published = release_time(_text(doc))
    if expected_release and published != expected_release:
        raise ValueError("BLS PPI archive answered with a different publication date")
    tables = doc.xpath('//table[@id="ppi_nrtable1"]')
    if len(tables) != 1:
        raise ValueError("BLS PPI Table 1 missing or ambiguous")
    table = tables[0]
    caption = _text(table.xpath('./caption')[0])
    match = re.search(r"\[(\w+) (\d{4})\]", caption)
    if not match or match[1].lower() not in MONTHS:
        raise ValueError("BLS PPI reference month missing")
    month = f"{match[2]}-{MONTHS[match[1].lower()]:02d}"
    head = _text(table.xpath('./thead')[0])
    if not all(s in head for s in ("Relative Importance", "Unadjusted 12-month percent change",
                                   "Seasonally adjusted 1-month percent change")):
        raise ValueError("BLS PPI Table 1 schema changed")
    weight = re.search(r"Relative Importance (\w+)\.? (\d{4})", head)
    if not weight:
        raise ValueError("BLS PPI weight month missing")
    number = next((i for m, i in MONTHS.items() if m[:3] == weight[1].lower()[:3]), None)
    if number is None:
        raise ValueError("BLS PPI weight month unrecognized")
    weight_month = f"{weight[2]}-{number:02d}"
    if weight_month >= month:
        raise ValueError("BLS PPI weight month is not before reference month")
    rows = {}
    for tr in table.xpath('./tbody/tr'):
        cells = tr.xpath('./th|./td')
        if len(cells) < 3 or any(int(c.get('colspan', '1')) > 1 for c in cells):
            continue
        values = [_text(c) for c in cells]
        if values[1] != 'FD':
            continue  # Intermediate demand is not the final-demand denominator.
        if len(values) != 10:
            raise ValueError("BLS PPI final-demand row schema changed")
        key = f"{values[1]}:{values[2]}"
        if key in rows:
            raise ValueError(f"Duplicate BLS PPI code: {key}")
        nums = [_number(v) for v in values[3:]]
        label = re.sub(r"\s*\(\s*\d+\s*\)", "", values[0]).strip()
        if nums[0] is not None and not 0 <= nums[0] <= 100:
            raise ValueError(f"BLS PPI relative importance out of range: {key}")
        rows[key] = {"official_label": label, "weight_pct": nums[0], "yoy": nums[1],
                     "mom": nums[-1], "previous_mom": nums[-2], "effect_pp": None}
    for key in ('FD:4', 'FD:49104', 'FD:49116'):
        if key not in rows or any(rows[key][b] is None for b in ('mom', 'yoy')):
            raise ValueError(f"BLS PPI required release value missing: {key}")
    if rows['FD:4']['weight_pct'] != 100:
        raise ValueError("BLS PPI final-demand denominator is not 100")
    return {"month": month, "weight_month": weight_month,
            "published_at": published.isoformat(), "rows": rows}


def fetch_release() -> dict:
    latest = get_text(LATEST_URL, timeout=25, retries=1)
    published = release_time(_text(html.fromstring(latest)))
    if published > datetime.now(published.tzinfo):
        raise ValueError("BLS PPI publication is in the future")
    url = ARCHIVE_URL.format(stamp=published.strftime('%m%d%Y'))
    raw = cache.fetch_text('bls-ppi', published.strftime('%Y%m%d'),
                           lambda: get_text(url, timeout=25, retries=1),
                           kind='macro_series', suffix='.html')
    result = parse(raw, expected_release=published)
    fetched = cache.modified(cache.path_for('bls-ppi', published.strftime('%Y%m%d'), '.html'))
    result.update(source_url=url, retrieved_at=fetched.isoformat() if fetched else None,
                  checked_at=utc_now_iso(), sha256=hashlib.sha256(raw.encode()).hexdigest())
    return result
