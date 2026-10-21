"""Scenario watch: the observable tests behind each named scenario, and the release ladders.

Pure functions: no fetching and no config. A condition reads one measured series
against a threshold and a looser "near" line. ``scenario_states`` joins the
conditions of a scenario into one state a session; ``episodes`` and
``lifecycle`` describe its history and where it stands against its added,
horizon and kill dates. ``release_probabilities`` turns a market strike ladder
into the odds of the three branches of a data release.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

KINDS = ("level", "change_pct", "change_bp")
OPS = ("above", "below")
MATCHES = ("all", "any")
# A FRED series a day behind still joins; a reading is carried no further.
CARRY_SESSIONS = 5
STRIKE_TOLERANCE = 1e-6


def _dated(series: pd.Series) -> pd.Series:
    """The series indexed by datetime, sorted."""
    out = series.copy()
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def _iso(when) -> str | None:
    return None if when is None else pd.Timestamp(when).strftime("%Y-%m-%d")


def measure(series: pd.Series, kind: str, sessions: int) -> pd.Series:
    """The series as a scenario reads it: its level, or its change over ``sessions`` observations.

    ``change_pct`` is a percent change. ``change_bp`` takes the series as a yield
    in percent and returns the change in basis points. A change over a zero base
    is missing, not infinite.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown measure {kind!r}")
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if kind == "level":
        return clean
    if kind == "change_pct":
        out = (clean / clean.shift(sessions) - 1) * 100
    else:
        out = (clean - clean.shift(sessions)) * 100
    return out.replace([np.inf, -np.inf], np.nan)


def condition(values: pd.Series, *, op: str, threshold: float, near: float | None) -> pd.DataFrame:
    """Per reading: whether it meets the threshold, or is near it short of it.

    ``above`` meets from the threshold up and ``below`` from it down; ``near`` is
    the looser line that counts as close. A missing reading is neither.
    """
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    values = pd.to_numeric(values, errors="coerce")
    beyond = (lambda line: values >= line) if op == "above" else (lambda line: values <= line)
    met = beyond(threshold).astype(bool)
    close = beyond(near).astype(bool) if near is not None else pd.Series(False, index=values.index)
    return pd.DataFrame({"met": met, "near": (close & ~met).astype(bool)}, index=values.index)


def scenario_states(conditions: list[pd.DataFrame], match: str) -> pd.Series:
    """Per session, the state of a scenario: triggered, near, quiet or missing.

    The conditions are joined on the union of their dates. Each reading is carried
    forward at most ``CARRY_SESSIONS`` rows; past that a condition has no reading.
    ``all`` needs every condition met (near: every one met or near); ``any`` needs
    one met (near: one near). Missing is set when the conditions have no reading
    to judge the session by.
    """
    if match not in MATCHES:
        raise ValueError(f"unknown match {match!r}")
    if not conditions:
        return pd.Series(dtype=object)
    index = conditions[0].index
    for frame in conditions[1:]:
        index = index.union(frame.index)
    has, met, near = {}, {}, {}
    for i, frame in enumerate(conditions):
        joined = frame.reindex(index).ffill(limit=CARRY_SESSIONS)
        # A carried-forward reading counts as a reading; ``has`` says which sessions have one.
        has[i] = joined["met"].notna()
        met[i] = joined["met"].eq(True)
        near[i] = joined["near"].eq(True)
    has, met, near = (pd.DataFrame(cols, index=index) for cols in (has, met, near))
    if match == "all":
        missing = ~has.all(axis=1)
        triggered = met.all(axis=1)
        close = (met | near).all(axis=1)
    else:
        missing = ~has.any(axis=1)
        triggered = met.any(axis=1)
        close = near.any(axis=1)
    labels = np.select(
        [missing.to_numpy(), triggered.to_numpy(), (close & ~triggered).to_numpy()],
        ["missing", "triggered", "near"],
        default="quiet",
    )
    return pd.Series(labels, index=index, name="state")


def episodes(states: pd.Series, *, merge_gap: int = 5) -> list[dict]:
    """The distinct runs of triggered sessions, oldest first.

    Runs separated by fewer than ``merge_gap`` other sessions merge into one.
    ``sessions`` counts the triggered sessions in an episode, not its calendar span.
    """
    ordered = states.sort_index()
    hits = np.flatnonzero(ordered.eq("triggered").to_numpy())
    runs: list[list[int]] = []  # [first position, last position, triggered sessions]
    for pos in hits:
        if runs:
            gap = pos - runs[-1][1] - 1
            if gap == 0 or gap < merge_gap:
                runs[-1][1] = pos
                runs[-1][2] += 1
                continue
        runs.append([pos, pos, 1])
    return [
        {"start": _iso(ordered.index[first]), "end": _iso(ordered.index[last]), "sessions": int(count)}
        for first, last, count in runs
    ]


