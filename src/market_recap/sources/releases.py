"""Earnings press releases (8-K Item 2.02, Exhibit 99.1) from EDGAR.

Some figures a theme needs are in the release and nowhere in XBRL company
facts: segment revenue (facts carry no dimensions) and management's outlook.
The release is found through the filing index's document types, read as
text, and searched with patterns; what matched is quoted, never paraphrased.

A filed release never changes and is cached as an archive.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import cache
from . import sec

ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
NAMESPACE = "sec/releases"
# A sentence ends at a full stop that follows a letter, a percent or a
# bracket -- not at the point inside "$89.0 billion".
_SENTENCE = re.compile(r"(?<=[A-Za-z%)\]])\.\s+(?=[A-Z•(])")
GUIDANCE = re.compile(r"capital expenditures|capex", re.I)
FORWARD = re.compile(r"\b(expect|anticipate|outlook|guidance|forecast|plan to|will be in the range|range of)\w*", re.I)
# Definitions and non-GAAP boilerplate mention expected capex without stating any.
BOILERPLATE = re.compile(r"supplemental|useful because|non-GAAP|we define|is defined|forward-looking statements", re.I)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()


def _exhibit(cik: int, accession: str) -> tuple[str, str] | None:
    """(url, text) of the filing's EX-99.1."""
    acc = accession.replace("-", "")
    base = ARCHIVE.format(cik=cik, acc=acc)
    index = cache.fetch_text(NAMESPACE, f"{acc}-index", lambda: sec._get(f"{base}{accession}-index.html", 30.0),
                             kind="archive", suffix=".html")
    soup = BeautifulSoup(index, "html.parser")
    for tr in soup.select("table.tableFile tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        link = tr.find("a")
        if len(cells) > 3 and cells[3].upper().startswith("EX-99.1") and link and link.get("href"):
            url = "https://www.sec.gov" + link["href"]
            html = cache.fetch_text(NAMESPACE, f"{acc}-ex991", lambda: sec._get(url, 30.0), kind="archive", suffix=".html")
            return url, _text(html)
    return None


def recent(cik: int, count: int) -> list[dict]:
    """The last ``count`` earnings releases: filing date, url and text, newest first."""
    block = sec.submissions_recent(cik)
    out = []
    for i, form in enumerate(block.get("form") or []):
        if form != "8-K" or "2.02" not in str((block.get("items") or [""])[i] or ""):
            continue
        found = _exhibit(cik, block["accessionNumber"][i])
        if found:
            out.append({"filed": block["filingDate"][i], "url": found[0], "text": found[1]})
        if len(out) >= count:
            break
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def guidance(text: str) -> list[str]:
    """Forward-looking sentences about capital expenditures, as written.
    Tables are skipped: a sentence full of figures is a table row, not a statement."""
    out = []
    for s in sentences(text):
        digits = sum(ch.isdigit() for ch in s)
        if (GUIDANCE.search(s) and FORWARD.search(s) and not BOILERPLATE.search(s)
                and len(s) < 400 and digits < 0.15 * len(s)):
            out.append(s if s.endswith(".") else s + ".")
    return out


def first(pattern: str, text: str) -> tuple[str, ...] | None:
    m = re.search(pattern, text, re.I)
    return m.groups() if m else None
