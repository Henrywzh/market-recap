"""Korea's monthly trade release (the 1st-of-month "수출입 동향").

The Ministry of Trade, Industry and Resources publishes the previous month's
exports on the first day of the month -- about two weeks before customs
confirms them -- with semiconductor exports as its lead item. The press
release page carries no figures; they are in the attached PDF, whose first six
pages are read with ``pdftotext`` (poppler), installed by the workflow.

Read per month: the release time, total exports and semiconductor exports
(US$ hundred-million, "억 달러") with their year-on-year change. A published
release never changes and is cached as an archive.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import re
import shutil
import subprocess
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import cache
from .http import get_bytes, get_text

# The ministry's server answers in seconds a page, 8 list pages and up to 13 releases a
# build, and was waited on one request at a time (190 s on a slow night). A few at a
# time, not many: it drops the odd request from a cloud runner as it is.
WORKERS = 3
BASE = "https://www.motir.go.kr"
LIST_URL = BASE + "/kor/article/ATCL3f49a5a8c"
NAMESPACE = "motie"
UA = "Mozilla/5.0"
_TITLE = re.compile(r"^(\d{4})년\s*(?:(?:상|하)반기\s*및\s*|연간\s*및\s*)?(\d{1,2})월\s*(?:및\s*(?:상|하)반기\s*)?수출입\s*동향$")
# The chip line has been written four ways; each rule yields (US$ 억, y/y %):
#   2026   "반도체 수출(466.5억 달러, +209.0%)"
#   2025H1 "반도체 수출은 101억 달러(+8.1%)"
#   2025H2 "반도체 수출은 25.4% 증가한 157.3억 달러로"
#   list   "수출증가품목(억 달러, %) : 반도체166.1(+22.0)", "증가품목 수출액·증감률(억 달러, %) : 반도체 151.0(+27.1)"
_AMOUNT, _PCT = r"([\d,.]+)", r"([+△-]?\s*[\d,.]+)"
_SEMIS = (
    (re.compile(rf"반도체\s*수출\s*\(\s*{_AMOUNT}\s*억\s*달러\s*,\s*{_PCT}\s*%\s*\)"), lambda m: (m.group(1), m.group(2))),
    (re.compile(rf"반도체\s*수출은\s*{_AMOUNT}\s*억\s*달러\s*\(\s*{_PCT}\s*%\s*\)"), lambda m: (m.group(1), m.group(2))),
    (re.compile(rf"반도체\s*수출은\s*{_PCT}\s*%\s*(증가|감소)한\s*{_AMOUNT}\s*억\s*달러"),
     lambda m: (m.group(3), ("-" if m.group(2) == "감소" else "") + m.group(1).lstrip("+"))),
    (re.compile(rf"품목[^:(]{{0,20}}\(억\s*달러,\s*%\)\s*:\s*반도체\s*{_AMOUNT}\s*\(\s*{_PCT}\s*\)"),
     lambda m: (m.group(1), m.group(2))),
)
_TOTAL = (
    (re.compile(r"\d{1,2}월\s*수출\s*([\d,.]+)\s*억\s*달러\s*\(\s*([+△-]?\s*[\d,.]+)\s*%\s*\)"), lambda m: (m.group(1), m.group(2))),
    (re.compile(r"\d{1,2}월\s*수출은\s*(?:전년\s*(?:동월\s*)?대비\s*)?([+△-]?\s*[\d,.]+)\s*%\s*(증가|감소)한\s*([\d,.]+)\s*억\s*달러"),
     lambda m: (m.group(3), ("-" if m.group(2) == "감소" else "") + m.group(1).lstrip("+"))),
)
_RELEASED = re.compile(r"보도시점\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.[^\d]*(\d{1,2}:\d{2})?")


def _num(text: str) -> float:
    text = text.replace(",", "").replace(" ", "")
    negative = text.startswith("△") or text.startswith("-")
    value = float(text.lstrip("△+-"))
    return -value if negative else value


def parse_text(text: str) -> dict:
    """Figures from the release's first pages (pdftotext output)."""
    out: dict = {}
    if m := _RELEASED.search(text):
        out["released"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out["released_time"] = m.group(4)
    for rule, pick in _TOTAL:
        if m := rule.search(text):
            amount, change = pick(m)
            out["total_bn"] = round(_num(amount) / 10, 2)
            out["total_yoy_pct"] = _num(change)
            break
    # The first chip figure that fits inside the month's exports: a June
    # release leads with the half-year (US$192bn) before the month (US$45bn).
    # The exact forms first (rule order), the rounded item list last.
    candidates = [pick(m) for rule, pick in _SEMIS for m in rule.finditer(text)]
    for amount, change in candidates:
        value = round(_num(amount) / 10, 2)                       # 억 달러 = US$100m
        if "total_bn" not in out or value <= out["total_bn"]:
            out["semis_bn"] = value
            out["semis_yoy_pct"] = _num(change)
            break
    return out


def releases(html: str) -> list[tuple[str, str]]:
    """(month 'YYYY-MM', article id) for every monthly trade release on a list page."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select('a[onclick*="article.view"]'):
        title = a.get_text(" ", strip=True)
        m = _TITLE.match(title)
        ident = re.search(r"'(\d+)'", a.get("onclick") or "")
        if m and ident:
            out.append((f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", ident.group(1)))
    return out


def _pdf_text(data: bytes) -> str:
    tool = shutil.which("pdftotext")
    if not tool:
        raise RuntimeError("pdftotext (poppler) is not installed")
    result = subprocess.run([tool, "-l", "6", "-", "-"], input=data, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {result.stderr.decode(errors='replace')[:120]}")
    return result.stdout.decode("utf-8", errors="replace")


def _article(ident: str, use_cache: bool) -> dict:
    view = cache.fetch_text(NAMESPACE, f"view-{ident}", lambda: get_text(f"{LIST_URL}/{ident}/view", user_agent=UA, retries=1),
                            kind="archive", suffix=".html", use_cache=use_cache)
    soup = BeautifulSoup(view, "html.parser")
    link = next((a for a in soup.find_all("a") if ".pdf" in a.get_text().lower() and a.get("href")), None)
    if link is None:
        raise RuntimeError(f"release {ident}: no PDF attached")
    pdf = cache.fetch_bytes(NAMESPACE, f"pdf-{ident}", lambda: get_bytes(BASE + link["href"], user_agent=UA, retries=1),
                            kind="archive", suffix=".pdf", use_cache=use_cache)
    return {"id": ident, "url": f"{LIST_URL}/{ident}/view", **parse_text(_pdf_text(pdf))}


def _list_page(keyword: str, page: int, use_cache: bool) -> tuple[str | None, str | None]:
    """(html, None), or (None, why) when the page could not be read."""
    # The ministry's server drops the odd request from a cloud runner
    # ("empty reply"); one list page lost costs its releases only.
    try:
        html = cache.fetch_text(
            NAMESPACE, f"list-{keyword.replace(' ', '_')}-{page}",
            lambda: get_text(f"{LIST_URL}?searchCondition=1&searchKeyword={quote(keyword)}&pageIndex={page}", user_agent=UA, retries=2),
            kind="daily_file", suffix=".html", use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        return None, f"list '{keyword}' page {page}: {str(exc)[:80]}"
    return html, None


def fetch(today: date, months: int = 13, *, use_cache: bool = True) -> tuple[list[dict], list[str]]:
    """Monthly releases, oldest first, and the months that could not be read."""
    found: dict[str, str] = {}
    pages_failed: list[str] = []
    asked = [(keyword, page) for keyword in ("수출입 동향", "수출입동향") for page in (1, 2, 3, 4)]
    with ThreadPoolExecutor(WORKERS) as pool:
        pages = list(pool.map(lambda kp: _list_page(kp[0], kp[1], use_cache), asked))
    # In the order asked, whatever finished first: the first page to name a month decides its release.
    for html, why in pages:
        if why:
            pages_failed.append(why)
            continue
        for month, ident in releases(html):
            found.setdefault(month, ident)
    if not found:
        raise RuntimeError("no list page could be read: " + "; ".join(pages_failed[:2]))
    # Each release states its own y/y change, so a year of releases is enough;
    # the site is slow (seconds a page, a 1.7 MB PDF each), and a published
    # release is cached for good once read.
    wanted = sorted(found.items())[-months:]

    def read(item: tuple[str, str]) -> tuple[dict | None, str | None]:
        month, ident = item
        try:
            return _article(ident, use_cache), None
        except Exception as exc:  # noqa: BLE001 - one unreadable release must not drop the rest
            return None, f"{month}: {str(exc)[:100]}"

    with ThreadPoolExecutor(WORKERS) as pool:
        articles = list(pool.map(read, wanted))
    rows, failed = [], list(pages_failed)
    for (month, _), (row, why) in zip(wanted, articles):
        if why:
            failed.append(why)
        elif "semis_bn" in row:
            rows.append({"month": month, **row})
        else:
            failed.append(f"{month}: semiconductor line not found")
    return rows, failed
