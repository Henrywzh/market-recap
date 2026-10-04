"""Earnings press releases (8-K Item 2.02, Exhibit 99.1) from EDGAR.

Some figures a theme needs are in the release and nowhere in XBRL company
facts: segment revenue (facts carry no dimensions) and management's outlook.
The release is found through the filing index's document types, read as
text, and searched with patterns; what matched is quoted, never paraphrased.

A filed release never changes and is cached as an archive.
"""

from __future__ import annotations

from datetime import date
import json
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


def _read_exhibit(cik: int, accession: str) -> tuple[str, str] | None:
    """(url, text) of the filing's EX-99.1, read from the filing's index page
    and the exhibit itself (each kept as fetched). Parses both documents."""
    acc = accession.replace("-", "")
    base = ARCHIVE.format(cik=cik, acc=acc)
    index = cache.fetch_text(NAMESPACE, f"{acc}-index", lambda: sec._get(f"{base}{accession}-index.html", 30.0),
                             kind="archive", suffix=".html")
    soup = BeautifulSoup(index, "html.parser")
    exhibits = []
    for tr in soup.select("table.tableFile tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        link = tr.find("a")
        if len(cells) > 3 and cells[3].upper().startswith("EX-99") and link and link.get("href"):
            exhibits.append((cells[3].upper(), "https://www.sec.gov" + link["href"]))
    # EX-99.1 where there is one; Texas Instruments files its release as EX-99.
    exhibits.sort(key=lambda e: (e[0] != "EX-99.1", e[0]))
    for _, url in exhibits[:1]:
        html = cache.fetch_text(NAMESPACE, f"{acc}-ex991", lambda: sec._get(url, 30.0), kind="archive", suffix=".html")
        return url, _text(html)
    return None


def _exhibit(cik: int, accession: str) -> tuple[str, str] | None:
    """(url, text) of the filing's EX-99.1.

    A filed release never changes, yet every build parsed the same index page
    and press release again: 2,351 BeautifulSoup runs over 8 million tags, most
    of an EVENTS build's CPU. What is kept is the answer -- the url and the
    extracted text, or that there is no exhibit -- so each filing is parsed once
    and read back thereafter."""
    acc = accession.replace("-", "")
    answer = cache.fetch_text(NAMESPACE, f"{acc}-exhibit",
                              lambda: json.dumps(_read_exhibit(cik, accession)),
                              kind="archive", suffix=".json", compress=True)
    found = json.loads(answer)
    return (found[0], found[1]) if found else None


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


# --- The outlook a release gives for the coming quarter --------------------------
# Three wordings cover most releases:
#   Micron  "Revenue $50.0 billion ± $1.0 billion", "EPS $30.73 ± $1.00 $31.00 ± $1.00"
#   common  "revenue between $4.20 billion and $4.40 billion"
#   NVIDIA  "Revenue is expected to be $108.0 billion, plus or minus 2%"
# Where a table gives GAAP and non-GAAP side by side, the last figure in the
# row is the non-GAAP one -- the basis Nasdaq's consensus EPS is on.
_SCALE = {"billion": 1e9, "million": 1e6, None: 1.0, "": 1.0}
_MONEY = r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million)?"
_OUTLOOK_AT = re.compile(r"business outlook|financial outlook|\boutlook\b|\bguidance\b|\btargets\b|expects?\b|expected to be", re.I)
_REVENUE = re.compile(r"\b(?:revenue|net sales|sales)s?\b", re.I)
_EPS = re.compile(r"(?:diluted )?(?:earnings|net income) per (?:diluted )?share|\bEPS\b", re.I)
_PLUS_MINUS = re.compile(rf"{_MONEY},?\s*(?:±|\+/-|plus or minus)\s*{_MONEY}", re.I)
_PLUS_MINUS_PCT = re.compile(rf"{_MONEY},?\s*(?:±|\+/-|plus or minus)\s*([\d.]+)\s*%", re.I)
_BETWEEN = re.compile(rf"(?:(?:between|range of|from)\s*)?{_MONEY}\s*(?:and|to|-|–)\s*{_MONEY}", re.I)
# A single figure: Broadcom's "revenue guidance of approximately $34.8 billion".
_POINT = re.compile(rf"(?:approximately|expected to be|guidance of)\s*{_MONEY}", re.I)
# Growth instead of a level: Oracle's "expected to grow between 30% and 34%".
_GROWTH = re.compile(r"(?:grow|growth|increase)\w*\s+(?:of\s+)?(?:between\s+)?([\d.]+)%\s*(?:and|to|-|–)\s*([\d.]+)%", re.I)
_PERIOD = re.compile(r"(?:first|second|third|fourth) (?:fiscal )?quarter(?: of (?:fiscal )?(?:year )?\d{4})?|\bQ[1-4](?: FY ?\d{2,4})?|FQ[1-4]-\d{2}|"
                     r"(?:full |fiscal )(?:fiscal )?year(?: \d{4})?|\bFY ?\d{2,4}", re.I)
