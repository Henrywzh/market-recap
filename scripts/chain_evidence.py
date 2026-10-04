"""Check every AI-chain edge against the SEC filings of its two companies.

For each edge (config/ai_chain.toml) the annual reports (10-K, 20-F, 40-F) of
both sides from the last three years are searched, through EDGAR full-text
search, for the other side's name. The first filing that names it gives the
edge its evidence: the form, the date, the link and the sentence the name
sits in, so a reader can see what the filing says rather than take the
graph's word for it. An edge neither side's filings name -- two companies
outside SEC filing, or a customer a supplier does not name -- is written out
as unverified, and keeps the `source` the config gives it, if any.

    PYTHONPATH=src python3 scripts/chain_evidence.py

Writes config/ai_chain_evidence.json. Run by hand when the graph changes; the
nightly build only reads the file.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import sys
import time
import tomllib

from bs4 import BeautifulSoup
import httpx

from market_recap import cache
from market_recap.config import SEC_USER_AGENT
from market_recap.panels.financials import cik_for
from market_recap.sources import sec

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "config" / "ai_chain.toml"
OUT = ROOT / "config" / "ai_chain_evidence.json"
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{file}"
FORMS = "10-K,20-F,40-F"
YEARS = 3
PAUSE_S = 0.2
# Words that make a sentence about the edge's relationship, by type, rather
# than a passing mention (a tariff on NVIDIA's chips in Arm's risk factors).
TELLING = {
    "supplies": re.compile(r"customers?\b|suppliers?\b|suppl(y|ies|ied)\b|purchase|accounted for|revenue from|"
                           r"contract manufactur|subcontract|foundr|manufactures? (our|for)|depend|agreement|orders?\b", re.I),
    "competes": re.compile(r"compet", re.I),
    "partner": re.compile(r"joint venture|partner|stake|equity (interest|investment)|Flash Ventures|collaborat", re.I),
}
# Phrases that state the tie outright: worth more than any number of the words above.
STATED = {
    "supplies": re.compile(r"accounted for (more than )?\d+%|(largest|significant|major|key|top) customers?|customers? (include|included|such as)|"
                           r"(we|to) (purchase|buy|source)|we utilize|suppliers?,? (such as|include)|contract manufacturers? such as|"
                           r"(agreement|contract) with|revenue from", re.I),
    "competes": re.compile(r"competitors? (are|include|such as)|compete (with|against)|primary competitors", re.I),
    "partner": re.compile(r"joint venture|Flash Ventures|equity (interest|investment|stake)|strategic (partnership|collaboration)", re.I),
}
# A sentence that says nothing of the tie however many of the words it has.
NOISE = re.compile(r"tariff|award|forward-looking|index of|exhibit \d|Xbox|termination of|visited|paid a visit|"
                   r"governing documents|change in control|Specimen|333-\d|peer group|Chief (Executive|Financial)|"
                   r"served as|issued shares", re.I)
HITS_READ = 2
# How a filing names each company: the config's name is not always the one
# legal documents use.
ALIASES = {
    "TSM": ["Taiwan Semiconductor", "TSMC"],
    "005930.KS": ["Samsung"],
    "000660.KS": ["SK hynix", "SK Hynix", "Hynix"],
    "8035.T": ["Tokyo Electron"],
    "6857.T": ["Advantest"],
    "6146.T": ["DISCO", "Disco Corporation"],
    "6920.T": ["Lasertec"],
    "4063.T": ["Shin-Etsu", "Shin Etsu"],
    "285A.T": ["Kioxia"],
    "ASM.AS": ["ASM International"],
    "BESI.AS": ["BE Semiconductor", "Besi"],
    "2317.TW": ["Hon Hai", "Foxconn"],
    "2382.TW": ["Quanta Computer"],
    "6669.TW": ["Wiwynn"],
    "3231.TW": ["Wistron"],
    "2308.TW": ["Delta Electronics"],
    "SU.PA": ["Schneider Electric"],
    "ENR.DE": ["Siemens Energy"],
    "GOOGL": ["Google", "Alphabet"],
    "META": ["Meta Platforms", "Meta"],
    "MSFT": ["Microsoft"],
    "AMZN": ["Amazon", "AWS"],
    "ORCL": ["Oracle"],
    "NVDA": ["NVIDIA", "Nvidia"],
    "AMD": ["Advanced Micro Devices", "AMD"],
    "AVGO": ["Broadcom"],
    "INTC": ["Intel"],
    "MU": ["Micron"],
    "ASML": ["ASML"],
    "AMAT": ["Applied Materials"],
    "LRCX": ["Lam Research"],
    "KLAC": ["KLA"],
    "ANET": ["Arista"],
    "CSCO": ["Cisco"],
    "CIEN": ["Ciena"],
    "CRWV": ["CoreWeave"],
    "NBIS": ["Nebius"],
    "ASX": ["ASE Technology", "Advanced Semiconductor Engineering"],
    "AMKR": ["Amkor"],
    "ARM": ["Arm Limited", "Arm Holdings", "Arm"],
    "SNPS": ["Synopsys"],
    "CDNS": ["Cadence"],
    "DELL": ["Dell"],
    "HPE": ["Hewlett Packard Enterprise", "HPE"],
    "SMCI": ["Super Micro", "Supermicro"],
    "VRT": ["Vertiv"],
    "CEG": ["Constellation"],
}


def names(key: str, node: dict) -> list[str]:
    return ALIASES.get(key) or [node["name"]]


def search(client: httpx.Client, text: str, cik: int, since: date) -> list[dict]:
    params = {"q": f'"{text}"', "ciks": f"{cik:010d}", "forms": FORMS, "dateRange": "custom",
              "startdt": since.isoformat(), "enddt": date.today().isoformat()}
    key = f"efts-{cik}-{re.sub(r'[^A-Za-z0-9]+', '_', text)}-{since.isoformat()}"
    body = cache.fetch_text("chain-evidence", key, lambda: _get(client, SEARCH_URL, params), kind="archive", suffix=".json")
    hits = json.loads(body).get("hits", {}).get("hits", [])
    out = []
    for h in hits:
        accession, _, file = h["_id"].partition(":")
        src = h["_source"]
        out.append({"form": src.get("form"), "filed": src.get("file_date"), "accession": accession, "file": file})
    return sorted(out, key=lambda h: h["filed"] or "", reverse=True)


def _get(client: httpx.Client, url: str, params: dict | None = None) -> str:
    # EDGAR's search answers a burst with a 500 now and then; a few spaced
    # tries clear it.
    for attempt in range(4):
        time.sleep(PAUSE_S * (1 + 10 * attempt))
        response = client.get(url, params=params)
        if response.status_code < 500:
            break
    response.raise_for_status()
    return response.text


def sentences(client: httpx.Client, cik: int, hit: dict, wanted: list[str], kind: str) -> list[tuple[int, str, str]]:
    """(score, sentence, url) for each place the filing names the company."""
    url = DOC_URL.format(cik=cik, accession=hit["accession"].replace("-", ""), file=hit["file"])
    html = cache.fetch_text("chain-evidence", f"doc-{hit['accession']}-{hit['file']}", lambda: _get(client, url),
                            kind="archive", suffix=".html", compress=True)
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))
    pattern = re.compile("|".join(rf"\b{re.escape(w)}\b" for w in wanted))
    out = []
    for m in pattern.finditer(text):
        start = max(text.rfind(". ", 0, m.start()) + 2, m.start() - 260)
        end = text.find(". ", m.end())
        end = min(end + 1 if end != -1 else len(text), m.end() + 260)
        found = text[start:end].strip()
        score = 0 if NOISE.search(found) else len(TELLING[kind].findall(found)) + 5 * len(STATED[kind].findall(found))
        out.append((score, found, url))
    return out


def main() -> int:
    graph = tomllib.loads(GRAPH.read_text(encoding="utf-8"))
    nodes = {n["key"]: n for n in graph["nodes"]}
    groups = graph.get("groups") or {}
    cik_map = sec.fetch_ticker_cik_map()
    ciks = {k: cik_for(k, cik_map) for k in nodes}
    since = date.today() - timedelta(days=365 * YEARS)
    out: dict[str, dict] = {}
    failed: list[str] = []
    with httpx.Client(headers={"User-Agent": SEC_USER_AGENT}, timeout=60.0) as client:
        for edge in graph["edges"]:
            for target in edge["to"]:
                if target.startswith("@"):
                    for member in groups[target[1:]]:
                        out[f"{edge['from']}>{member}"] = {"named": False, "group": target[1:]}
                    continue
                pair = (edge["from"], target)
                found = None
                # Both sides' annual reports: the supplier naming its customer,
                # the customer naming its supplier, either naming a competitor.
                # The sentence that says most about the tie wins.
                for filer, named in (pair, pair[::-1]):
                    cik = ciks.get(filer)
                    if not cik:
                        continue
                    for alias in names(named, nodes[named]):
                        try:
                            hits = search(client, alias, cik, since)
                        except httpx.HTTPError as exc:
                            print("   search failed:", filer, alias, type(exc).__name__, flush=True)
                            failed.append(f"{filer}:{alias}")
                            continue
                        for hit in hits[:HITS_READ]:
                            for score, text, url in sentences(client, cik, hit, names(named, nodes[named]), edge["type"]):
                                if found is None or score > found["score"]:
                                    found = {"named": True, "filer": filer, "form": hit["form"], "filed": hit["filed"],
                                             "url": url, "text": text, "searched": alias, "score": score}
                        if found and found["score"] >= 5:
                            break
                if found:
                    # "relationship": the sentence speaks to the tie; "mention":
                    # the filing names the company, nowhere about the tie.
                    score = found.pop("score")
                    found["strength"] = "stated" if score >= 5 else "relationship" if score > 0 else "mention"
                out[f"{edge['from']}>{target}"] = found or {"named": True, "missing": True}
                status = "-- " if not found else {"stated": "ok ", "relationship": "~  ", "mention": ".  "}[found["strength"]]
                print(status, f"{edge['type']:9s}", f"{edge['from']:>10s} > {target:<10s}",
                      (found or {}).get("filer", ""), (found or {}).get("filed", ""), flush=True)
    OUT.write_text(json.dumps({"checked": date.today().isoformat(), "years": YEARS, "forms": FORMS,
                              "search_failed": failed, "edges": out},
                              indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = [k for k, v in out.items() if v.get("missing")]
    weak = [k for k, v in out.items() if v.get("strength") == "mention"]
    print(f"{len(out)} edges, {len(missing)} not named in either side's filings, {len(weak)} named only in passing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