def lifecycle(states: pd.Series, kill: pd.Series | None, *, added: date, horizon: date, as_of: date) -> dict:
    """Where a scenario stands on ``as_of``, and its record since it was added.

    Only sessions from ``added`` to ``horizon`` count toward the first trigger, the
    triggered sessions and the kill. A kill (the first True within the window) makes the state
    ``killed`` from that session on. After ``horizon`` a live scenario is ``expired``,
    and its outcome says whether it triggered within the window.
    """
    added_at, horizon_at, now = (pd.Timestamp(d) for d in (added, horizon, as_of))
    raw = _dated(states)
    raw = raw[raw.index <= now]

    killed_on = None
    if kill is not None:
        flags = _dated(kill).fillna(False).astype(bool)
        window = flags.loc[added_at:min(horizon_at, now)]
        hits = window.index[window.to_numpy()]
        killed_on = hits[0] if len(hits) else None

    def effective(day: pd.Timestamp, recorded: str) -> str:
        if killed_on is not None and day >= killed_on:
            return "killed"
        if day > horizon_at:
            return "expired"
        return recorded

    if killed_on is not None:
        state = "killed"
    elif now > horizon_at:
        state = "expired"
    else:
        state = str(raw.iloc[-1]) if len(raw) else "missing"
    previous = effective(raw.index[-2], str(raw.iloc[-2])) if len(raw) >= 2 else None
    changed = previous is not None and state != previous

    if killed_on is not None:
        since = killed_on
    elif state == "expired":
        after = raw.index[raw.index > horizon_at]
        since = after[0] if len(after) else now
    elif len(raw):
        start = len(raw) - 1
        while start > 0 and raw.iloc[start - 1] == raw.iloc[-1]:
            start -= 1
        since = raw.index[start]
    else:
        since = None

    # The record runs from the day it was added to its horizon.
    seen = raw[(raw.index >= added_at) & (raw.index <= horizon_at)]
    triggered_on = seen.index[seen.eq("triggered").to_numpy()]
    first_triggered = triggered_on[0] if len(triggered_on) else None

    if killed_on is not None:
        outcome = "killed"
    elif now > horizon_at:
        hit = first_triggered is not None and first_triggered <= horizon_at
        outcome = "triggered" if hit else "not triggered"
    else:
        outcome = None

    return {
        "state": state,
        "previous_state": previous,
        "changed": changed,
        "since": _iso(since),
        "first_triggered": _iso(first_triggered),
        "triggered_sessions": int(len(triggered_on)),
        "killed_on": _iso(killed_on),
        "outcome": outcome,
    }


def release_probabilities(ladder: list[list[float]], forecast: float | None, *,
                          tick: float | None, band: float | None) -> dict | None:
    """Market odds that a release prints above, in line with, or below its forecast.

    ``ladder`` is ``[strike, p_above]`` pairs: the market probability that the
    release prints above each strike. A discrete series (``tick``, e.g. 0.1 for a
    CPI printed to one decimal) reads "above" as the probability at the forecast
    itself, and "below" as one minus the probability at the strike one tick under
    it. A continuous series (``band``) reads the ladder at the forecast plus and
    minus the band, and is None outside the ladder's strikes. Noisy quotes are made
    non-increasing in strike, from the low strike up, before they are read.
    """
    if forecast is None or (tick is None and band is None):
        return None
    points = sorted((float(s), float(p)) for s, p in ladder if np.isfinite(s) and np.isfinite(p))
    if len(points) < 2:
        return None
    strikes = np.array([s for s, _ in points])
    probs = np.minimum.accumulate([p for _, p in points])

    if tick is not None:
        def at(strike: float) -> float | None:
            hit = np.flatnonzero(np.abs(strikes - strike) <= STRIKE_TOLERANCE)
            return float(probs[hit[0]]) if hit.size else None

        above = at(forecast)
        under = at(forecast - tick)
        below = None if under is None else 1 - under
    else:
        def inside(strike: float) -> float | None:
            if not strikes[0] <= strike <= strikes[-1]:
                return None
            return float(np.interp(strike, strikes, probs))

        above = inside(forecast + band)
        under = inside(forecast - band)
        below = None if under is None else 1 - under

    if above is None or below is None:
        return None
    inline = max(0.0, 1 - above - below)
    return {"p_above": round(above, 3), "p_inline": round(inline, 3), "p_below": round(below, 3)}