_MARGIN = re.compile(r"gross margin[^%]{0,40}?(?:approximately\s+)?([\d.]+)\s*%(?:\s*(?:±|plus or minus)\s*([\d.]+)\s*%)?", re.I)
# How far after a label its figures may sit (a table row, or a sentence).
_ROW_CHARS = 160


def _amount(number: str, scale: str | None, fallback: str | None = None) -> float:
    return float(number.replace(",", "")) * _SCALE[(scale or fallback or "").lower() or None]


def _ranges(text: str) -> list[tuple[float, float]]:
    """Every (low, high) stated in ``text``, in order."""
    found = []
    for m in _PLUS_MINUS_PCT.finditer(text):
        mid = _amount(m.group(1), m.group(2))
        found.append((m.start(), mid * (1 - float(m.group(3)) / 100), mid * (1 + float(m.group(3)) / 100)))
    for m in _PLUS_MINUS.finditer(text):
        if any(abs(m.start() - start) < 3 for start, _, _ in found):
            continue
        mid, half = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4), m.group(2))
        found.append((m.start(), mid - half, mid + half))
    for m in _BETWEEN.finditer(text):
        if any(abs(m.start() - start) < 3 for start, _, _ in found):
            continue
        low, high = _amount(m.group(1), m.group(2), m.group(4)), _amount(m.group(3), m.group(4), m.group(2))
        if low <= high:
            found.append((m.start(), low, high))
    if not found:
        for m in _POINT.finditer(text):
            value = _amount(m.group(1), m.group(2))
            found.append((m.start(), value, value))
    return [(low, high) for _, low, high in sorted(found)]


def _after(label: re.Pattern, text: str, start: int) -> list[tuple[float, float]]:
    """The ranges after the first ``label`` from ``start`` that states any --
    a label in a sentence about something else ("revenue includes sales of
    customer service") is passed over."""
    others = (_REVENUE, _MARGIN) if label is _EPS else (_EPS, _MARGIN)
    for m in label.finditer(text, start):
        stretch = text[m.end():m.end() + _ROW_CHARS]
        # Stop at the next line item, so revenue does not take the EPS figure.
        stop = min([x.start() for x in (o.search(stretch) for o in others) if x] + [len(stretch)])
        found = _ranges(stretch[:stop])
        if found:
            return found
    return []


def outlook(text: str) -> dict | None:
    """Next-quarter revenue and EPS ranges and gross margin, as a release
    states them; None when it states none. Figures are read, never inferred:
    a release that guides only on the call has no outlook here."""
    for anchor in _OUTLOOK_AT.finditer(text):
        # A little before the anchor: "revenue guidance of" names the line first.
        begin = max(0, anchor.start() - 120)
        window = text[begin:anchor.start() + 1500]
        out: dict = {}
        at = anchor.start() - begin
        revenue = _after(_REVENUE, window, at) or _after(_REVENUE, window, 0)
        eps = _after(_EPS, window, at)
        if revenue and revenue[-1][1] > 1e6:          # a sales figure, not a per-share one
            out["revenue_low"], out["revenue_high"] = revenue[-1]
        elif (rev := _REVENUE.search(window)) and (g := _GROWTH.search(window, rev.end(), rev.end() + _ROW_CHARS)):
            out["revenue_growth_low"], out["revenue_growth_high"] = float(g.group(1)), float(g.group(2))
        if eps and eps[-1][1] < 1e4:                  # a per-share figure
            out["eps_low"], out["eps_high"] = eps[-1]
        if (m := _MARGIN.search(window, at)) and out:
            out["gross_margin_pct"] = float(m.group(1))
        if out:
            if period := _PERIOD.search(window, at):
                out["period"] = period.group(0)
            elif period := _PERIOD.search(window):
                out["period"] = period.group(0)
            out["quote"] = re.sub(r"\s+", " ", window[anchor.start() - begin:anchor.start() - begin + 400]).strip()
            return out
    return None


def release_on(cik: int, day: str, block: dict, *, tolerance_days: int = 1,
               fetch: bool = True) -> tuple[str, str, bool] | None:
    """(url, text, read for the first time) of the earnings release (8-K Item
    2.02) filed on ``day``, from a submissions block. None when there is none
    within the tolerance -- or when it is not cached and ``fetch`` is off."""
    target = date.fromisoformat(day)
    forms, items = block.get("form") or [], block.get("items") or []
    for i, form in enumerate(forms):
        if form != "8-K" or "2.02" not in str(items[i] if i < len(items) else ""):
            continue
        filed = date.fromisoformat(block["filingDate"][i])
        if abs((filed - target).days) > tolerance_days:
            continue
        acc = block["accessionNumber"][i]
        cached = cache.path_for(NAMESPACE, f"{acc.replace('-', '')}-index", ".html").exists()
        if not cached and not fetch:
            return None
        found = _exhibit(cik, acc)
        return (found[0], found[1], not cached) if found else None
    return None
