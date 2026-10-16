"""Official BLS CPI release tables, never model output or a FRED first print.

Discover the dated release from BLS itself, then read its tables together so
Table 1 and Table 6 cannot silently belong to different reference months.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
from zoneinfo import ZoneInfo

from lxml import html

from .. import cache
from ..util import utc_now_iso
from .http import get_text

LATEST_URL = "https://www.bls.gov/news.release/cpi.nr0.htm"
ARCHIVE_URL = "https://www.bls.gov/news.release/archives/cpi_{stamp}.htm"
MONTHS = {name.lower(): i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}


def _text(node) -> str:
    return re.sub(r"\s+", " ", " ".join(node.xpath(".//text()[not(ancestor::sup)]"))).strip()


def _number(value: str) -> float | None:
    value = re.sub(r"\(r\)", "", value).replace(",", "").strip()
    return float(value) if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value) else None


def release_time(text: str) -> datetime:
    # BLS publishes a local Eastern time, not a fixed UTC hour (DST matters).
    match = re.search(
        r"(\d{1,2}):(\d{2})\s*([ap])\.m\.\s*\(ET\)\s+\w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})",
        re.sub(r"\s+", " ", text), re.I,
    )
    if not match:
        raise ValueError("BLS CPI publication time not found")
    hour, minute, ampm, month, day, year = match.groups()
    return datetime(int(year), MONTHS[month.lower()], int(day),
                    int(hour) % 12 + (12 if ampm.lower() == "p" else 0), int(minute),
                    tzinfo=ZoneInfo("America/New_York"))


def _table(doc, identifier: str):
    tables = doc.xpath(f'//table[@id="{identifier}"]')
    if len(tables) != 1:
        raise ValueError(f"BLS CPI table missing or ambiguous: {identifier}")
    table = tables[0]
    caption = _text(table.xpath("./caption")[0])
    match = re.search(r", (\w+) (\d{4})(?:,|\s*\[|$)", caption)
    if not match or match[1].lower() not in MONTHS:
        raise ValueError(f"BLS CPI reference month not found: {caption}")
    month = f"{match[2]}-{MONTHS[match[1].lower()]:02d}"
    rows = {}
    for row in table.xpath("./tbody/tr"):
        cells = row.xpath("./th|./td")
        if len(cells) < 2:
            continue
        if any(int(c.get("colspan", "1")) > 1 for c in cells):
            continue  # Section headings, not measurements.
        label = re.sub(r"\s*\(\s*\d+\s*\)", "", _text(cells[0])).strip()
        if label in rows:
            raise ValueError(f"Duplicate BLS CPI category: {label}")
        rows[label] = [_number(_text(c)) for c in cells[1:]]
    return table, month, rows


def parse(text: str, *, expected_release: datetime | None = None) -> dict:
    doc = html.fromstring(text)
    published = release_time(_text(doc))
    if expected_release and published != expected_release:
        raise ValueError("BLS archive answered with a different publication date")
    t1, month, values = _table(doc, "cpipress1")
    t6, effect_month, effects = _table(doc, "cpipress6")
    if month != effect_month:
        raise ValueError("BLS CPI Table 1 / Table 6 reference months disagree")
    head1, head6 = _text(t1.xpath("./thead")[0]), _text(t6.xpath("./thead")[0])
    if not all(s in head1 for s in ("Unadjusted percent change", "Seasonally adjusted percent change")):
        raise ValueError("BLS CPI Table 1 schema changed")
    if "Seasonally adjusted effect on All Items" not in head6:
        raise ValueError("BLS CPI Table 6 effect schema changed")
    weight_match = re.search(r"Relative importance\s+(\w+)\.?\s+(\d{4})", head6)
    if not weight_match or weight_match[1].lower()[:3] not in {m[:3] for m in MONTHS}:
        raise ValueError("BLS CPI weight reference month not found")
    weight_number = next(i for m, i in MONTHS.items() if m[:3] == weight_match[1].lower()[:3])
    weight_month = f"{weight_match[2]}-{weight_number:02d}"
    expected_weight = datetime.strptime(month, "%Y-%m")
    prior = f"{expected_weight.year - (expected_weight.month == 1)}-{(expected_weight.month - 2) % 12 + 1:02d}"
    if weight_month != prior:
        raise ValueError("BLS CPI weights do not refer to the preceding month")
    rows = {}
    for label, row in effects.items():
        if len(row) != 6:
            raise ValueError(f"BLS CPI Table 6 row schema changed: {label}")
        original = values.get(label)
        if original is not None and len(original) != 9:
            raise ValueError(f"BLS CPI Table 1 row schema changed: {label}")
        rows[label] = {
            "weight_pct": row[0], "mom": row[1], "effect_pp": row[2],
            "standard_error": row[3],
            "yoy": original[4] if original else None,
            "previous_mom": original[7] if original else None,
        }
    for key in ("All items", "All items less food and energy"):
        if key not in rows or rows[key]["mom"] is None or rows[key]["yoy"] is None:
            raise ValueError(f"BLS CPI required release figure missing: {key}")
    return {"month": month, "weight_month": weight_month,
            "published_at": published.isoformat(), "rows": rows}


def fetch_release() -> dict:
    # Always discover afresh on a build: a 12h cache may span an 08:30 release.
    latest = get_text(LATEST_URL, timeout=25, retries=1)
    published = release_time(_text(html.fromstring(latest)))
    if published > datetime.now(published.tzinfo):
        raise ValueError("BLS CPI publication is in the future")
    url = ARCHIVE_URL.format(stamp=published.strftime("%m%d%Y"))
    raw = cache.fetch_text("bls-cpi", published.strftime("%Y%m%d"),
                           lambda: get_text(url, timeout=25, retries=1),
                           kind="macro_series", suffix=".html")
    result = parse(raw, expected_release=published)
    fetched = cache.modified(cache.path_for('bls-cpi', published.strftime('%Y%m%d'), '.html'))
    result.update(source_url=url, retrieved_at=fetched.isoformat() if fetched else None, checked_at=utc_now_iso(),
                  sha256=hashlib.sha256(raw.encode()).hexdigest())
    return result
