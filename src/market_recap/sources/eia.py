"""EIA weekly petroleum and natural gas, from the public history pages.

The Weekly Petroleum Status Report (Wednesdays, 10:30 New York) and the
Weekly Natural Gas Storage Report (Thursdays, 10:30) are published as history
tables on EIA's data pages, which need no key: one row per month, each week
as (week-ending date, value). Petroleum back to 1982-83 (gasoline 1990),
lower-48 gas storage back to 2010.

The page is the current vintage: EIA revises a week rarely and by little, so
the table is read as published now, not as it stood each week.
"""

from __future__ import annotations

from datetime import date, timedelta
import re

from bs4 import BeautifulSoup
import pandas as pd

from .. import cache
from .http import get_text

NAMESPACE = "eia"
PETROLEUM_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series}&f=W"
GAS_URL = "https://www.eia.gov/dnav/ng/hist/{series}w.htm"
PAGE_URL = "https://www.eia.gov/petroleum/supply/weekly/"
UA = "Mozilla/5.0"


# key: (url template, EIA series, label, unit)
SERIES = {
    "crude_stocks": (PETROLEUM_URL, "WCESTUS1", "Commercial crude stocks (ex-SPR)", "mb"),
    "gasoline_stocks": (PETROLEUM_URL, "WGTSTUS1", "Gasoline stocks", "mb"),
    "distillate_stocks": (PETROLEUM_URL, "WDISTUS1", "Distillate stocks", "mb"),
    "refinery_utilization": (PETROLEUM_URL, "WPULEUS3", "Refinery utilization", "pct"),
    "crude_production": (PETROLEUM_URL, "WCRFPUS2", "US crude production", "kbd"),
    "gas_storage": (GAS_URL, "nw2_epg0_swo_r48_bcf", "Lower-48 working gas in storage", "bcf"),
}
_MONTH = re.compile(r"^(\d{4})-([A-Z][a-z]{2})$")
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def parse(html: str) -> pd.Series:
    """Week-ending date -> value from a history page."""
    soup = BeautifulSoup(html, "html.parser")
    points = {}
    for row in soup.select("table tr"):
        label = row.find("td", class_="B6")
        if label is None:
            continue
        m = _MONTH.match(label.get_text(strip=True))
        if not m:
            continue
        year = int(m.group(1))
        cells = [td.get_text(strip=True) for td in row.find_all("td")][1:]
        for day, value in zip(cells[::2], cells[1::2]):
            if not day or not value:
                continue
            month, dom = (int(p) for p in day.split("/"))
            try:
                points[pd.Timestamp(year, month, dom)] = float(value.replace(",", ""))
            except ValueError:
                continue
    return pd.Series(points, dtype=float).sort_index()


def fetch(key: str, *, use_cache: bool = True) -> pd.Series:
    template, series, _, _ = SERIES[key]
    url = template.format(series=series)
    html = cache.fetch_text(NAMESPACE, series, lambda: get_text(url, user_agent=UA, timeout=60.0, retries=1),
                            kind="daily_file", suffix=".html", compress=True, use_cache=use_cache)
    return parse(html)


def seasonal(series: pd.Series, years: int = 5) -> pd.DataFrame:
    """Each week's value, its change on the week, and the average of the same
    week of the year over the ``years`` before it (EIA's own comparison)."""
    frame = pd.DataFrame({"value": series})
    frame["week"] = frame.index.isocalendar().week.clip(upper=52).to_numpy()
    frame["year"] = frame.index.year
    by = frame.pivot_table(index="year", columns="week", values="value", aggfunc="last")
    averages = []
    for stamp, row in frame.iterrows():
        prior = by.loc[(by.index < row["year"]) & (by.index >= row["year"] - years), row["week"]].dropna()
        averages.append(float(prior.mean()) if len(prior) == years else None)
    frame["avg5"] = averages
    frame["change"] = frame["value"].diff()
    frame["vs_avg5_pct"] = (frame["value"] / frame["avg5"] - 1) * 100
    return frame.drop(columns=["week", "year"])


def next_release(as_of: date, weekday: int) -> date:
    """The next weekday-numbered release after ``as_of`` (Wednesday 2 for
    petroleum, Thursday 3 for gas); a holiday shifts it a day, not shown."""
    day = as_of + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day
