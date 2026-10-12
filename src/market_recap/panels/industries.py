"""INDUSTRIES view: every sub-industry and sector read as the median of its names.

ROTATION says how a group moved against the index, cap-weighted. This view says
what happened to the typical member and beside it the evidence that separates a
fall the estimates explain from one they do not: how many names fell, the drawdown
from the one-year high, the share above the long average, the FY1 EPS revisions
and where the P/E stands against its own ten years. Nothing is scored; see
compute.industries for what a flag means and ``[industries]`` for the thresholds.

Returns and members come from the build's own closes, the same windows as
ROTATION (compute.rotation.WINDOWS). Drawdown and EPS revisions are read from
this session's MONITOR, the forward P/E and its percentile from VALUATION, so a
reading is one definition wherever it appears. An input that did not build
leaves its columns empty and is named in ``missing``; another session's numbers
are never used in its place.
"""

from __future__ import annotations

import pandas as pd

from ..compute import industries as I
from ..compute import rotation as R
from ..util import company_name

# Panels read, each required to be from this session (build.optional_panel).
INPUTS = ("valuation", "monitor")
SETTING_KEYS = (
    "min_members", "thin_below", "ma_sessions", "sold_off_return_pct", "sold_off_down_share",
    "estimates_cut_30d_pct", "estimates_cut_90d_pct", "cheap_percentile", "no_pe_sectors",
)


def _rows(panel: dict | None) -> dict[str, dict]:
    return {row["ticker"]: row for row in (panel or {}).get("rows", [])}


def _member_frame(members: pd.DataFrame, closes: pd.DataFrame, settings: dict, valuation: dict | None,
                  monitor: dict | None) -> pd.DataFrame:
    average = closes.rolling(int(settings["ma_sessions"])).mean().iloc[-1]
    last = closes.iloc[-1]
    # A name with fewer sessions than the average needs has no reading, not "below".
    above = (last > average).where(average.notna())
    returns = {f"r{w}": R.member_returns(closes, R.WINDOWS[w]) * 100 for w in I.RETURN_WINDOWS}
    monitored, valued = _rows(monitor), _rows(valuation)

    records = {}
    for symbol in members.index:
        watch = monitored.get(symbol, {})
        expect = watch.get("expectations") or {}
        value = valued.get(symbol, {})
        records[symbol] = {
            "sector": members.at[symbol, "sector"],
            "sub_sector": members.at[symbol, "sub_sector"],
            "name": company_name(members.at[symbol, "name"]),
            "weight": float(members.at[symbol, "weight"]),
            **{key: series.get(symbol) for key, series in returns.items()},
            "drawdown": watch.get("drawdown_pct"),
            "above_ma": above.get(symbol),
            "rev30": I.revision(expect.get("eps"), expect.get("eps_30d"), expect.get("change_30d_pct")),
            "rev90": I.revision(expect.get("eps"), expect.get("eps_90d"), expect.get("change_90d_pct")),
            "fwd_pe": value.get("pe_forward"),
            "pe_percentile": value.get("pe_percentile"),
        }
    frame = pd.DataFrame.from_dict(records, orient="index")
    numeric = [c for c in frame.columns if c not in ("sector", "sub_sector", "name", "above_ma")]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame["above_ma"] = frame["above_ma"].astype("float")
    return frame


def build(ctx, inputs: dict) -> dict:
    settings = ctx.config["industries"]
    members = ctx.priced(ctx.primary.key).drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
    closes = R.sessions(ctx.closes[members.index.tolist()])
    valuation, monitor = inputs.get("valuation"), inputs.get("monitor")
    frame = _member_frame(members, closes, settings, valuation, monitor)
    card = I.scorecard(frame, settings)
    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "index": {"key": ctx.primary.key, "label": ctx.primary.label, "holdings_etf": ctx.primary.holdings_etf},
        "windows": {w: R.WINDOWS[w] for w in I.RETURN_WINDOWS},
        "settings": {key: settings[key] for key in SETTING_KEYS},
        # Inputs that did not build this session: their columns are empty.
        "missing": [name for name, panel in (("valuation", valuation), ("monitor", monitor)) if panel is None],
        **card,
    }
