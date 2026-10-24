"""Revenue and profit by business, product and region, from each filing's XBRL.

SEC's company facts carry only undimensioned figures -- the company total. The
breakdowns a filer reports (ASC 280 operating segments, revenue by product or
service, revenue by region) are the same facts narrowed by a dimension, and
live only in the filing's own XBRL instance. This reads them from the filing's
``-xbrl.zip`` (the instance and its linkbases; a twentieth the size of the
extracted instance), keeps the few concepts the BY BUSINESS view needs, and
caches the result per accession: a filing never changes.

Which filings: every other 10-K back ANNUAL_FILINGS (each carries three years,
so the years join up) and the last QUARTERLY_FILINGS 10-Qs (each carries its
quarter and the year-ago quarter). A build reads at most ``budget`` filings not
yet cached, newest first across companies, so the first builds fill the history
over a few nights instead of in one long one.
"""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import re
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

from .. import cache
from . import sec

NAMESPACE = f"{sec.NAMESPACE}/segments"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
XLINK = "http://www.w3.org/1999/xlink"
ZIP_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-xbrl.zip"

# Every other 10-K: the latest, then two years back, and so on (about 15 years).
ANNUAL_FILINGS = 7
ANNUAL_STEP = 2
QUARTERLY_FILINGS = 12

