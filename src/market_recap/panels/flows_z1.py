"""FLOWS section C: who bought US equities, by sector, from the Fed's Z.1 accounts.

Quarterly net purchases of corporate equities by holding sector, and net issues
by issuer, read from FRED's copies of the Z.1 tables (keyless CSV). The Fed
revises each release, so these are the current vintage only.
"""

from __future__ import annotations

import time

import pandas as pd

from .. import cache
from ..compute import z1 as Z
from ..sources import fred
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

# The Z.1 table these series come from, in the current release's numbering.
# The Fed's table mapping file renames the old F.224 (corporate equities) to
# F51.1.t; the old F.223 is now direct investment intercompany debt, so the
# spec's F.223 is not this table.
TABLE_URL = "https://www.federalreserve.gov/releases/z1/current/html/F51_1_t.htm"
FRED_PAGE = "https://fred.stlouisfed.org/series/{series_id}"
# Z.1 release dates. Constants: the Fed publishes the schedule, not the feed.
LATEST_RELEASE = "2026-09-11"
NEXT_RELEASE = "2026-12-10"
# The FU family is not seasonally adjusted, and is a quarter's own total. The
# SAAR (FA) copies are missing on FRED for households, rest of world, the
# financial issuer line and the nonfinancial issuer line, so one basis is used
# throughout and the page says so.
BASIS = "NSA"
# FRED is served behind a rate limit. Pause between uncached requests.
PACING_SECONDS = 2.0
# Source policy: a quarter-end figure published about ten weeks after quarter end.
SOURCE_POLICY = "quarterly_filing"

# FRED id per line, in millions of dollars for the quarter (FRED's Z.1 units).
SERIES = {
    "total": ("BOGZ1FU893064105Q", "All sectors, net purchases (total)"),
    "households": ("BOGZ1FU153064105Q", "Household sector"),
    "mutual_funds": ("BOGZ1FU653064100Q", "Mutual funds"),
    "etfs": ("BOGZ1FU563064100Q", "Exchange-traded funds"),
    "pension_private": ("BOGZ1FU573064105Q", "Private pension funds"),
    "pension_federal": ("BOGZ1FU343064105Q", "Federal government retirement funds"),
    "pension_state_local": ("BOGZ1FU223064145Q", "State and local government retirement funds"),
    "life_insurers": ("BOGZ1FU543064105Q", "Life insurance companies"),
    "pc_insurers": ("BOGZ1FU513064105Q", "Property-casualty insurance companies"),
    "broker_dealers": ("BOGZ1FU663064105Q", "Brokers and dealers"),
    "rest_of_world": ("BOGZ1FU263064105Q", "Rest of the world"),
    "financial_issues": ("BOGZ1FU793164105Q", "Domestic financial sectors, net issues"),
    "foreign_issues": ("BOGZ1FU263164105Q", "Foreign issues bought by US residents"),
}

# Chart groups, in stacking order. Each lists the holding-sector lines it sums;
# ``other`` is the total less every named group (see compute.z1.decompose).
GROUPS = (
    ("households", ("households",)),
    ("mutual_funds", ("mutual_funds",)),
    ("etfs", ("etfs",)),
    ("pensions", ("pension_private", "pension_federal", "pension_state_local")),
    ("insurers", ("life_insurers", "pc_insurers")),
    ("rest_of_world", ("rest_of_world",)),
    ("broker_dealers", ("broker_dealers",)),
)
GROUP_LABELS = {
    "households": "Households (residual sector)",
    "mutual_funds": "Mutual funds",
    "etfs": "ETFs",
    "pensions": "Pension funds",
    "insurers": "Insurers",
    "rest_of_world": "Rest of world",
    "broker_dealers": "Broker-dealers",
    "other": "Other",
}
GROUP_MEMBERS = {
    "households": "Household sector line (the Fed's residual sector)",
    "pensions": "private + federal retirement + state and local retirement",
    "insurers": "life insurers + property-casualty insurers",
    "other": "everything else: nonfinancial corporates, banks, hedge funds, closed-end and other funds, government, other financial",
}
ISSUER_KEYS = ("nfc_issues", "financial_issues", "foreign_issues")
ISSUER_LABELS = {
    "nfc_issues": "Nonfinancial net issues (below zero: net buybacks)",
    "financial_issues": "Financial net issues (mostly new ETF shares)",
    "foreign_issues": "Foreign issues bought by US residents",
}


