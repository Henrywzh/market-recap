"""Korean earnings releases from DART, the FSS electronic disclosure system.

Samsung Electronics and SK hynix file their quarterly results as a fair
disclosure titled "연결재무제표기준영업(잠정)실적(공정공시)" (consolidated
preliminary operating results). DART's public search -- the one its own
pages use, no key -- lists each filing with its date; corrections
("[기재정정]") are dropped so a quarter counts once.

Both release in the Korean morning, which is the previous evening in New
York: the first US session to trade on the release is the one dated the same
calendar day as the filing.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import re

import httpx
from bs4 import BeautifulSoup

from .. import cache
from ..util import utc_now_iso

HOME_URL = "https://dart.fss.or.kr/dsab007/main.do"
SEARCH_URL = "https://dart.fss.or.kr/dsab007/detailSearch.ax"
VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}"
NAMESPACE = "dart"
RESULTS = "영업(잠정)실적"


def parse(html: str) -> list[dict]:
    """(date, title, receipt number) of every listed filing, corrections dropped."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        link = tr.find("a", href=re.compile(r"rcpNo=\d+"))
        if len(cells) < 5 or link is None:
            continue
        title, day = cells[2], cells[4]
        if "기재정정" in title or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", day):
            continue
        rcp = re.search(r"rcpNo=(\d+)", link["href"]).group(1)
        out.append({"date": day.replace(".", "-"), "title": title, "rcp": rcp, "url": VIEW_URL.format(rcp=rcp)})
    return out


def _search(company: str, start: date, end: date) -> str:
    data = {"currentPage": "1", "maxResults": "60", "maxLinks": "10", "sort": "date", "series": "desc",
            "textCrpCik": "", "lateKeyword": "", "keyword": "", "reportNamePopYn": "N", "textkeyword": "",
            "businessCode": "all", "autoSearch": "N", "option": "corp", "textCrpNm": company, "reportName": RESULTS,
            "startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "finalReport": "recent",
            "typesOfBusiness": "all", "corporationType": "all", "closingAccountsMonth": "all"}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": HOME_URL}
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        client.get(HOME_URL).raise_for_status()
        response = client.post(SEARCH_URL, data=data)
        response.raise_for_status()
    return json.dumps({"html": response.text, "fetched": utc_now_iso()})


def results(company: str, today: date, *, years: int = 4, use_cache: bool = True) -> list[dict]:
    """The company's results filings over ``years``, newest first."""
    start = today - timedelta(days=365 * years)
    text = cache.fetch_text(NAMESPACE, f"results-{company}-{today.isoformat()}", lambda: _search(company, start, today),
                            kind="daily_file", suffix=".json", use_cache=use_cache)
    rows = parse(json.loads(text)["html"])
    seen, out = set(), []
    for row in rows:
        if row["date"] not in seen:
            seen.add(row["date"])
            out.append(row)
    return out
