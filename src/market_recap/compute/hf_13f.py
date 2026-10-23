"""13F crowding arithmetic: what the curated hedge funds own, and how it moved.

Pure functions over frames already read from EDGAR and SSGA. Nothing here
fetches, so every figure can be checked against a synthetic holding list.

Conventions, stated once:

- Long exposure is equity shares held outright. Rows carrying a put or call
  are options; they are summed apart and never added to the longs.
- A security is "crowded" by how many of the funds hold it, then by value.
- Weights are shares of the funds' combined long value in that quarter. The
  S&P 500 weight is the index's own weight on the SPY file's date, which is
  current, not quarter-end. The ratio of the two is the crowding read.
- Adds and cuts are measured in shares, valued at one price (the latest
  close), so a move in the stock does not count as buying.
"""

from __future__ import annotations

from datetime import date
import xml.etree.ElementTree as ET

import pandas as pd

# Quarterly 13F-HR filings are due 45 days after quarter end.
FILING_LAG_DAYS = 45

# From periods ending on this date, the information table reports whole dollars;
# earlier filings report thousands of dollars.
VALUE_IN_DOLLARS_FROM = "2022-12-31"

TOP_CROWDED = 25
TOP_FLOWS = 10
TOP_CONCENTRATION = 10

# Multi-strategy platforms are fetched but left out of the default aggregate.
INCLUDE_MULTI = False

_QUARTER_ENDS = {3: 31, 6: 30, 9: 30, 12: 31}

TABLE_COLUMNS = ["issuer", "cusip", "shares", "value_usd", "put_call"]
LONG_COLUMNS = ["cusip", "issuer", "shares", "value"]


def latest_complete_period(as_of: str) -> str:
    """The latest quarter end whose filing deadline has passed by ``as_of``."""
    day = date.fromisoformat(as_of)
    ends = [
        date(year, month, day_of_month)
        for year in (day.year - 1, day.year)
        for month, day_of_month in _QUARTER_ENDS.items()
    ]
    return max(end for end in ends if (day - end).days >= FILING_LAG_DAYS).isoformat()


def prior_quarter(period: str) -> str:
    """The quarter end before ``period``."""
    day = date.fromisoformat(period)
    month, year = day.month - 3, day.year
    if month <= 0:
        month += 12
        year -= 1
    return date(year, month, _QUARTER_ENDS[month]).isoformat()


def pick_filing(filings, period: str):
    """The accepted original for a quarter: the latest-filed 13F-HR whose period matches."""
    matches = [f for f in filings if f.period == period]
    return max(matches, key=lambda f: f.filed) if matches else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def parse_information_table(xml_text: str, period: str) -> pd.DataFrame:
    """One row per holding line: issuer, CUSIP, shares, dollar value, put/call.

    Namespace prefixes differ between filing agents, so elements are matched on
    their local names. Only share positions are kept; principal-amount rows
    (bonds) are not equity exposure.
    """
    root = ET.fromstring(xml_text.encode("utf-8"))
    scale = 1.0 if period >= VALUE_IN_DOLLARS_FROM else 1000.0
    rows = []
    for entry in root.iter():
        if _local(entry.tag) != "infoTable":
            continue
        fields: dict[str, str] = {}
        for child in entry.iter():
            name = _local(child.tag)
            if child.text and name not in fields:
                fields[name] = child.text
        if fields.get("sshPrnamtType", "SH").strip().upper() != "SH":
            continue
        value = _number(fields.get("value"))
        shares = _number(fields.get("sshPrnamt"))
        if value is None or shares is None:
            continue
        put_call = fields.get("putCall", "").strip().upper() or None
        rows.append({
            "issuer": fields.get("nameOfIssuer", "").strip(),
            "cusip": fields.get("cusip", "").strip().upper(),
            "shares": shares,
            "value_usd": value * scale,
            "put_call": put_call,
        })
    return pd.DataFrame(rows, columns=TABLE_COLUMNS)


def long_positions(table: pd.DataFrame) -> pd.DataFrame:
    """A filer's shares held outright, summed over its lines in each security."""
    longs = table[table["put_call"].isna()]
    if longs.empty:
        return pd.DataFrame(columns=LONG_COLUMNS)
    grouped = longs.groupby("cusip", as_index=False).agg(
        issuer=("issuer", "first"), shares=("shares", "sum"), value=("value_usd", "sum"),
    )
    return grouped[LONG_COLUMNS]


def option_exposure(table: pd.DataFrame) -> dict:
    """Options a filer reported, counted apart from its longs, in dollars and lines."""
    calls = table[table["put_call"] == "CALL"]
    puts = table[table["put_call"] == "PUT"]
    return {
        "put_rows": int(len(puts)), "call_rows": int(len(calls)),
        "put_value": float(puts["value_usd"].sum()), "call_value": float(calls["value_usd"].sum()),
    }


