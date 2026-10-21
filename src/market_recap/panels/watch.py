"""SCENARIO WATCH: scheduled branches and hand-written conditions, checked each build.

Two layers, and neither carries an opinion probability:

- Scheduled. Each SCENARIOS release (and the FOMC decision) due inside
  ``event_days``: the consensus, Kalshi's price of a print above, in line with
  and below it, and what the 2-year yield and SPY did on past releases in each
  branch. Fully automatic; the latest release says which branch it landed in.
- Conditions. Named scenarios from ``[[watch.scenarios]]`` with observable
  triggers fixed when they were added. Each build marks them triggered, near
  or quiet; past the horizon they are listed as expired with whether they
  triggered. How often the same trigger fired over the last decade is context,
  not a forecast.

Pure assembly in ``assemble``; ``build`` fetches the trigger series.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..compute import watch as W
from ..context import YAHOO_URL
from ..sources import fred, yahoo
from ..util import SourceRecord, clean_float, to_iso_date

# Panels WATCH reads, from this session (build passes them as inputs).
INPUTS = ("scenarios", "priced")
MEASURE_TEXT = {"level": "", "change_pct": "{n}-session change", "change_bp": "{n}-session change"}
MEASURE_UNIT = {"change_pct": "%", "change_bp": "bp"}
NOTES = (
    "Scheduled branches: above / below means the print missed the consensus by more than the SCENARIOS class band "
    "(any miss of the published tick for series printed to one decimal). Branch probabilities are Kalshi prices read "
    "off the strike ladder; past moves are SCENARIOS' means on release days, dim where not detected.",
    "Conditions are written by hand and fixed when added; the build only checks them. A threshold moved after the "
    "fact would make the record meaningless, so a changed scenario is a new one.",
    "Near: every needed trigger is met or past its near line. Episodes count distinct runs of the triggered state "
    "(gaps under five sessions merged) over the series' history: how often it happened, not what followed.",
)


def _num(value, digits: int = 3):
    return clean_float(value, digits)


# --- scheduled ---------------------------------------------------------------

def _branch(entry: dict | None) -> dict:
    entry = entry or {}
    dy2, spy = entry.get("dY2") or {}, entry.get("SPY") or {}
    return {"n": entry.get("n"), "dY2": _num(dy2.get("mean"), 2), "dY2_se": _num(dy2.get("se"), 2),
            "SPY": _num(spy.get("mean"), 3), "SPY_se": _num(spy.get("se"), 3)}


def _market_release(releases: list[dict], key: str | None, day: str) -> dict | None:
    """PRICED's Kalshi distribution for this release: the same day, or within two days
    (a market can close the evening before)."""
    if not key:
        return None
    target = date.fromisoformat(day)
    near = [r for r in releases if r.get("key") == key and r.get("release")
            and abs((date.fromisoformat(r["release"]) - target).days) <= 2]
    return min(near, key=lambda r: abs((date.fromisoformat(r["release"]) - target).days)) if near else None


def _release_event(driver: dict, release: dict | None, threshold_sd: float) -> dict:
    nxt = driver["next"]
    miss = driver.get("miss_threshold")
    tick = round(2 * miss, 6) if miss else None
    scale = driver.get("scale")
    band = miss if miss else (threshold_sd * scale if scale else None)
    market = None
    if release:
        probs = W.release_probabilities(release.get("ladder") or [], nxt.get("forecast"), tick=tick,
                                        band=None if tick else band)
        market = {"source": "Kalshi", "median": release.get("value"), "low": release.get("low"),
                  "high": release.get("high"), "open_interest": release.get("open_interest"),
                  **(probs or {"p_above": None, "p_inline": None, "p_below": None})}
    classes = driver.get("classes") or {}
    return {
        "kind": "release", "key": driver["key"], "label": driver["label"], "unit": driver.get("unit"),
        "date": nxt["date"], "time": nxt.get("time"), "forecast": nxt.get("forecast"), "previous": nxt.get("previous"),
        "band": _num(band, 4),
        "band_basis": "any miss of the published tick" if tick else f"{threshold_sd:g} robust SD of past surprises",
        "market": market,
        "branches": {cls: _branch(classes.get(cls)) for cls in ("above", "inline", "below")},
        "latest": driver.get("latest"),
    }


def _fomc_event(meeting: dict, fomc: dict) -> dict:
    kalshi = meeting.get("kalshi") or {}
    buckets = fomc.get("buckets") or {}
    return {
        "kind": "fomc", "key": "fomc", "label": "FOMC decision", "date": meeting["date"],
        "market": {"source": "Kalshi", "outcomes": kalshi["outcomes"]} if kalshi.get("outcomes") else None,
        "branches": {"bp": buckets.get("bp"),
                     **{side: {"n": (buckets.get(side) or {}).get("n"), "SPY": (buckets.get(side) or {}).get("spy")}
                        for side in ("hawkish", "dovish")}},
    }


def scheduled(scenarios: dict | None, priced: dict | None, *, as_of: date, cfg: dict, threshold_sd: float) -> list[dict]:
    """Releases and the FOMC decision due after as_of and within event_days, soonest first."""
    end = (as_of + timedelta(days=int(cfg["event_days"]))).isoformat()
    start = as_of.isoformat()
    releases = (priced or {}).get("releases") or []
    keys = cfg.get("kalshi_keys") or {}
    out = []
    for driver in (scenarios or {}).get("drivers") or []:
        nxt = driver.get("next")
        if driver.get("status") != "ok" or not nxt or not (start < nxt["date"] <= end):
            continue
        out.append(_release_event(driver, _market_release(releases, keys.get(driver["key"]), nxt["date"]), threshold_sd))
    meetings = [m for m in (priced or {}).get("meetings") or [] if start < m.get("date", "") <= end]
    if meetings:
        out.append(_fomc_event(meetings[0], (scenarios or {}).get("fomc") or {}))
    return sorted(out, key=lambda e: (e["date"], e.get("time") or "99:99"))


# --- conditions --------------------------------------------------------------

def _label(spec: dict, series_cfg: dict) -> str:
    name = series_cfg.get("label", spec["series"])
    text = MEASURE_TEXT[spec["measure"]].format(n=spec.get("sessions", 0))
    return f"{name} {text}" if text else name


def _unit(spec: dict, series_cfg: dict) -> str:
    return MEASURE_UNIT.get(spec["measure"], series_cfg.get("unit", ""))


def _trigger(spec: dict, series: dict[str, pd.Series], series_cfg: dict, cfg: dict) -> tuple[dict, pd.DataFrame]:
    """One trigger's reading and its daily met / near frame."""
    raw = series.get(spec["series"], pd.Series(dtype=float))
    values = W.measure(raw, spec["measure"], int(spec.get("sessions", 0))) if not raw.empty else raw
    frame = W.condition(values, op=spec["op"], threshold=spec["threshold"], near=spec.get("near"))
    clean = values.dropna()
    digits = 4 if series_cfg.get("source") == "ratio" and spec["measure"] == "level" else 2
    last = clean.index[-1] if not clean.empty else None
    tail = clean.iloc[-int(cfg["history_sessions"]):]
    return {
        "label": _label(spec, series_cfg), "series": spec["series"], "measure": spec["measure"],
        "sessions": int(spec.get("sessions", 0)), "op": spec["op"], "threshold": spec["threshold"],
        "near": spec.get("near"), "unit": _unit(spec, series_cfg),
        "value": _num(clean.iloc[-1], digits) if last is not None else None,
        "as_of": to_iso_date(last) if last is not None else None,
        "met": bool(frame["met"].loc[last]) if last is not None else False,
        "is_near": bool(frame["near"].loc[last]) if last is not None else False,
        "history": [[to_iso_date(d), _num(v, digits)] for d, v in tail.items()],
    }, frame


