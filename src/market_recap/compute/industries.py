"""Industry scorecard: one group of names read as the median of its members.

A sub-industry's cap-weighted return is a few large names (Semiconductors is
17% of the index); its median member says what happened to the industry. Beside
the move, the evidence that tells a fall the estimates explain from one they do
not: how many names fell, how far they sit under their high, whether analysts
cut this year's EPS, and where the P/E stands against its own ten years.

Nothing here is scored. A reading is flagged only where it crosses a threshold
written in ``[industries]`` beforehand, and a reading that cannot be computed
stays None all the way to the page.
"""

from __future__ import annotations

import math

import pandas as pd

from ..util import clean_float

RETURN_WINDOWS = ("1M", "3M", "6M")
# Member columns a group is read from.
MEMBER_FIELDS = ("name", "weight", "r1M", "r3M", "r6M", "drawdown", "above_ma", "rev30", "rev90", "fwd_pe", "pe_percentile")


def revision(current: float | None, earlier: float | None, reported: float | None = None) -> float | None:
    """A consensus EPS revision in percent, or None where it is not one.

    A percentage off a loss, or off a figure near zero, is not a revision
    (Boeing's came out at -165%), so both ends must be positive. The monitor's
    own figure is preferred when present: it already handles the fiscal-year
    roll-over, which a naive ratio would read as analysts cutting.
    """
    if current is None or earlier is None or not current > 0 or not earlier > 0:
        return None
    if reported is not None and not math.isnan(reported):
        return float(reported)
    return (current / earlier - 1) * 100


def _median(values: pd.Series) -> float | None:
    values = values.dropna()
    return float(values.median()) if len(values) else None


def _count(values: pd.Series) -> int:
    return int(values.notna().sum())


def group_row(frame: pd.DataFrame, settings: dict, *, sector: str, label: str, kind: str,
              with_members: bool) -> dict:
    """The reading for one group; ``frame`` is indexed by ticker, one row per member."""
    n = len(frame)
    no_pe = sector in set(settings.get("no_pe_sectors") or [])
    blank = pd.Series(float("nan"), index=frame.index)
    fwd_pe = blank if no_pe else frame["fwd_pe"]
    pe_pct = blank if no_pe else frame["pe_percentile"]

    returns = {w: _median(frame[f"r{w}"]) for w in RETURN_WINDOWS}
    one_month = frame["r1M"].dropna()
    down_share = float((one_month < 0).mean()) if len(one_month) else None
    rev30, rev90 = _median(frame["rev30"]), _median(frame["rev90"])
    pe_median = _median(pe_pct)
    above = frame["above_ma"].dropna()

    sold_off = None
    if returns["1M"] is not None and down_share is not None:
        sold_off = bool(returns["1M"] <= settings["sold_off_return_pct"] and down_share >= settings["sold_off_down_share"])
    estimates_cut = None
    if rev30 is not None and rev90 is not None:
        estimates_cut = bool(rev30 < settings["estimates_cut_30d_pct"] or rev90 < settings["estimates_cut_90d_pct"])
    cheap = None if pe_median is None else bool(pe_median <= settings["cheap_percentile"])

    ranked = frame["r1M"].dropna().sort_values()
    row = {
        "kind": kind,
        "sector": sector,
        "label": label,
        "members": n,
        "thin": n < settings["thin_below"],
        "weight": clean_float(frame["weight"].sum(), 2),
        "returns": {w: clean_float(v, 2) for w, v in returns.items()},
        "down_share": clean_float(None if down_share is None else down_share * 100, 0),
        "drawdown": clean_float(_median(frame["drawdown"]), 1),
        "above_ma": clean_float(None if not len(above) else float(above.astype(float).mean()) * 100, 0),
        "revision": {"30d": clean_float(rev30, 1), "90d": clean_float(rev90, 1), "names": _count(frame["rev90"])},
        "forward_pe": {"median": clean_float(_median(fwd_pe), 1), "names": _count(fwd_pe)},
        "pe_percentile": {"median": clean_float(pe_median, 0), "names": _count(pe_pct)},
        "worst": ({"ticker": str(ranked.index[0]), "return": clean_float(ranked.iloc[0], 1)} if len(ranked) else None),
        "best": ({"ticker": str(ranked.index[-1]), "return": clean_float(ranked.iloc[-1], 1)} if len(ranked) else None),
        "evidence": {"sold_off": sold_off, "estimates_cut": estimates_cut, "cheap_vs_own_history": cheap},
    }
    if with_members:
        row["member_rows"] = [
            {
                "ticker": str(ticker),
                "name": str(m["name"]),
                "weight": clean_float(m["weight"], 3),
                "returns": {w: clean_float(m[f"r{w}"], 1) for w in RETURN_WINDOWS},
                "drawdown": clean_float(m["drawdown"], 1),
                "above_ma": None if pd.isna(m["above_ma"]) else bool(m["above_ma"]),
                "revision": {"30d": clean_float(m["rev30"], 1), "90d": clean_float(m["rev90"], 1)},
                "forward_pe": clean_float(None if no_pe else m["fwd_pe"], 1),
                "pe_percentile": clean_float(None if no_pe else m["pe_percentile"], 0),
            }
            for ticker, m in frame.sort_values("r1M").iterrows()
        ]
    return row


def scorecard(members: pd.DataFrame, settings: dict) -> dict:
    """{sectors, sub_industries, omitted} from a member frame indexed by ticker.

    Columns: sector, sub_sector and MEMBER_FIELDS. A group smaller than
    ``min_members`` is left out and counted, so the page can say how many names
    no row describes instead of looking complete.
    """
    usable = members[~members["sector"].isin(["Unclassified"]) & ~members["sub_sector"].isin(["-"])]
    sectors = [group_row(frame, settings, sector=name, label=name, kind="sector", with_members=False)
               for name, frame in usable.groupby("sector")]
    subs, left_out = [], []
    for (sector, label), frame in usable.groupby(["sector", "sub_sector"]):
        if len(frame) < settings["min_members"]:
            left_out.append((sector, label, len(frame)))
            continue
        subs.append(group_row(frame, settings, sector=sector, label=label, kind="sub_industry", with_members=True))
    subs.sort(key=lambda r: (r["returns"]["1M"] is None, r["returns"]["1M"] or 0))
    sectors.sort(key=lambda r: (r["returns"]["1M"] is None, r["returns"]["1M"] or 0))
    return {
        "sectors": sectors,
        "sub_industries": subs,
        "omitted": {"groups": len(left_out), "names": int(sum(n for *_, n in left_out)),
                    "examples": [f"{label} ({n})" for _, label, n in sorted(left_out, key=lambda x: -x[2])[:6]]},
    }