def aggregate(longs_by_filer: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """Per security across the filers given: how many hold it, and the shares and value they hold."""
    frames = []
    for cik, longs in longs_by_filer.items():
        held = longs[longs["shares"] > 0][LONG_COLUMNS].copy()
        held["cik"] = cik
        frames.append(held)
    columns = ["cusip", "issuer", "funds", "shares", "value"]
    if not frames:
        return pd.DataFrame(columns=columns)
    stacked = pd.concat(frames, ignore_index=True)
    out = stacked.groupby("cusip", as_index=False).agg(
        issuer=("issuer", "first"), funds=("cik", "nunique"),
        shares=("shares", "sum"), value=("value", "sum"),
    )
    return out[columns]


def _with_members(agg: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Rows of ``agg`` that are S&P 500 members, with the member's ticker, weight and sector."""
    return agg.merge(members, on="cusip", how="inner")


def crowded_names(agg: pd.DataFrame, members: pd.DataFrame, total_value: float,
                  top: int = TOP_CROWDED) -> pd.DataFrame:
    """The S&P 500 names the funds hold most widely, then by value."""
    if agg.empty or not total_value:
        return pd.DataFrame(columns=["cusip", "ticker", "funds", "value", "hf_pct", "sp_pct", "ratio"])
    ranked = _with_members(agg, members).copy()
    ranked["hf_pct"] = 100 * ranked["value"] / total_value
    ranked["sp_pct"] = ranked["weight"]
    ranked["ratio"] = ranked["hf_pct"] / ranked["sp_pct"].where(ranked["sp_pct"] > 0)
    ranked = ranked.sort_values(["funds", "value"], ascending=False).head(top)
    return ranked[["cusip", "ticker", "sector", "funds", "value", "hf_pct", "sp_pct", "ratio"]].reset_index(drop=True)


def outside_index(agg: pd.DataFrame, members: pd.DataFrame, total_value: float) -> dict:
    """Names the funds hold that are not in the S&P 500, counted and valued apart."""
    if agg.empty or not total_value:
        return {"names": 0, "value_share_pct": None}
    outside = agg[~agg["cusip"].isin(members["cusip"])]
    return {
        "names": int(len(outside)),
        "value_share_pct": float(100 * outside["value"].sum() / total_value),
    }


def concentration(agg: pd.DataFrame, total_value: float, top: int = TOP_CONCENTRATION) -> float | None:
    """Share of the funds' combined long value in their largest ``top`` names."""
    if agg.empty or not total_value:
        return None
    biggest = agg["value"].nlargest(top).sum()
    return float(100 * biggest / total_value)


def option_totals(exposures: list[dict]) -> dict:
    """Options summed over the filers, in dollars: the long book is not netted against them."""
    return {
        "put_rows": sum(e["put_rows"] for e in exposures),
        "call_rows": sum(e["call_rows"] for e in exposures),
        "put_value": sum(e["put_value"] for e in exposures),
        "call_value": sum(e["call_value"] for e in exposures),
    }


def changes(now: pd.DataFrame, prior: pd.DataFrame, members: pd.DataFrame,
            prices: dict[str, float], top: int = TOP_FLOWS) -> dict:
    """Adds and cuts between two quarters, for the filers that reported both.

    ``now`` and ``prior`` must cover the same filers. Shares are compared, then
    valued at one price so a move in the stock does not look like buying.
    """
    keys = ["cusip", "funds", "shares"]
    merged = now[keys].merge(prior[keys], on="cusip", how="outer", suffixes=("_now", "_prior"))
    merged[["funds_now", "funds_prior", "shares_now", "shares_prior"]] = (
        merged[["funds_now", "funds_prior", "shares_now", "shares_prior"]].fillna(0.0)
    )
    named = merged.merge(members[["cusip", "ticker", "yahoo_symbol"]], on="cusip", how="inner")
    named["d_holders"] = named["funds_now"] - named["funds_prior"]
    named["d_shares"] = named["shares_now"] - named["shares_prior"]
    # A name with no price this build has no dollar change, not a zero one.
    named["d_value"] = named["d_shares"] * named["yahoo_symbol"].map(prices).astype(float)
    # Changes in the holder count are read from the same common filers.
    valued = named.dropna(subset=["d_value"])

    def pick(frame: pd.DataFrame, by: str, ascending: bool) -> list[dict]:
        ordered = frame.sort_values(by, ascending=ascending).head(top)
        return [
            {"ticker": r.ticker, "d_holders": int(r.d_holders), "d_value": float(r.d_value)}
            for r in ordered.itertuples()
        ]

    adds = valued[valued["d_value"] > 0]
    cuts = valued[valued["d_value"] < 0]
    return {
        "adds": pick(adds, "d_value", ascending=False),
        "cuts": pick(cuts, "d_value", ascending=True),
        "adds_by_holders": pick(named[named["d_holders"] > 0], "d_holders", ascending=False),
        "cuts_by_holders": pick(named[named["d_holders"] < 0], "d_holders", ascending=True),
    }


def sector_tilt(agg: pd.DataFrame, members: pd.DataFrame) -> list[dict]:
    """Each sector's share of the funds' S&P 500 holdings against its share of the index.

    Both sides are normalised over the S&P 500 names alone, so they are
    comparable: the tilt is a difference in mix, not in how much is outside
    the index.
    """
    index_by_sector = members.groupby(members["sector"].fillna("Unclassified"))["weight"].sum()
    index_total = float(index_by_sector.sum())
    held = _with_members(agg, members).copy()
    held["sector"] = held["sector"].fillna("Unclassified")
    held_by_sector = held.groupby("sector")["value"].sum()
    held_total = float(held_by_sector.sum())
    rows = []
    for sector in sorted(set(index_by_sector.index) | set(held_by_sector.index)):
        hf = 100 * float(held_by_sector.get(sector, 0.0)) / held_total if held_total else None
        sp = 100 * float(index_by_sector.get(sector, 0.0)) / index_total if index_total else None
        rows.append({
            "sector": sector,
            "hf_pct": hf,
            "sp_pct": sp,
            "tilt_pts": (hf - sp) if hf is not None and sp is not None else None,
        })
    return sorted(rows, key=lambda r: -(r["tilt_pts"] or 0.0))