def _scenario(spec: dict, series: dict[str, pd.Series], cfg: dict, as_of: date) -> dict:
    series_cfg = cfg["series"]
    triggers, frames = zip(*[_trigger(t, series, series_cfg.get(t["series"], {}), cfg) for t in spec["triggers"]])
    match = spec.get("match", "all")
    states = W.scenario_states(list(frames), match)
    kill_specs = spec.get("kill") or []
    kills, kill_flag = [], None
    if kill_specs:
        kills, kill_frames = zip(*[_trigger(t, series, series_cfg.get(t["series"], {}), cfg) for t in kill_specs])
        kill_flag = pd.concat([f["met"] for f in kill_frames], axis=1).fillna(False).any(axis=1)
    life = W.lifecycle(states, kill_flag, added=date.fromisoformat(spec["added"]),
                       horizon=date.fromisoformat(spec["horizon"]), as_of=as_of)
    known = states[states != "missing"]
    runs = W.episodes(known)
    return {
        "key": spec["key"], "name": spec["name"], "thesis": spec.get("thesis"),
        "added": spec["added"], "horizon": spec["horizon"], "match": match,
        **life,
        "episodes": {"count": len(runs), "since": to_iso_date(known.index[0]) if not known.empty else None,
                     "last": runs[-1] if runs else None},
        "triggers": list(triggers), "kill": list(kills),
    }