def _fetch(series_id: str, *, first: bool) -> pd.Series:
    """One FRED series as a quarterly Series in $ millions, paced past the rate limit."""
    if not first and not cache.is_fresh(cache.path_for(fred.NAMESPACE, series_id, ".csv"), "macro_series"):
        time.sleep(PACING_SECONDS)
    frame, _ = fred.fetch_series(series_id)
    return frame.set_index("date")["value"].sort_index()


def _unavailable(ctx, error: str) -> dict:
    ctx.log.add(SourceRecord("z1_flows", "Federal Reserve Z.1 corporate equity purchases, by sector (via FRED)",
                             TABLE_URL, status="error", error=error))
    return {"unavailable": error}


def build(ctx, inputs: dict) -> dict:
    """The section's payload, or ``{"unavailable": reason}``. A source failure is a gap, never an error."""
    try:
        raw = {}
        for i, (key, (series_id, _)) in enumerate(SERIES.items()):
            raw[key] = _fetch(series_id, first=i == 0)
    except Exception as exc:  # noqa: BLE001 -- any fetch failure is a gap on the page
        return _unavailable(ctx, describe_error(exc))

    # Quarters as billions. Each line is aligned on the Z.1 quarter dates.
    frame = pd.DataFrame({key: Z.to_quarter_bn(values, BASIS) for key, values in raw.items()})
    latest = frame["total"].dropna().index[-1]
    # Every line must carry the total's latest quarter, or the groups would not sum to it.
    lagging = [key for key in SERIES if frame[key].dropna().index[-1] != latest]
    if lagging:
        return _unavailable(ctx, f"no {Z.quarter_label(latest)} value yet for {', '.join(lagging)}")

    frame = frame.loc[:latest]
    # Nonfinancial net issues (F51.1.t line 2) are not on FRED. Net issues are the
    # three issuer lines -- nonfinancial, domestic financial, rest of world -- and
    # equal net purchases (line 1 = line 17), so line 2 is the total less the other two.
    frame["nfc_issues"] = frame["total"] - frame["financial_issues"] - frame["foreign_issues"]
    groups = Z.decompose(frame, frame["total"], GROUPS)
    keys = [key for key, _ in GROUPS] + ["other"]
    total = frame["total"]

    def row(key: str, label: str, series: pd.Series) -> dict:
        return {"key": key, "label": label, **Z.summary(series)}

    latest_rows = [row(key, GROUP_LABELS[key], groups[key]) for key in keys]
    latest_rows.append(row("total", "Total, all sectors", total))
    issuer_rows = [row(key, ISSUER_LABELS[key], frame[key]) for key in ISSUER_KEYS]

    # The chart's quarters: the same dates for every line, missing kept as null.
    tail = groups.index[-Z.CHART_QUARTERS:]
    def values(series: pd.Series) -> list:
        return [clean_float(v, 2) for v in series.reindex(tail)]

    history = {
        "dates": [d.strftime("%Y-%m-%d") for d in tail],
        "total": values(total),
        "groups": {key: values(groups[key]) for key in keys},
        "nfc_issues": values(frame["nfc_issues"]),
    }

    ctx.log.add(SourceRecord(
        "z1_flows", "Federal Reserve Z.1 corporate equity purchases, by sector (via FRED)",
        FRED_PAGE.format(series_id=SERIES["total"][0]),
        observed_date=to_iso_date(Z.quarter_end(latest)), rows=int(frame.dropna(how="all").shape[0]),
        policy=SOURCE_POLICY,
    ))
    return {
        "as_of": ctx.as_of,
        "latest_quarter": Z.quarter_label(latest),
        "latest_quarter_end": to_iso_date(Z.quarter_end(latest)),
        "released": LATEST_RELEASE,
        "next_release": NEXT_RELEASE,
        "next_release_note": "Z.1 release schedule (the Fed's date for 2026:Q3); not read from a feed",
        "basis": BASIS,
        "units": "$bn per quarter",
        "groups": [{"key": key, "label": GROUP_LABELS[key], "members": GROUP_MEMBERS.get(key, "")} for key in keys],
        "latest": latest_rows,
        "issuers": issuer_rows,
        "history": history,
        "series": [{"id": sid, "key": key, "label": label, "page": FRED_PAGE.format(series_id=sid)}
                   for key, (sid, label) in SERIES.items()],
        "not_covered": [
            "Nonfinancial corporate net issues (F51.1.t line 2) are not on FRED; they are derived as total net issues less the financial and foreign issuer lines",
            "Seasonally adjusted (FA) copies are missing on FRED for households, rest of world and the financial issuer line, so the NSA family is used throughout",
        ],
        "revisions": "Each release revises earlier quarters. This is the current vintage only, not what was published at the time.",
    }
