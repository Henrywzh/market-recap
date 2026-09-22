"""US Treasury daily par yield curve rates -- the official published curve.

"Latest published" is deliberately not "today". Treasury usually posts the
same day but sometimes not until the evening ET, so a refresh run shortly
after the close can legitimately show the prior business day. The artifact
carries the published date so the page can say which one it is showing
instead of implying the curve is stale or broken.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from lxml import etree

from .http import get_bytes

XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

# Treasury's element names -> the tenors the curve panel plots, in order.
TENORS = [
    ("BC_1MONTH", "1M", 1),
    ("BC_2MONTH", "2M", 2),
    ("BC_3MONTH", "3M", 3),
    ("BC_4MONTH", "4M", 4),
    ("BC_6MONTH", "6M", 6),
    ("BC_1YEAR", "1Y", 12),
    ("BC_2YEAR", "2Y", 24),
    ("BC_3YEAR", "3Y", 36),
    ("BC_5YEAR", "5Y", 60),
    ("BC_7YEAR", "7Y", 84),
    ("BC_10YEAR", "10Y", 120),
    ("BC_20YEAR", "20Y", 240),
    ("BC_30YEAR", "30Y", 360),
]
_D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"


def fetch_par_yield_curve(years: list[int] | None = None) -> tuple[pd.DataFrame, str]:
    """Tidy (date, tenor, tenor_months, yield_pct) across the requested years."""
    years = years or [date.today().year - 1, date.today().year]
    rows: list[dict] = []
    for year in years:
        url = XML_URL.format(year=year)
        tree = etree.fromstring(get_bytes(url, timeout=90.0))
        for entry in tree.iter("{http://www.w3.org/2005/Atom}entry"):
            props = entry.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
            if props is None:
                continue
            stamp = props.findtext(f"{_D}NEW_DATE")
            if not stamp:
                continue
            observed = pd.Timestamp(stamp).strftime("%Y-%m-%d")
            for element, tenor, months in TENORS:
                text = props.findtext(f"{_D}{element}")
                if text is None or text == "":
                    continue
                try:
                    value = float(text)
                except ValueError:
                    continue
                rows.append(
                    {"date": observed, "tenor": tenor, "tenor_months": months, "yield_pct": value}
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, XML_URL.format(year=years[-1])
    frame = frame.drop_duplicates(["date", "tenor"], keep="last")
    return frame.sort_values(["date", "tenor_months"]).reset_index(drop=True), XML_URL.format(year=years[-1])
