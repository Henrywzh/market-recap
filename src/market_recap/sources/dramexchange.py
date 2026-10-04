"""Local archive of DRAMeXchange's public homepage spot tables.

The homepage shows the day's spot averages without a login. History and
contract prices redirect to the member site and are not requested. The
site's terms forbid republication, display, distribution and derivative
works, so this module is not imported by the build and its output stays
under data/private/, which is gitignored. Nothing here is rendered.
"""

from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
import re

from bs4 import BeautifulSoup

from ..config import REPO_ROOT, USER_AGENT
from ..util import utc_now_iso
from .http import get_text

HOME_URL = "https://www.dramexchange.com/"
ARCHIVE_DIR = REPO_ROOT / "data" / "private" / "dramexchange"
_HEADINGS = (
    ("DRAM Spot", "DRAM spot"),
    ("Module Spot", "Module spot"),
    ("NAND Flash Wafer", "NAND wafer"),
    ("Wafer Spot", "NAND wafer"),
    ("GDDR", "GDDR"),
    ("NAND Flash", "NAND spot"),
    ("Flash Spot", "NAND spot"),
    ("Memory Card", "Memory card"),
    ("SSD Street", "SSD street"),
    ("SSD", "SSD"),
)


def _number(text: str) -> float | None:
    cleaned = text.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        value = float(cleaned)
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def _heading(text: str) -> str | None:
    found = None
    for needle, label in _HEADINGS:
        at = text.rfind(needle)
        if at >= 0 and (found is None or at > found[0]):
            found = (at, label)
    return None if found is None else found[1]


def _section_from_items(items: list[str]) -> str:
    text = " ".join(items).upper()
    if "GDDR" in text:
        return "GDDR"
    if "MICROS" in text or "SDXC" in text or "SDHC" in text:
        return "Memory card"
    if "TLC" in text or "QLC" in text or "WAFER" in text:
        return "NAND wafer"
    if "UDIMM" in text or "RDIMM" in text or "SODIMM" in text:
        return "Module spot"
    if "SLC" in text or "MLC" in text or "NAND" in text:
        return "NAND spot"
    if "DDR" in text or "DRAM" in text:
        return "DRAM spot"
    return "Other"


def _updated(text: str) -> str | None:
    matches = re.findall(r"Last\s*Update:\s*([^<]*?\(GMT[^)]*\))", text, re.IGNORECASE)
    return " ".join(matches[-1].split()) if matches else None


def parse_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for table in soup.find_all("table"):
        # Wrapper tables must not consume or duplicate their nested price rows.
        rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False)]
                for row in table.find_all("tr") if row.find_parent("table") is table]
        header = next((row for row in rows if "Session Average" in row or "Avg." in row), None)
        if header is None:
            continue
        columns = {name: i for i, name in enumerate(header)}
        street = "Avg." in columns
        avg_at = columns["Avg." if street else "Session Average"]
        chg_at = next((i for name, i in columns.items() if "Change" in name), None)
        item_at = next((i for name, i in columns.items() if name == "Item"), 0)
        parsed = []
        for row in rows:
            if row is header or len(row) <= item_at:
                continue
            item = row[item_at].strip()
            if not item or item in {"Item", "Brand"}:
                continue
            values = {}
            for name, i in columns.items():
                if not name or name in {"Item", "History"} or i >= len(row):
                    continue
                number = _number(row[i])
                if number is not None:
                    values[name] = number
            if avg_at >= len(row):
                continue
            average = _number(row[avg_at])
            change = _number(row[chg_at]) if chg_at is not None and chg_at < len(row) else None
            entry = {"item": " · ".join(row[:avg_at - 2]) if street else item,
                     "average": average, "change_pct": change, "values": values}
            if not street:
                entry.update(session_average=average, session_change_pct=change)
            parsed.append(entry)
        if not parsed:
            continue
        preceding, size = [], 0
        for node in table.find_all_previous(string=True):
            if node.parent.name in {"script", "style"}:
                continue
            piece = str(node).strip()
            if piece:
                preceding.append(piece)
                size += len(piece)
            if size > 2500:
                break
        before = " ".join(reversed(preceding))
        updated = _updated(table.get_text(" ", strip=True)) or _updated(before)
        label = "SSD street" if street else _heading(before) or _section_from_items([row["item"] for row in parsed])
        tables.append({"section": label, "updated": updated, "rows": parsed})
    return tables


def fetch_homepage() -> str:
    """The public homepage only, with this project's own User-Agent."""
    return get_text(HOME_URL, user_agent=USER_AGENT, retries=2, timeout=60.0)


def archive(html: str, day: date) -> Path:
    tables = parse_tables(html)
    if not tables:
        raise RuntimeError("DRAMeXchange homepage had no session-average tables")
    payload = {
        "source": HOME_URL,
        "fetched_at": utc_now_iso(),
        "archive_date": day.isoformat(),
        "tables": tables,
        "note": "Local archive only. Not for the public site.",
    }
    root = ARCHIVE_DIR / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day.isoformat()}.json"
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(body + chr(10), encoding="utf-8")
    temporary.replace(path)
    latest = ARCHIVE_DIR / "latest.json"
    latest_temporary = latest.with_suffix(".json.part")
    latest_temporary.write_text(body + chr(10), encoding="utf-8")
    latest_temporary.replace(latest)
    return path