def assemble(*, as_of: date, series: dict[str, pd.Series], scenarios: dict | None, priced: dict | None,
             cfg: dict, threshold_sd: float) -> dict:
    """The panel from plain data: trigger series by key (dated index, cut at as_of by
    the caller or here), this session's SCENARIOS and PRICED. Pure: no fetching."""
    cut = {k: s[s.index <= pd.Timestamp(as_of)].dropna() for k, s in series.items()}
    return {
        "as_of": as_of.isoformat(),
        "settings": {"event_days": int(cfg["event_days"]), "history_sessions": int(cfg["history_sessions"])},
        "events": scheduled(scenarios, priced, as_of=as_of, cfg=cfg, threshold_sd=threshold_sd),
        "scenarios": [_scenario(spec, cut, cfg, as_of) for spec in cfg.get("scenarios") or []],
        "notes": list(NOTES),
    }


def _series(ctx, cfg: dict) -> dict[str, pd.Series]:
    """Every configured trigger series: Yahoo closes, FRED readings, then ratios of those."""
    specs = cfg["series"]
    symbols = sorted({s["symbol"] for s in specs.values() if s.get("source") == "yahoo"})
    out: dict[str, pd.Series] = {}
    if symbols:
        closes = yahoo.fetch_closes(symbols, period=f"{int(cfg['history_years'])}y")
        missing = sorted(set(symbols) - set(closes.columns))
        ctx.log.add(SourceRecord("watch_prices", "Closes for the SCENARIO WATCH triggers", YAHOO_URL,
                                 to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                                 status="partial" if missing else "ok",
                                 error=f"no data: {', '.join(missing)}" if missing else None))
        for key, s in specs.items():
            if s.get("source") == "yahoo" and s["symbol"] in closes.columns:
                out[key] = closes[s["symbol"]].dropna()
    for key, s in specs.items():
        if s.get("source") == "fred":
            frame, url = fred.fetch_series(s["id"])
            out[key] = frame.set_index("date")["value"].dropna()
            ctx.log.add(SourceRecord(f"watch_fred_{s['id']}", f"{s.get('label', s['id'])} (FRED)", url,
                                     to_iso_date(frame["date"].max()), rows=int(len(frame))))
    for key, s in specs.items():
        if s.get("source") == "ratio":
            a, b = s["of"]
            if a in out and b in out:
                both = pd.concat([out[a], out[b]], axis=1, join="inner").dropna()
                out[key] = both.iloc[:, 0] / both.iloc[:, 1]
    return out


def build(ctx, *, inputs: dict) -> dict:
    cfg = ctx.config["watch"]
    as_of = date.fromisoformat(ctx.as_of)
    payload = assemble(as_of=as_of, series=_series(ctx, cfg), scenarios=inputs.get("scenarios"),
                       priced=inputs.get("priced"), cfg=cfg,
                       threshold_sd=float(ctx.config["scenarios"]["class_threshold_sd"]))
    payload["unavailable"] = [{"part": name, "reason": f"the {name} panel did not build this session"}
                              for name in INPUTS if inputs.get(name) is None]
    return payload
