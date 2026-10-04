"""Probe FactSet's weekly Earnings Insight PDF for sector forward P/E.

Research tooling, not part of the build. The build reads the PDF's text for the
S&P 500's forward P/E and its averages, and skips the sector page because it is
"a chart image" (sources/factset.py). Before anyone writes a reader for it, this
answers four questions, measured from the machine that would run it:

1. How far back do the weekly PDFs exist? (one per Friday, ``--years`` back)
2. Which page carries the sector forward P/E, and is its text selectable or only
   pixels (``pdftotext`` per page; ``pdfimages -list`` for images on the page)?
3. If only pixels, does OCR (``tesseract``, when installed) return a sector name
   beside a number for at least ``EXTREMES_PER_WEEK`` sectors? (The first run found
   the page is text and names only four sectors a week: the two with the highest
   and the two with the lowest forward P/E.)
4. Do the numbers read back agree with each other between weeks (a sector's
   forward P/E should not move 30% in a week)? Sectors appear only in the weeks they
   are an extreme, so consecutive readings can be several weeks apart.

    python scripts/probe_factset_sector.py [--years 6] [--out data/probes/factset]

Writes ``summary.json`` (one record per week tried) and, for the newest PDF that
has a sector page, that page as a PNG and its text/OCR, so a person can look.
Nothing here touches the cache, the artifacts or the build. Needs poppler
(``pdftotext``, ``pdftoppm``, ``pdfimages``); tesseract is optional.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.sources import factset  # noqa: E402
from market_recap.sources.http import FetchError, get_bytes  # noqa: E402

SECTORS = ("Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials",
           "Health Care", "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities")
# A page is the sector page when it names this many sectors and talks of P/E.
MIN_SECTORS = 6
# A week-to-week move in one sector's forward P/E beyond this is a misread.
MAX_WEEKLY_MOVE = 0.30
# FactSet writes a sector's forward P/E as "Consumer Discretionary (22.6)", and
# the same page prints "(+27.6%)" target-price upsides and "(70%)" buy shares
# for the same sectors; only an unsigned one-decimal number straight after the
# name, in brackets, is a P/E.
NUMBER_AFTER_NAME = r"\s*\((\d{1,2}\.\d)\)"
# The sentence names the two highest and two lowest sectors, so four a week.
EXTREMES_PER_WEEK = 4


def run(cmd: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=data, capture_output=True, timeout=180)


def fridays(years: int, today: date) -> list[date]:
    day = today - timedelta(days=(today.weekday() - 4) % 7)
    out = []
    while day >= today - timedelta(days=365 * years):
        out.append(day)
        day -= timedelta(days=7)
    return out


def fetch_pdf(day: date) -> tuple[bytes | None, str]:
    """The PDF for a Friday, or the Thursday before it (a Friday holiday)."""
    reason = ""
    for candidate in (day, day - timedelta(days=1)):
        url = factset.PDF_URL.format(stamp=candidate.strftime("%m%d%y"))
        try:
            return get_bytes(url, user_agent=factset.USER_AGENT, timeout=60.0, retries=1), url
        except FetchError as exc:
            reason = f"{candidate}: {str(exc)[:80]}"
    return None, reason


def page_count(pdf: Path) -> int:
    info = run(["pdfinfo", str(pdf)]).stdout.decode(errors="replace")
    match = re.search(r"^Pages:\s+(\d+)", info, re.M)
    return int(match.group(1)) if match else 0


def page_text(pdf: Path, number: int) -> str:
    return run(["pdftotext", "-f", str(number), "-l", str(number), "-layout", str(pdf), "-"]).stdout.decode("utf-8", errors="replace")


def page_images(pdf: Path, number: int) -> int:
    lines = run(["pdfimages", "-list", "-f", str(number), "-l", str(number), str(pdf)]).stdout.decode(errors="replace").splitlines()
    return max(len(lines) - 2, 0)


def sectors_named(text: str) -> list[str]:
    return [s for s in SECTORS if s.lower() in text.lower()]


def read_pairs(text: str) -> dict[str, list[float]]:
    """{sector: [forward P/E]} for every sector written as ``Name (12.3)``.
    The text is flattened first: the sentence wraps lines mid-name."""
    flat = re.sub(r"\s+", " ", text)
    out: dict[str, list[float]] = {}
    for sector in SECTORS:
        found = [float(v) for v in re.findall(re.escape(sector) + NUMBER_AFTER_NAME, flat, re.I)]
        if found:
            out[sector] = found
    return out


def ocr(png: Path) -> str | None:
    if not shutil.which("tesseract"):
        return None
    return run(["tesseract", str(png), "-", "--psm", "6"]).stdout.decode("utf-8", errors="replace")


def probe_week(day: date, out_dir: Path, keep_page: bool) -> dict:
    record: dict = {"friday": day.isoformat()}
    data, detail = fetch_pdf(day)
    if data is None:
        return record | {"found": False, "detail": detail}
    pdf = out_dir / f"{day:%Y-%m-%d}.pdf"
    pdf.write_bytes(data)
    record |= {"found": True, "url": detail, "bytes": len(data), "pages": page_count(pdf)}
    candidates = []
    for number in range(1, record["pages"] + 1):
        text = page_text(pdf, number)
        named = sectors_named(text)
        if len(named) >= MIN_SECTORS and re.search(r"P/E", text):
            candidates.append({"page": number, "sectors_in_text": len(named), "images_on_page": page_images(pdf, number),
                               "text_pairs": read_pairs(text), "heading": next((l.strip() for l in text.splitlines() if l.strip()), "")[:100]})
    record["sector_pages"] = candidates
    for cand in candidates:
        png_prefix = out_dir / f"{day:%Y-%m-%d}-p{cand['page']}"
        run(["pdftoppm", "-f", str(cand["page"]), "-l", str(cand["page"]), "-r", "150", "-png", "-singlefile", str(pdf), str(png_prefix)])
        png = png_prefix.with_suffix(".png")
        text = ocr(png) if png.exists() else None
        if text is not None:
            cand["ocr_pairs"] = read_pairs(text)
            cand["ocr_sectors_with_numbers"] = len(cand["ocr_pairs"])
        if not keep_page:
            png.unlink(missing_ok=True)
    if not keep_page:
        pdf.unlink(missing_ok=True)
    return record


def implausible_moves(records: list[dict]) -> list[str]:
    """Sectors whose first number moved more than MAX_WEEKLY_MOVE between
    consecutive weeks that both read back (a misread, not a market)."""
    series: dict[str, list[tuple[str, float]]] = {}
    for rec in sorted(records, key=lambda r: r["friday"]):
        for cand in rec.get("sector_pages") or []:
            pairs = cand.get("text_pairs") or cand.get("ocr_pairs") or {}
            for sector, numbers in pairs.items():
                series.setdefault(sector, []).append((rec["friday"], numbers[0]))
            break
    bad = []
    for sector, points in series.items():
        for (d0, v0), (d1, v1) in zip(points, points[1:]):
            if v0 and abs(v1 / v0 - 1) > MAX_WEEKLY_MOVE:
                bad.append(f"{sector} {d0}->{d1}: {v0} -> {v1}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--out", default="data/probes/factset")
    parser.add_argument("--keep-newest", action="store_true", help="keep the newest sector page's PDF and PNG for inspection")
    args = parser.parse_args()
    for tool in ("pdftotext", "pdftoppm", "pdfimages", "pdfinfo"):
        if not shutil.which(tool):
            print(f"{tool} (poppler) is not installed", file=sys.stderr)
            return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    records, kept = [], False
    for day in fridays(args.years, date.today()):
        record = probe_week(day, out_dir, keep_page=args.keep_newest and not kept)
        kept = kept or bool(record.get("sector_pages"))
        records.append(record)
        state = "missing" if not record.get("found") else f"{len(record['sector_pages'])} sector page(s)"
        print(f"{record['friday']}  {state}", flush=True)
    found = [r for r in records if r.get("found")]
    with_page = [r for r in found if r["sector_pages"]]
    selectable = [r for r in with_page if any(len(c["text_pairs"]) >= EXTREMES_PER_WEEK for c in r["sector_pages"])]
    ocr_ok = [r for r in with_page if any(c.get("ocr_sectors_with_numbers", 0) >= EXTREMES_PER_WEEK for c in r["sector_pages"])]
    weeks_per_sector = {name: sum(1 for r in selectable for c in r["sector_pages"] if name in c["text_pairs"]) for name in SECTORS}
    summary = {
        "weeks_tried": len(records), "pdfs_found": len(found),
        "oldest_found": min((r["friday"] for r in found), default=None),
        "with_sector_page": len(with_page),
        "sector_numbers_selectable_as_text": len(selectable),
        "sector_numbers_read_by_ocr": len(ocr_ok), "tesseract": bool(shutil.which("tesseract")),
        "weeks_per_sector": weeks_per_sector,
        "implausible_moves": implausible_moves(records),
    }
    (out_dir / "summary.json").write_text(json.dumps({"summary": summary, "weeks": records}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
