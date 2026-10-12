"""Kenneth French's daily portfolio returns: the size and book-to-market sorts.

The Fama-French value factor (HML) is built from six value-weighted portfolios
sorted on size and book-to-market. This module reads the daily returns of those
six from the Data Library's zip, and only that section of it. The file is
published monthly, a month or more after month end, and its returns are in
percent: they come back here as decimals, indexed by the trading date.

The file is one CSV with prose at the top and then several sections, each
opened by a title line, a column line (starting with a comma) and one row per
date (YYYYMMDD). A blank line ends a section. The value-weighted section comes
first, and it is the only one read.
"""

from __future__ import annotations

import io
import re
import zipfile

import pandas as pd

from .. import cache
from .http import get_bytes

NAMESPACE = "french"
URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/6_Portfolios_2x3_daily_CSV.zip"
SECTION = "Average Value Weighted Returns -- Daily"
# The column names as the file prints them. SMALL / BIG is the size sort; LoBM
# is the lowest book-to-market third (growth), HiBM the highest (value).
PORTFOLIOS = ("SMALL LoBM", "ME1 BM2", "SMALL HiBM", "BIG LoBM", "ME2 BM2", "BIG HiBM")
# The file's own marker for a missing return (its notes say -99.99 or -999).
MISSING = (-99.99, -999.0)

_DATE_ROW = re.compile(r"^\s*(\d{8})\s*,")


def parse_value_weighted_daily(text: str) -> pd.DataFrame:
    """The value-weighted daily returns of the six portfolios, as decimals.

    Reads the section titled :data:`SECTION`: skips the prose before it and
    any blank lines, then takes the rows until the next blank line or title.
    Columns are looked up by name, so a reordered file still parses. A missing
    section, a missing portfolio or a short row raises rather than returning a
    partial frame.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == SECTION), None)
    if start is None:
        raise ValueError(f"no '{SECTION}' section in the French file")
    header = next((i for i in range(start + 1, len(lines)) if lines[i].strip()), None)
    if header is None or not lines[header].lstrip().startswith(","):
        raise ValueError(f"'{SECTION}' has no column line")
    names = [name.strip() for name in lines[header].split(",")[1:]]
    absent = [name for name in PORTFOLIOS if name not in names]
    if absent:
        raise ValueError(f"'{SECTION}' lacks {', '.join(absent)}")
    position = {name: names.index(name) + 1 for name in PORTFOLIOS}

    dates: list[str] = []
    rows: list[list[float]] = []
    for line in lines[header + 1:]:
        if not line.strip():
            if rows:
                break               # a blank line closes the section
            continue
        match = _DATE_ROW.match(line)
        if not match:
            break                   # the next title, or the copyright line
        fields = line.split(",")
        if len(fields) <= max(position.values()):
            raise ValueError(f"short row in '{SECTION}': {line.strip()[:60]}")
        dates.append(match.group(1))
        rows.append([float(fields[position[name]]) for name in PORTFOLIOS])
    if not rows:
        raise ValueError(f"'{SECTION}' has no rows")

    frame = pd.DataFrame(rows, columns=list(PORTFOLIOS), index=pd.to_datetime(dates, format="%Y%m%d"))
    frame = frame.where(~frame.isin(MISSING))
    frame = frame[~frame.index.duplicated()].sort_index()
    frame.index.name = "date"
    return frame / 100.0


def fetch_value_weighted_daily(*, use_cache: bool = True) -> pd.DataFrame:
    """Download the Data Library zip (or reuse it within a session) and parse its
    value-weighted section. The cache kind is ``daily_file``: the file changes
    monthly, so one download per session is more than enough."""
    payload = cache.fetch_bytes(
        NAMESPACE, "6_portfolios_2x3_daily", lambda: get_bytes(URL, timeout=60.0),
        kind="daily_file", suffix=".zip", use_cache=use_cache,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV in the French zip, found {len(members)}")
        text = archive.read(members[0]).decode("latin-1")
    return parse_value_weighted_daily(text)
