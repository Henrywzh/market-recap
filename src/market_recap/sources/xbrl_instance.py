"""Company facts read from a filing's own XBRL instance.

SEC's company-facts API is built from the same instance documents, but it is a
second pipeline and it can lag or skip a filing: Citigroup's 10-Qs filed on
2026-05-07 and 2026-08-06 were still absent from it two months later, so the
VALUATION row for C sat on FY2025 statements while every other bank was on
2026-06-30. The filing is the primary source. This reads its instance document
(the ``*_htm.xml`` that EDGAR extracts from the inline XBRL) and returns rows in
company-facts' own shape, so the rest of the extraction cannot tell the
difference.

Only what company facts itself carries is kept: facts with no dimension (a
segment or scenario narrows a fact to a slice, and company facts leaves those
out), in the ``us-gaap`` and ``dei`` taxonomies.
"""

from __future__ import annotations

import io
import re
from xml.etree import ElementTree as ET

XBRLI = "http://www.xbrl.org/2003/instance"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
TAXONOMIES = (("fasb.org/us-gaap", "us-gaap"), ("xbrl.sec.gov/dei", "dei"))
# dei facts that describe the filing itself; text, not numbers.
FILING_TAGS = ("DocumentType", "DocumentFiscalYearFocus", "DocumentFiscalPeriodFocus")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def _taxonomy(namespace: str) -> str | None:
    for marker, name in TAXONOMIES:
        if marker in namespace:
            return name
    return None


def _split(tag: str) -> tuple[str, str]:
    namespace, _, local = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    return namespace, local


def _unit_name(measures: list[str], divide: bool) -> str:
    names = [m.split(":")[-1] for m in measures]
    return "/".join(names) if divide else (names[0] if names else "")


def facts_from_instance(xml: bytes | str, *, accession: str, filed: str, form: str | None = None) -> dict:
    """{taxonomy: {tag: {unit: [row, ...]}}} in company-facts' shape.

    ``form``, ``fy`` and ``fp`` come from the instance's own cover facts unless
    ``form`` is given. A row is ``{start?, end, val, accn, fy, fp, form, filed}``.
    """
    source = io.BytesIO(xml.encode("utf-8") if isinstance(xml, str) else xml)
    contexts: dict[str, dict | None] = {}
    units: dict[str, str] = {}
    raw: list[tuple[str, str, str, str, str]] = []  # taxonomy, tag, context, unit, text
    cover: dict[str, str] = {}
    for _, element in ET.iterparse(source, events=("end",)):
        namespace, local = _split(element.tag)
        if namespace == XBRLI and local == "context":
            period = element.find(f"{{{XBRLI}}}period")
            dimensional = element.find(f"{{{XBRLI}}}entity/{{{XBRLI}}}segment") is not None \
                or element.find(f"{{{XBRLI}}}scenario") is not None
            if period is None or dimensional:
                contexts[element.get("id")] = None
            else:
                instant = period.findtext(f"{{{XBRLI}}}instant")
                start = period.findtext(f"{{{XBRLI}}}startDate")
                end = period.findtext(f"{{{XBRLI}}}endDate")
                contexts[element.get("id")] = {"end": (instant or end), "start": None if instant else start}
            element.clear()
        elif namespace == XBRLI and local == "unit":
            divide = element.find(f"{{{XBRLI}}}divide")
            if divide is not None:
                num = [m.text or "" for m in divide.findall(f"{{{XBRLI}}}unitNumerator/{{{XBRLI}}}measure")]
                den = [m.text or "" for m in divide.findall(f"{{{XBRLI}}}unitDenominator/{{{XBRLI}}}measure")]
                units[element.get("id")] = _unit_name(num + den, divide=True)
            else:
                units[element.get("id")] = _unit_name([m.text or "" for m in element.findall(f"{{{XBRLI}}}measure")], divide=False)
            element.clear()
        else:
            taxonomy = _taxonomy(namespace)
            if taxonomy is None or element.get("contextRef") is None:
                continue
            text = (element.text or "").strip()
            if taxonomy == "dei" and local in FILING_TAGS and text and local not in cover:
                cover[local] = text
            if element.get(XSI_NIL) == "true" or element.get("unitRef") is None or not _NUMBER.match(text):
                element.clear()
                continue
            raw.append((taxonomy, local, element.get("contextRef"), element.get("unitRef"), text))
            element.clear()

    fp = cover.get("DocumentFiscalPeriodFocus")
    try:
        fy: int | None = int(cover["DocumentFiscalYearFocus"])
    except (KeyError, ValueError):
        fy = None
    doc_form = form or cover.get("DocumentType")
    out: dict = {}
    seen: set[tuple] = set()
    for taxonomy, tag, ctx_id, unit_id, text in raw:
        period = contexts.get(ctx_id)
        unit = units.get(unit_id)
        if period is None or not unit or not period["end"]:
            continue
        value = float(text)
        key = (taxonomy, tag, unit, period["start"], period["end"], value)
        if key in seen:
            continue
        seen.add(key)
        row = {"end": period["end"], "val": int(value) if value.is_integer() and "e" not in text.lower() else value,
               "accn": accession, "fy": fy, "fp": fp, "form": doc_form, "filed": filed}
        if period["start"]:
            row = {"start": period["start"], **row}
        out.setdefault(taxonomy, {}).setdefault(tag, {}).setdefault(unit, []).append(row)
    return out


def merge_into(facts: dict, extra: dict) -> dict:
    """Add ``extra`` rows to a company-facts document, leaving rows it already
    has alone. Returns a new document; the input is not modified."""
    merged = {**facts, "facts": {**facts.get("facts", {})}}
    for taxonomy, concepts in extra.items():
        target = {tag: {**concept, "units": {u: list(r) for u, r in concept.get("units", {}).items()}}
                  for tag, concept in merged["facts"].get(taxonomy, {}).items()}
        for tag, by_unit in concepts.items():
            concept = target.setdefault(tag, {"units": {}})
            for unit, rows in by_unit.items():
                have = {(r.get("start"), r.get("end"), r.get("val"), r.get("accn")) for r in concept["units"].get(unit, [])}
                concept["units"].setdefault(unit, []).extend(
                    r for r in rows if (r.get("start"), r.get("end"), r.get("val"), r.get("accn")) not in have)
        merged["facts"][taxonomy] = target
    return merged