# The three ways a filer breaks itself down, by the axis's local name.
AXES = {
    "StatementBusinessSegmentsAxis": "segment",
    "ProductOrServiceAxis": "product",
    "StatementGeographicalAxis": "geography",
}
# A segment figure is often tagged "operating segments" on the consolidation
# axis as well; the other members of that axis (eliminations, corporate,
# reconciling items) are not a business and are not kept.
CONSOLIDATION_AXIS = "ConsolidationItemsAxis"
OPERATING_SEGMENTS = "OperatingSegmentsMember"
REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RevenuesNetOfInterestExpense",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "RevenueFromExternalCustomers",
)
PROFIT_CONCEPTS = (
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
)
CONCEPTS = frozenset(REVENUE_CONCEPTS + PROFIT_CONCEPTS)
_NOT_AN_INSTANCE = re.compile(r"_(cal|def|lab|pre)\.xml$|FilingSummary|MetaLinks", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _member(qname: str) -> str:
    """``goog:GoogleCloudMember`` -> ``goog_GoogleCloudMember``, the id the label linkbase uses."""
    return qname.strip().replace(":", "_")


def _labels(xml: bytes, wanted: set[str]) -> dict[str, str]:
    """Labels for ``wanted`` member ids from a label linkbase, or from a schema
    that embeds its linkbases (some filing agents do). The terse label first:
    "Google Cloud" rather than "Google Cloud [Member]"."""
    locs: dict[str, str] = {}
    resources: dict[str, dict[str, str]] = {}
    arcs: list[tuple[str, str]] = []
    for _, element in ET.iterparse(io.BytesIO(xml), events=("end",)):
        name = _local(element.tag)
        if name == "loc":
            fragment = element.get(f"{{{XLINK}}}href", "").rsplit("#", 1)[-1]
            if fragment in wanted:
                locs[element.get(f"{{{XLINK}}}label")] = fragment
        elif name == "label" and element.get(f"{{{XLINK}}}label"):
            role = element.get(f"{{{XLINK}}}role", "").rsplit("/", 1)[-1]
            resources.setdefault(element.get(f"{{{XLINK}}}label"), {})[role] = (element.text or "").strip()
        elif name == "labelArc":
            arcs.append((element.get(f"{{{XLINK}}}from"), element.get(f"{{{XLINK}}}to")))
        if name not in ("loc", "label", "labelArc", "labelLink", "linkbase"):
            continue
        element.clear()
    out: dict[str, str] = {}
    for source, target in arcs:
        member = locs.get(source)
        found = resources.get(target)
        if member and found:
            text = found.get("terseLabel") or found.get("label") or next(iter(found.values()))
            out.setdefault(member, re.sub(r"\s*\[Member\]$", "", text))
    return out


def _number(text: str, fmt: str | None) -> float | None:
    """An inline-XBRL figure as written ("1,234", "(5)", "—"), by its format."""
    text = text.strip()
    fmt = (fmt or "").rsplit(":", 1)[-1].lower()
    if "zero" in fmt or text in {"-", "—", "–"}:
        return 0.0
    if "comma-decimal" in fmt or "numcommadecimal" in fmt:
        text = text.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        text = text.replace(",", "").replace(" ", "")
    text = text.strip("()")
    try:
        return float(text)
    except ValueError:
        return None


def _instance_facts(xml: bytes, inline: bool):
    """(contexts, usd units, raw facts, document period end) of one instance,
    plain XBRL or inline. Raw facts are (concept, context, unit, value) for the
    kept us-gaap concepts; contexts are resolved after the whole document is
    read, since an inline document may declare them after its facts."""
    contexts: dict[str, tuple | None] = {}
    usd: set[str] = set()
    raw: list[tuple[str, str, str, float]] = []
    period_end = None
    for _, element in ET.iterparse(io.BytesIO(xml), events=("end",)):
        name = _local(element.tag)
        namespace = element.tag[1:].split("}", 1)[0] if element.tag.startswith("{") else ""
        if namespace == XBRLI and name == "context":
            period = element.find(f"{{{XBRLI}}}period")
            start = period.findtext(f"{{{XBRLI}}}startDate") if period is not None else None
            end = period.findtext(f"{{{XBRLI}}}endDate") if period is not None else None
            dims = {(m.get("dimension") or "").split(":")[-1]: (m.text or "").strip()
                    for m in element.iter(f"{{{XBRLDI}}}explicitMember")}
            typed = next(element.iter(f"{{{XBRLDI}}}typedMember"), None) is not None
            contexts[element.get("id")] = None if (not start or not end or typed) else (start.strip(), end.strip(), dims)
            element.clear()
        elif namespace == XBRLI and name == "unit":
            measures = [m.text or "" for m in element.iter(f"{{{XBRLI}}}measure")]
            if len(measures) == 1 and measures[0].split(":")[-1].upper() == "USD":
                usd.add(element.get("id"))
            element.clear()
        elif inline and name == "nonNumeric" and (element.get("name") or "").endswith(":DocumentPeriodEndDate"):
            period_end = "".join(element.itertext()).strip() or period_end
        elif not inline and name == "DocumentPeriodEndDate":
            period_end = (element.text or "").strip() or period_end
        elif inline and name == "nonFraction":
            prefix, _, concept = (element.get("name") or "").partition(":")
            if prefix == "us-gaap" and concept in CONCEPTS and element.get("contextRef"):
                nil = element.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"
                value = None if nil else _number("".join(element.itertext()), element.get("format"))
                if value is not None:
                    value *= 10 ** int(element.get("scale") or 0)
                    if element.get("sign") == "-":
                        value = -value
                    raw.append((concept, element.get("contextRef"), element.get("unitRef"), value))
        elif not inline and name in CONCEPTS and "us-gaap" in namespace and element.get("contextRef"):
            try:
                raw.append((name, element.get("contextRef"), element.get("unitRef"), float((element.text or "").strip())))
            except ValueError:
                pass
            element.clear()
    return contexts, usd, raw, period_end


def _inline_document(archive: zipfile.ZipFile, names: list[str]) -> str | None:
    """The inline-XBRL document in an archive: the .htm carrying ix:header."""
    for name in sorted((n for n in names if n.lower().endswith((".htm", ".html"))), key=lambda n: -archive.getinfo(n).file_size):
        if b"ix:header" in archive.read(name):
            return name
    return None


def parse_filing(data: bytes, *, want_labels: bool) -> dict:
    """The segment, product and region facts of one filing's ``-xbrl.zip``:
    the instance for filings before inline XBRL, the inline document since.

    Returns ``{period_end, facts, totals, labels}``: ``facts`` rows are
    ``[concept, view, member, within, start, end, value]`` (``within`` is the
    segment a product figure is reported under, else None); ``totals`` rows are
    ``[concept, start, end, value]``, the undimensioned company figures.
    """
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = archive.namelist()
    instance = next((n for n in names if n.endswith("_htm.xml")), None) or next(
        (n for n in names if n.endswith(".xml") and not _NOT_AN_INSTANCE.search(n)), None)
    inline = instance is None
    if inline:
        instance = _inline_document(archive, names)
    if instance is None:
        raise LookupError("no XBRL instance in the archive")
    contexts, usd, raw, period_end = _instance_facts(archive.read(instance), inline)
    facts, totals, seen = [], [], set()
    for concept, context_id, unit, value in raw:
        context = contexts.get(context_id)
        if context is None or unit not in usd:
            continue
        start, end, dims = context
        dims = dict(dims)
        if CONSOLIDATION_AXIS in dims and dims.pop(CONSOLIDATION_AXIS).split(":")[-1] != OPERATING_SEGMENTS:
            continue
        row = None
        if not dims:
            row = ("total", concept, start, end, value)
        else:
            views = {AXES[a]: m for a, m in dims.items() if a in AXES}
            if len(views) == len(dims) == 1:
                (view, member), = views.items()
                row = ("fact", concept, view, _member(member), None, start, end, value)
            elif len(dims) == 2 and set(views) == {"product", "segment"}:
                row = ("fact", concept, "product", _member(views["product"]), _member(views["segment"]), start, end, value)
        if row is not None and row not in seen:
            seen.add(row)
            (totals if row[0] == "total" else facts).append(list(row[1:]))
    labels: dict[str, str] = {}
    if want_labels:
        wanted = {f[2] for f in facts} | {f[3] for f in facts if f[3]}
        source = next((n for n in names if n.endswith("_lab.xml")), None) or next((n for n in names if n.endswith(".xsd")), None)
        if source and wanted:
            labels = _labels(archive.read(source), wanted)
    return {"period_end": period_end, "facts": facts, "totals": totals, "labels": labels}


@dataclass(frozen=True)
class Filing:
    cik: int
    form: str
    accession: str
    filed: str
    labels: bool  # read the member labels from this one


def _submissions(cik: int) -> dict:
    """The filer's submissions document: the same cache entry the SEC panels read."""
    text = cache.fetch_text(
        f"{sec.NAMESPACE}/submissions", f"CIK{cik:010d}",
        lambda: sec._get(sec.SUBMISSIONS_URL.format(cik=cik), 45.0),
        kind="daily_file", suffix=".json", compress=True,
    )
    return json.loads(text)


def _rows(block: dict) -> list[tuple[str, str, str, bool]]:
    return [(form, accession, filed, bool(xbrl)) for form, accession, filed, xbrl in zip(
        block.get("form", []), block.get("accessionNumber", []), block.get("filingDate", []), block.get("isXBRL", []))]


def statement_filings(cik: int) -> list[Filing]:
    """The 10-Ks and 10-Qs read for one filer, newest first. A filer with
    thousands of other filings (a bank's prospectus supplements) keeps its
    older ones on further pages, which are read until enough 10-Ks are found."""
    document = _submissions(cik)
    rows = _rows(document.get("filings", {}).get("recent", {}))
    annual_needed = (ANNUAL_FILINGS - 1) * ANNUAL_STEP + 1
    for page in document.get("filings", {}).get("files", []):
        if sum(1 for r in rows if r[0] == "10-K") >= annual_needed:
            break
        name = page.get("name")
        if not name:
            continue
        text = cache.fetch_text(
            f"{sec.NAMESPACE}/submissions", name.removesuffix(".json"),
            lambda name=name: sec._get(f"https://data.sec.gov/submissions/{name}", 45.0),
            kind="archive", suffix=".json", compress=True,
        )
        rows += _rows(json.loads(text))
    rows = sorted({r[1]: r for r in rows}.values(), key=lambda r: r[2], reverse=True)
    annual = [r for r in rows if r[0] == "10-K" and r[3]][:annual_needed:ANNUAL_STEP]
    quarterly = [r for r in rows if r[0] == "10-Q" and r[3]][:QUARTERLY_FILINGS]
    newest = {annual[0][1] if annual else None, quarterly[0][1] if quarterly else None}
    chosen = [Filing(cik, form, accession, filed, labels=(form == "10-K" or accession in newest))
              for form, accession, filed, _ in annual + quarterly]
    return sorted(chosen, key=lambda f: f.filed, reverse=True)


def _path(filing: Filing):
    return cache.path_for(NAMESPACE, filing.accession, ".json" + cache.GZIP_SUFFIX)


def cached(filing: Filing) -> dict | None:
    path = _path(filing)
    if not path.exists():
        return None
    try:
        payload = json.loads(cache._read(path, compress=True))
    except Exception:
        return None
    # Read nightly, never stale: keep it clear of the cache's age-based pruning.
    try:
        os.utime(path)
    except OSError:
        pass
    return payload


def _store(filing: Filing, payload: dict) -> None:
    cache._write(_path(filing), json.dumps(payload, separators=(",", ":")).encode(), compress=True)


def _download(filing: Filing) -> bytes:
    folder = filing.accession.replace("-", "")
    url = ZIP_URL.format(cik=filing.cik, folder=folder, accession=filing.accession)
    for attempt in range(sec.ATTEMPTS):
        sec._throttle()
        try:
            response = httpx.get(url, headers={"User-Agent": sec.SEC_USER_AGENT}, timeout=120.0)
        except httpx.TransportError:
            if attempt == sec.ATTEMPTS - 1:
                raise
            continue
        if response.status_code in sec.RETRY_STATUSES and attempt < sec.ATTEMPTS - 1:
            continue
        response.raise_for_status()
        return response.content
    raise AssertionError("unreachable")


def _empty(filing: Filing, why: str) -> dict:
    return {"accession": filing.accession, "form": filing.form, "filed": filing.filed,
            "period_end": None, "facts": [], "totals": [], "labels": {}, "error": why}


def _parse_job(args: tuple[bytes, bool]) -> dict:
    data, want_labels = args
    return parse_filing(data, want_labels=want_labels)


def fetch_missing(filings: list[Filing], budget: int, *, workers: int = 4) -> dict:
    """Download and parse up to ``budget`` filings not yet cached: the
    downloads on threads under SEC's shared throttle, the XML on processes.
    Returns ``{fetched, failed: {accession: why}, deferred}``."""
    todo = [f for f in filings if not _path(f).exists()]
    now, deferred = todo[:budget], len(todo) - min(len(todo), budget)
    failed: dict[str, str] = {}
    fetched = 0
    if not now:
        return {"fetched": 0, "failed": failed, "deferred": deferred}
    # Spawned, not forked: the build has other threads running (EVENTS' Finnhub phase).
    with ThreadPoolExecutor(workers) as downloads, ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as parses:
        pending = {downloads.submit(_download, f): f for f in now}
        parsing = {}
        for future, filing in pending.items():
            try:
                data = future.result()
            except httpx.HTTPStatusError as exc:
                failed[filing.accession] = str(exc)[:200]
                if exc.response.status_code == 404:  # no XBRL archive: never will be
                    _store(filing, _empty(filing, "no -xbrl.zip"))
                continue
            except Exception as exc:
                failed[filing.accession] = str(exc)[:200]
                continue
            parsing[parses.submit(_parse_job, (data, filing.labels))] = filing
        for future, filing in parsing.items():
            try:
                payload = future.result()
            except (LookupError, ET.ParseError, zipfile.BadZipFile) as exc:
                # The filing itself cannot be read: recorded, not retried every night.
                failed[filing.accession] = str(exc)[:200]
                _store(filing, _empty(filing, str(exc)[:200]))
                continue
            except Exception as exc:
                failed[filing.accession] = str(exc)[:200]
                continue
            _store(filing, {"accession": filing.accession, "form": filing.form, "filed": filing.filed, **payload})
            fetched += 1
    return {"fetched": fetched, "failed": failed, "deferred": deferred}
