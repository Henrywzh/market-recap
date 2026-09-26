"""The decision log, reviewed against what happened.

Each entry in ``config/journal.toml`` is a decision with its reason, written
when it was made: an entry, add, trim or exit; a pass on a name that was
looked at; or an override of the systematic anchor's exposure. The review is
mechanical and uses only prices after the decision date:

- a name decision is judged on the name's return against the index over its
  horizon (``horizon_days``, calendar days). An entry or add was right if the
  name beat the index; a trim, exit or pass was right if it did not.
- an override is judged against the anchor it departed from: the daily
  difference between the exposure held and the anchor's, times the index's
  return, summed over the horizon. Positive means the override added return.

Until a decision's horizon has passed it is open, and only its return so far
is shown. The log is the evidence of judgment; nothing here edits it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

NAME_ACTIONS = {"enter": 1, "add": 1, "trim": -1, "exit": -1, "pass": -1}
ACTIONS = set(NAME_ACTIONS) | {"override"}
MARKET = "SPX"


def _close_on_or_before(series: pd.Series, day: date) -> tuple[pd.Timestamp, float] | None:
    s = series.dropna()
    s = s[s.index <= pd.Timestamp(day)]
    return (s.index[-1], float(s.iloc[-1])) if not s.empty else None


def _return(series: pd.Series, start: date, end: date) -> float | None:
    a, b = _close_on_or_before(series, start), _close_on_or_before(series, end)
    if not a or not b or b[0] <= a[0]:
        return None
    return 100 * (b[1] / a[1] - 1)


def validate(entry: dict, index: int) -> list[str]:
    problems = []
    for field in ("date", "action", "reason"):
        if not entry.get(field):
            problems.append(f"decision {index + 1}: '{field}' is required")
    action = entry.get("action")
    if action and action not in ACTIONS:
        problems.append(f"decision {index + 1}: action '{action}' is not one of {', '.join(sorted(ACTIONS))}")
    if action == "override" and entry.get("exposure") is None:
        problems.append(f"decision {index + 1}: an override needs the exposure actually held")
    if action in NAME_ACTIONS and not entry.get("ticker"):
        problems.append(f"decision {index + 1}: a {action} needs a ticker")
    try:
        date.fromisoformat(str(entry.get("date")))
    except ValueError:
        problems.append(f"decision {index + 1}: date must be YYYY-MM-DD")
    return problems


def review_name(entry: dict, closes: pd.Series, index_close: pd.Series, as_of: date, default_horizon: int) -> dict:
    start = date.fromisoformat(str(entry["date"]))
    horizon = int(entry.get("horizon_days") or default_horizon)
    end = start + timedelta(days=horizon)
    matured = end <= as_of
    stop = end if matured else as_of
    name_ret, index_ret = _return(closes, start, stop), _return(index_close, start, stop)
    excess = None if name_ret is None or index_ret is None else name_ret - index_ret
    sign = NAME_ACTIONS[entry["action"]]
    right = None if not matured or excess is None else (excess > 0) == (sign > 0)
    return {
        "horizon_days": horizon, "horizon_end": end.isoformat(), "matured": matured,
        "return_pct": None if name_ret is None else round(name_ret, 2),
        "index_pct": None if index_ret is None else round(index_ret, 2),
        "excess_pct": None if excess is None else round(excess, 2),
        "right": right,
    }


def review_override(entry: dict, index_close: pd.Series, anchor_exposure: pd.Series, as_of: date,
                    default_horizon: int) -> dict:
    start = date.fromisoformat(str(entry["date"]))
    horizon = int(entry.get("horizon_days") or default_horizon)
    end = start + timedelta(days=horizon)
    matured = end <= as_of
    stop = end if matured else as_of
    held = float(entry["exposure"])
    returns = index_close.dropna().pct_change(fill_method=None)
    window = returns[(returns.index > pd.Timestamp(start)) & (returns.index <= pd.Timestamp(stop))]
    anchor = anchor_exposure.reindex(returns.index).ffill().reindex(window.index)
    anchor_at = _close_on_or_before(anchor_exposure, start)
    if window.empty or anchor.isna().all():
        value = None
    else:
        value = float(((held - anchor.fillna(held)) * window).sum() * 10000)
    return {
        "horizon_days": horizon, "horizon_end": end.isoformat(), "matured": matured,
        "exposure": held, "anchor_exposure": None if not anchor_at else round(anchor_at[1], 3),
        "value_bp": None if value is None else round(value, 1),
        "right": None if not matured or value is None else value > 0,
    }


def checkpoints(entries: list[dict], as_of: date, *, lookback_days: int = 14) -> list[dict]:
    """Checkpoints still ahead, and those passed within ``lookback_days`` (due)."""
    out = []
    for entry in entries:
        for point in entry.get("checkpoints") or []:
            try:
                day = date.fromisoformat(str(point["date"]))
            except (KeyError, ValueError):
                continue
            if day < as_of - timedelta(days=lookback_days):
                continue
            out.append({"ticker": entry.get("ticker") or MARKET, "date": day.isoformat(), "text": point.get("text", ""),
                        "due": day <= as_of, "decision_date": str(entry["date"]), "action": entry["action"]})
    return sorted(out, key=lambda c: c["date"])


def summary(reviews: list[dict]) -> dict:
    def rate(items):
        judged = [r for r in items if r["review"]["right"] is not None]
        return {"judged": len(judged), "right": sum(r["review"]["right"] for r in judged),
                "hit_rate": round(sum(r["review"]["right"] for r in judged) / len(judged), 3) if judged else None}

    by_action = {}
    for action in sorted({r["action"] for r in reviews}):
        by_action[action] = rate([r for r in reviews if r["action"] == action])
    names = [r for r in reviews if r["action"] in NAME_ACTIONS]
    overrides = [r for r in reviews if r["action"] == "override"]
    matured_excess = [r["review"]["excess_pct"] for r in names if r["review"]["matured"] and r["review"]["excess_pct"] is not None]
    return {
        "decisions": len(reviews),
        "open": sum(not r["review"]["matured"] for r in reviews),
        "matured": sum(r["review"]["matured"] for r in reviews),
        "names": rate(names),
        "overrides": rate(overrides) | {"value_bp": round(sum(r["review"]["value_bp"] or 0 for r in overrides if r["review"]["matured"]), 1)},
        "by_action": by_action,
        "mean_matured_excess_pct": round(sum(matured_excess) / len(matured_excess), 2) if matured_excess else None,
    }
