"""CFTC Traders in Financial Futures: leveraged-money positioning.

Ported from alternative-data's global_market_regime.cot, with one change: the
query is by CFTC contract code, not market name. CFTC renamed its markets in
February 2022 ("E-MINI S&P 500 STOCK INDEX" became "E-MINI S&P 500"), so a
name filter silently cuts every history at 2022; the code runs through.

Report dates are the Tuesday the positions are as of. The report is published
the following Friday, so a reading is dated by its position date and is not
known until three days later -- the page says so rather than aligning it to
the Tuesday close.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from .. import cache
from .http import get_text

NAMESPACE = "cftc"
TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
HOME_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
ROW_LIMIT = 20000


def fetch_tff(codes: list[str], *, start: str = "2006-01-01", use_cache: bool = True) -> pd.DataFrame:
    """Weekly leveraged-money positions for the given contract codes.

    Columns: date, code, open_interest, long, short, net, net_pct_oi.
    """
    quoted = ",".join("'" + code.replace("'", "''") + "'" for code in codes)
    params = {
        "$select": ",".join([
            "report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "open_interest_all",
            "lev_money_positions_long", "lev_money_positions_short",
        ]),
        "$where": f"cftc_contract_market_code in ({quoted}) AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": str(ROW_LIMIT),
    }
    url = f"{TFF_URL}?{urlencode(params)}"
    text = cache.fetch_text(
        NAMESPACE, "tff-" + "-".join(sorted(codes)),
        lambda: get_text(url, timeout=60.0, headers={"Accept": "application/json"}),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    frame = pd.DataFrame(json.loads(text))
    if frame.empty:
        return pd.DataFrame(columns=["date", "code", "open_interest", "long", "short", "net", "net_pct_oi"])
    out = pd.DataFrame({
        "date": pd.to_datetime(frame["report_date_as_yyyy_mm_dd"].str[:10], errors="coerce"),
        "code": frame["cftc_contract_market_code"].astype(str),
        "open_interest": pd.to_numeric(frame["open_interest_all"], errors="coerce"),
        "long": pd.to_numeric(frame["lev_money_positions_long"], errors="coerce"),
        "short": pd.to_numeric(frame["lev_money_positions_short"], errors="coerce"),
    }).dropna(subset=["date", "long", "short"])
    out["net"] = out["long"] - out["short"]
    out["net_pct_oi"] = 100 * out["net"] / out["open_interest"].where(out["open_interest"] > 0)
    # Two market names can share a code in the week of a rename; keep one row.
    return out.drop_duplicates(["date", "code"], keep="last").sort_values(["code", "date"]).reset_index(drop=True)


# Every category's long and short side, plus open interest and the number of
# traders on each side. Field names checked against the live dataset: the
# reportable "other" side's trader count has no "_all" suffix, unlike the rest.
CATEGORY_FIELDS = {
    "open_interest": "open_interest_all",
    "dealer_long": "dealer_positions_long_all", "dealer_short": "dealer_positions_short_all",
    "asset_mgr_long": "asset_mgr_positions_long", "asset_mgr_short": "asset_mgr_positions_short",
    "lev_money_long": "lev_money_positions_long", "lev_money_short": "lev_money_positions_short",
    "other_long": "other_rept_positions_long", "other_short": "other_rept_positions_short",
    "nonrept_long": "nonrept_positions_long_all", "nonrept_short": "nonrept_positions_short_all",
    "traders_total": "traders_tot_all",
    "traders_dealer_long": "traders_dealer_long_all", "traders_dealer_short": "traders_dealer_short_all",
    "traders_asset_mgr_long": "traders_asset_mgr_long_all", "traders_asset_mgr_short": "traders_asset_mgr_short_all",
    "traders_lev_money_long": "traders_lev_money_long_all", "traders_lev_money_short": "traders_lev_money_short_all",
    "traders_other_long": "traders_other_rept_long_all", "traders_other_short": "traders_other_rept_short",
}
CATEGORY_COLUMNS = ["date", "code", *CATEGORY_FIELDS]


def fetch_tff_categories(codes: list[str], *, start: str = "2010-01-01", use_cache: bool = True) -> pd.DataFrame:
    """Weekly positions of every trader category for the given contract codes.

    One row per report date and code, futures only (the dataset's FutOnly rows),
    with the columns in CATEGORY_COLUMNS: long and short contracts for dealer,
    asset manager, leveraged money, other reportables and non-reportables, the
    open interest, and traders per side where the dataset counts them. Missing
    fields come through as NaN, never as zero.
    """
    quoted = ",".join("'" + code.replace("'", "''") + "'" for code in codes)
    params = {
        "$select": ",".join(["report_date_as_yyyy_mm_dd", "cftc_contract_market_code", *CATEGORY_FIELDS.values()]),
        "$where": (f"cftc_contract_market_code in ({quoted}) AND futonly_or_combined = 'FutOnly' "
                   f"AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'"),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": str(ROW_LIMIT),
    }
    url = f"{TFF_URL}?{urlencode(params)}"
    text = cache.fetch_text(
        NAMESPACE, "tff-categories-" + "-".join(sorted(codes)),
        lambda: get_text(url, timeout=60.0, headers={"Accept": "application/json"}),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    frame = pd.DataFrame(json.loads(text))
    if frame.empty:
        return pd.DataFrame(columns=CATEGORY_COLUMNS)
    out = pd.DataFrame({
        "date": pd.to_datetime(frame["report_date_as_yyyy_mm_dd"].str[:10], errors="coerce"),
        "code": frame["cftc_contract_market_code"].astype(str),
    })
    for key, field in CATEGORY_FIELDS.items():
        out[key] = pd.to_numeric(frame[field], errors="coerce") if field in frame else np.nan
    out = out.dropna(subset=["date"])
    return out.drop_duplicates(["date", "code"], keep="last").sort_values(["code", "date"]).reset_index(drop=True)
