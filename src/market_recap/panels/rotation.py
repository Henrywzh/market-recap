"""ROTATION view: GICS sectors against the S&P 500, from closes already pulled.

No extra data: the members, their official weights, their GICS labels and
their closes all come from the shared context. See compute.rotation for how a
basket is built and why the benchmark is rebuilt from the same closes.
"""

from __future__ import annotations

import pandas as pd

from ..compute import rotation as R
from ..util import clean_float

SCHEMES = ("cap", "equal")
# Sessions of daily relative strength the page can chart (the 12M window).
CHART_SESSIONS = R.WINDOWS["12M"] + 1
# Weekly RRG points kept per group: the longest tail the page draws.
RRG_WEEKS = 13
# Enough history for a 12M window plus the RRG's warm-up.
HISTORY_SESSIONS = CHART_SESSIONS + 5 * (RRG_WEEKS + R.RATIO_WEEKS + R.MOMENTUM_WEEKS)
# A sub-industry needs this many members to be read as a group.
MIN_SUB_MEMBERS = 3


def _pct(value: float | None) -> float | None:
    return clean_float(value * 100, 2) if value is not None and pd.notna(value) else None


def _windows(level: pd.Series, bench: pd.Series) -> dict:
    out = {}
    for label, n in R.WINDOWS.items():
        group, base = R.window_return(level, n), R.window_return(bench, n)
        out[label] = {
            "return": _pct(group),
            "excess": _pct(group - base) if group is not None and base is not None else None,
        }
    return out


def _schemes(closes: pd.DataFrame, held: pd.Series) -> dict[str, pd.Series]:
    return {"cap": R.basket(closes, held.reindex(closes.columns)), "equal": R.basket(closes, None)}


def build(ctx) -> dict:
    members = ctx.priced(ctx.primary.key)
    members = members.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
    closes = R.sessions(ctx.closes[members.index.tolist()]).tail(HISTORY_SESSIONS)
    held = R.units(closes, members["weight"].astype(float))
    benches = {"cap": R.basket(closes, held), "equal": R.basket(closes, None)}
    chart_index = closes.index[-CHART_SESSIONS:]
    bench_returns = {s: {w: R.window_return(benches[s], n) for w, n in R.WINDOWS.items()} for s in SCHEMES}
    member_returns = {w: R.member_returns(closes, n) for w, n in R.WINDOWS.items()}

    groups = []
    contributions: dict[str, dict[str, dict[str, float | None]]] = {}
    for sector, frame in members.groupby("sector"):
        if sector == "Unclassified":
            continue
        cols = frame.index.tolist()
        sub = closes[cols]
        levels = _schemes(sub, held)
        entry = {
            "key": sector,
            "label": sector,
            "members": len(cols),
            "weight": clean_float(frame["weight"].sum(), 2),
        }
        for scheme in SCHEMES:
            level, bench = levels[scheme], benches[scheme]
            rs = (level / bench).reindex(chart_index)
            wheel = R.rrg(level, bench).tail(RRG_WEEKS)
            last = wheel.iloc[-1] if not wheel.empty else None
            breadth = {}
            for window, n in R.WINDOWS.items():
                moves = member_returns[window].reindex(cols).dropna()
                base = bench_returns[scheme][window]
                breadth[window] = (clean_float(100 * float((moves > base).mean()), 0)
                                   if len(moves) and base is not None else None)
                weights = R.start_weights(sub, held.reindex(cols) if scheme == "cap" else None, n)
                for symbol in cols:
                    r = member_returns[window].get(symbol)
                    w = weights.get(symbol)
                    value = (w * (r - base) if base is not None and pd.notna(r) and pd.notna(w) else None)
                    contributions.setdefault(symbol, {}).setdefault(scheme, {})[window] = _pct(value)
            entry[scheme] = {
                "rs": [clean_float(v * 100, 3) for v in rs.to_numpy()],
                "windows": _windows(level, bench),
                "breadth": breadth,
                "rrg": [[d.strftime("%Y-%m-%d"), clean_float(r, 2), clean_float(m, 2)]
                        for d, r, m in wheel.itertuples(index=False)],
                "quadrant": R.quadrant(last["ratio"], last["momentum"]) if last is not None else None,
            }
        groups.append(entry)
    groups.sort(key=lambda g: g["weight"] or 0, reverse=True)

    subs = []
    for (sector, name), frame in members.groupby(["sector", "sub_sector"]):
        if sector == "Unclassified" or name in ("-", None) or len(frame) < MIN_SUB_MEMBERS:
            continue
        cols = frame.index.tolist()
        levels = _schemes(closes[cols], held)
        subs.append({
            "sector": sector,
            "label": name,
            "members": len(cols),
            "weight": clean_float(frame["weight"].sum(), 2),
            **{scheme: _windows(levels[scheme], benches[scheme]) for scheme in SCHEMES},
        })

    rows = []
    for symbol, row in members.iterrows():
        if row["sector"] == "Unclassified":
            continue
        rows.append({
            "ticker": symbol,
            "name": str(row["name"]).title(),
            "sector": row["sector"],
            "sub_sector": row["sub_sector"],
            "weight": clean_float(row["weight"], 3),
            "returns": {w: _pct(member_returns[w].get(symbol)) for w in R.WINDOWS},
            "contribution": contributions.get(symbol, {}),
        })

    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "index": {"key": ctx.primary.key, "label": ctx.primary.label, "holdings_etf": ctx.primary.holdings_etf},
        "windows": R.WINDOWS,
        "rrg_weeks": {"ratio": R.RATIO_WEEKS, "momentum": R.MOMENTUM_WEEKS},
        "dates": [d.strftime("%Y-%m-%d") for d in chart_index],
        "benchmark": {scheme: {w: _pct(v) for w, v in bench_returns[scheme].items()} for scheme in SCHEMES},
        "groups": groups,
        "sub_industries": subs,
        "members": rows,
        "min_sub_members": MIN_SUB_MEMBERS,
    }
