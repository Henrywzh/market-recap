"""SCENARIOS: what a data release has done to rates and to stocks, measured.

Everything here is a measurement of the past, with its sample size. Nothing
forecasts. The findings that shaped it (and the ones that did not survive):

- A release's surprise moves the 2-year yield reliably (payrolls, ISM, core
  PCE, CPI, claims), so that link is reported with a t-statistic.
- Its effect on the stock market, and on the sectors, is mostly not
  detectable: the daily noise is larger than the effect at 20-60 releases a
  class. The sector ordering after a hot CPI persisted out of sample only
  marginally (a permutation test, since sectors are not independent), and for
  the other drivers not at all. Every figure is shown with its n; a cell
  with too few releases is absent, never filled.
- Betas fixed over a decade explained about 1% of a sector's release-day
  excess return; betas of the last year explain far more once the day's
  rates, credit and oil moves are known. So the live part is a nowcast from
  what has already moved, not a forecast from the surprise.
"""

from __future__ import annotations

import math
import warnings
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from . import themes as T


def robust_scale(values: Iterable[float]) -> float | None:
    """The spread of a surprise series: 1.4826 x the median absolute deviation.
    A series whose deviation is zero (most releases equal the forecast) falls
    back to the standard deviation of its middle 96%; None when it has none."""
    v = pd.Series(list(values), dtype=float).dropna()
    if len(v) < 8:
        return None
    mad = (v - v.median()).abs().median() * 1.4826
    if mad > 0:
        return float(mad)
    trimmed = v.clip(v.quantile(0.02), v.quantile(0.98)).std()
    return float(trimmed) if trimmed and math.isfinite(trimmed) and trimmed > 0 else None


def release_table(rows: list[dict], title: str, *, start: str, exclude: Sequence[tuple[str, str]],
                  days: pd.DatetimeIndex, threshold_sd: float, clip_sd: float,
                  miss_threshold: float | None = None) -> tuple[pd.DataFrame, float | None]:
    """The releases of one TradingView line, one row per release day with its
    surprise (actual less forecast), the surprise in robust standard
    deviations (``z``, clipped) and its class: ``above`` / ``below`` the
    forecast by more than ``threshold_sd`` of them, otherwise ``inline``. A
    series published to one decimal (CPI, PPI) sets ``miss_threshold`` in its
    own unit instead -- half a tick, so any miss counts -- because a surprise
    is 0.1 or 0.2 and a standard-deviation rule would call a 0.1 miss in line. Only days the
    market traded; releases in an excluded window (a month whose surprises are
    in the millions) are left out before the scale is taken."""
    table = T.tv_surprises(rows, rf"^{title}$", "diff")
    table = table[table["released"] >= pd.Timestamp(start)]
    for lo, hi in exclude:
        table = table[~((table["released"] >= pd.Timestamp(lo)) & (table["released"] <= pd.Timestamp(hi)))]
    table = table[table["released"].isin(days)].set_index("released")
    scale = robust_scale(table["surprise"]) if len(table) else None
    if scale is None:
        return table.assign(z=np.nan, cls=pd.Series(dtype=object)), None
    table = table.assign(z=(table["surprise"] / scale).clip(-clip_sd, clip_sd))
    if miss_threshold is None:
        high, low = table["z"] > threshold_sd, table["z"] < -threshold_sd
    else:
        high, low = table["surprise"] > miss_threshold, table["surprise"] < -miss_threshold
    table["cls"] = np.where(high, "above", np.where(low, "below", "inline"))
    return table, scale


def slope_t(x: pd.Series, y: pd.Series, *, min_n: int = 8) -> dict:
    """Change in ``y`` per unit of ``x`` with the t-statistic of the
    correlation, or an absent result under ``min_n`` points."""
    both = pd.concat([x, y], axis=1).dropna()
    n = len(both)
    out = {"slope": None, "t": None, "n": n}
    if n < min_n or both.iloc[:, 0].std() == 0 or both.iloc[:, 1].std() == 0:
        return out
    r = float(np.corrcoef(both.iloc[:, 0], both.iloc[:, 1])[0, 1])
    out["slope"] = float(np.polyfit(both.iloc[:, 0], both.iloc[:, 1], 1)[0])
    out["t"] = r * math.sqrt((n - 2) / (1 - r * r)) if abs(r) < 1 else None
    return out


def class_means(table: pd.DataFrame, outcomes: pd.DataFrame, *, min_n: int) -> dict:
    """{class: {n, outcome: {mean, se}}} on the release days. A class with
    fewer than ``min_n`` releases has its count and no means."""
    joined = table[["cls"]].join(outcomes, how="inner")
    out = {}
    for cls in ("above", "inline", "below"):
        g = joined[joined["cls"] == cls]
        entry: dict = {"n": int(len(g))}
        if len(g) >= min_n:
            for col in outcomes.columns:
                v = g[col].dropna()
                entry[col] = {"mean": float(v.mean()), "se": float(v.std() / math.sqrt(len(v))) if len(v) > 1 else None} if len(v) else None
        out[cls] = entry
    return out


def era_slopes(x: pd.Series, y: pd.Series, breaks: Sequence[str], *, min_n: int) -> list[dict]:
    """``slope_t`` within each era the breaks cut the history into."""
    edges = [None, *[pd.Timestamp(b) for b in breaks], None]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = pd.Series(True, index=x.index)
        if lo is not None:
            mask &= x.index >= lo
        if hi is not None:
            mask &= x.index < hi
        label = f"{lo.year if lo is not None else x.index.min().year}-{(hi.year - 1) if hi is not None else 'now'}"
        out.append({"era": label, **slope_t(x[mask], y[mask], min_n=min_n)})
    return out


def rolling_betas(y: pd.Series, factors: pd.DataFrame, *, window: int, min_n: int = 150) -> dict | None:
    """Least-squares loadings of ``y`` on the factor columns over the last
    ``window`` sessions, the fit's R-squared and its sample size; None when the
    window holds too few complete days."""
    both = pd.concat([y.rename("y"), factors], axis=1).dropna().iloc[-window:]
    if len(both) < min_n:
        return None
    x = np.column_stack([np.ones(len(both)), both[factors.columns].to_numpy()])
    coef = np.linalg.lstsq(x, both["y"].to_numpy(), rcond=None)[0]
    fitted = x @ coef
    resid = both["y"].to_numpy() - fitted
    total = both["y"].to_numpy() - both["y"].mean()
    r2 = 1 - float(resid @ resid) / float(total @ total) if float(total @ total) > 0 else None
    return {"betas": dict(zip(factors.columns, (float(b) for b in coef[1:]))), "intercept": float(coef[0]), "r2": r2, "n": int(len(both))}


def walk_forward_r2(y: pd.Series, factors: pd.DataFrame, *, window: int, step: int, min_scored: int = 250) -> dict | None:
    """Out-of-sample skill of the nowcast: loadings fitted on the ``window``
    sessions before a block of ``step`` sessions, applied to that block's
    factor moves, then rolled forward block by block. The score is
    1 - (squared error / sum of squares of the actual) over every scored day,
    against predicting zero (an excess return has no drift worth predicting).
    Negative means the loadings did worse than saying nothing. None when fewer
    than ``min_scored`` days could be scored."""
    both = pd.concat([y.rename("y"), factors], axis=1).dropna()
    cols = list(factors.columns)
    values, target = both[cols].to_numpy(), both["y"].to_numpy()
    sse = sst = 0.0
    scored = 0
    for t in range(window, len(both), step):
        x = np.column_stack([np.ones(window), values[t - window:t]])
        coef = np.linalg.lstsq(x, target[t - window:t], rcond=None)[0]
        block = slice(t, min(t + step, len(both)))
        predicted = np.column_stack([np.ones(block.stop - block.start), values[block]]) @ coef
        sse += float(((target[block] - predicted) ** 2).sum())
        sst += float((target[block] ** 2).sum())
        scored += block.stop - block.start
    if scored < min_scored or sst <= 0:
        return None
    return {"r2": 1 - sse / sst, "n": scored}


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def persistence(table: pd.DataFrame, excess: pd.DataFrame, *, split: str, min_n: int, permutations: int, seed: int) -> dict:
    """Does the sector ordering of "above minus below the forecast" found before
    ``split`` hold after it? The rank correlation across sectors, with a
    permutation p-value: class labels shuffled across all releases, 'train' and
    'test' differences recomputed. The permutation, not a Spearman p-value,
    because the sectors move together and are not independent samples.
    ``status`` is 'insufficient' when a class has fewer than ``min_n``
    releases in either period: then nothing is tested."""
    # A sector ETF that began after the first releases (XLC, XLRE) has NaN
    # before it: each sector's means use the days it has, and a sector missing
    # from either period is left out of the ranking, not the release.
    joined = table[["cls"]].join(excess, how="inner").dropna(subset=["cls"])
    if joined.empty:
        return {"status": "insufficient"}
    lab = joined["cls"].map({"below": 0, "inline": 1, "above": 2}).to_numpy()
    values = joined.drop(columns="cls").to_numpy(dtype=float)
    train = np.asarray(joined.index < pd.Timestamp(split))
    test = ~train

    def diff(labels: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
        above, below = mask & (labels == 2), mask & (labels == 0)
        if above.sum() < min_n or below.sum() < min_n:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # a sector with no day in the class
            return np.nanmean(values[above], axis=0) - np.nanmean(values[below], axis=0)

    def rho(labels: np.ndarray) -> float:
        p, r = diff(labels, train), diff(labels, test)
        if p is None or r is None:
            return float("nan")
        ok = np.isfinite(p) & np.isfinite(r)
        return _spearman(p[ok], r[ok]) if ok.sum() >= 5 else float("nan")

    counts = {"train_above": int(((lab == 2) & train).sum()), "train_below": int(((lab == 0) & train).sum()),
              "test_above": int(((lab == 2) & test).sum()), "test_below": int(((lab == 0) & test).sum())}
    actual = rho(lab)
    if math.isnan(actual):
        return {"status": "insufficient", **counts}
    rng = np.random.default_rng(seed)
    null = np.array([v for v in (rho(rng.permutation(lab)) for _ in range(permutations)) if not math.isnan(v)])
    if not len(null):
        return {"status": "insufficient", **counts}
    return {"status": "tested", "rho": actual, "p_perm": float((null >= actual).mean()), "null_sd": float(null.std()),
            "permutations": int(len(null)), "split": split, **counts}


def regime(spy: pd.Series, dy10: pd.Series, *, sessions: int) -> dict:
    """The rolling correlation of daily SPY returns with the change in the
    10-year yield. Negative: stocks fall when yields rise (rates drive them);
    positive: they rise with yields (growth drives them)."""
    corr = spy.rolling(sessions).corr(dy10)
    valid = corr.dropna()
    if valid.empty:
        return {"corr": None, "share_negative": None, "since": None, "label": None}
    now = float(valid.iloc[-1])
    return {"corr": now, "share_negative": float((valid < 0).mean()), "since": valid.index[0].date().isoformat(),
            "label": "rates" if now < 0 else "growth", "sessions": sessions}


def _ols_hc1(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Least squares with heteroskedasticity-robust (HC1) t-statistics; None
    when the design is singular or too short."""
    n, k = x.shape
    if n <= k + 5:
        return None
    try:
        xtx_inv = np.linalg.inv(x.T @ x)
    except np.linalg.LinAlgError:
        return None
    coef = xtx_inv @ x.T @ y
    resid = y - x @ coef
    meat = (x * resid[:, None]).T @ (x * resid[:, None]) * n / (n - k)
    se = np.sqrt(np.diag(xtx_inv @ meat @ xtx_inv))
    return coef, np.where(se > 0, coef / se, np.nan)


def release_days(tables: dict[str, pd.DataFrame], hawkish: dict[str, int], spy: pd.Series, dy2: pd.Series,
                 regime_corr: pd.Series) -> pd.DataFrame:
    """One row per day any line was released: the mean hawkish surprise
    (``z``: the robust-scaled surprise, signed so that up is the 'higher
    yields' direction -- a rise in unemployment is dovish), SPY's return, the
    2-year yield's change in bp and whether the day opened in a rates-driven
    market (the stock-yield correlation of the 60 sessions before it,
    negative). Days without a regime reading or a stock return are left out."""
    parts = [(t["z"] * hawkish.get(key, 1)).rename(key) for key, t in tables.items() if "z" in t]
    if not parts:
        return pd.DataFrame(columns=["z", "spy", "dy2", "rates"])
    z = pd.concat(parts, axis=1).mean(axis=1)
    out = pd.DataFrame({"z": z, "spy": spy.reindex(z.index), "dy2": dy2.reindex(z.index), "corr": regime_corr.reindex(z.index)})
    out = out.dropna(subset=["z", "spy", "corr"])
    out["rates"] = out["corr"] < 0
    return out.drop(columns="corr")


def _by_regime(days: pd.DataFrame, x: str, *, min_n: int) -> dict:
    return {name: slope_t(g[x], g["spy"], min_n=min_n) for name, g in (("rates", days[days["rates"]]), ("growth", days[~days["rates"]]))}


def regime_response(days: pd.DataFrame, other_days: pd.DataFrame, *, split: str, min_n: int, permutations: int, seed: int) -> dict:
    """How the stock reaction to a release depends on what was driving the
    market, from the stock-yield correlation known before the day.

    - ``surprise``: SPY's return per standard deviation of hawkish surprise, in
      the rates-driven and the growth-driven days, and the interaction (the
      difference between them) with its HC1 t and a permutation p-value over
      the regime labels; also for the days from ``split`` on.
    - ``after_the_move``: SPY's return per bp of the 2-year yield's change on
      release days, by regime, against the same on other days.
    - ``out_of_sample``: lines fitted on release days before ``split`` and
      scored (R-squared against saying zero) on those after it, one line
      pooled and one per regime.
    Each figure carries its n; a slice too short for a figure is absent."""
    out: dict = {"days": int(len(days))}
    if len(days) < 2 * min_n:
        return {**out, "status": "insufficient"}

    def interaction(frame: pd.DataFrame, shuffle: np.random.Generator | None = None) -> dict | None:
        r = frame["rates"].to_numpy(dtype=float)
        if shuffle is not None:
            r = shuffle.permutation(r)
        z = frame["z"].to_numpy()
        fit = _ols_hc1(np.column_stack([np.ones(len(frame)), z, r, z * r]), frame["spy"].to_numpy())
        return None if fit is None else {"coef": float(fit[0][3]), "t": float(fit[1][3])}

    def block(frame: pd.DataFrame) -> dict:
        both = interaction(frame)
        return {"n": int(len(frame)), "rates_days": int(frame["rates"].sum()), "by_regime": _by_regime(frame, "z", min_n=min_n),
                "interaction": both}

    out["surprise"] = {"all": block(days), "since_split": block(days[days.index >= pd.Timestamp(split)]),
                       "before_split": block(days[days.index < pd.Timestamp(split)])}
    actual = out["surprise"]["all"]["interaction"]
    if actual is not None:
        rng = np.random.default_rng(seed)
        null = [i["coef"] for i in (interaction(days, rng) for _ in range(permutations)) if i is not None]
        out["surprise"]["all"]["p_perm"] = float((np.abs(null) >= abs(actual["coef"])).mean()) if null else None
        out["surprise"]["all"]["permutations"] = len(null)
    moved = days.dropna(subset=["dy2"])
    out["after_the_move"] = {"release_days": _by_regime(moved, "dy2", min_n=min_n),
                             "other_days": _by_regime(other_days, "dy2", min_n=min_n)}
    train, test = moved[moved.index < pd.Timestamp(split)], moved[moved.index >= pd.Timestamp(split)]
    if len(train) >= min_n and len(test) >= min_n and train["rates"].nunique() == 2 and test["rates"].nunique() >= 1:
        def fitted(frame: pd.DataFrame, per_regime: bool) -> np.ndarray:
            line = {flag: np.polyfit(g["dy2"], g["spy"], 1) for flag, g in train.groupby("rates")} if per_regime else None
            pooled = np.polyfit(train["dy2"], train["spy"], 1)
            return np.array([np.polyval(line[bool(r)] if line else pooled, x) for r, x in zip(frame["rates"], frame["dy2"])])
        denom = float((test["spy"] ** 2).sum())

        def score(pred: np.ndarray) -> float | None:
            return 1 - float(((test["spy"].to_numpy() - pred) ** 2).sum()) / denom if denom > 0 else None

        out["out_of_sample"] = {"pooled": score(fitted(test, False)), "by_regime": score(fitted(test, True)),
                                "train_days": int(len(train)), "test_days": int(len(test)), "split": split}
    out["status"] = "ok"
    return out


def event_size(release_days_index: pd.Index, spy: pd.Series, dy2: pd.Series, *, start: str, vol_sessions: int = 20) -> dict:
    """How big a line's release days are against the other days since ``start``:
    the 2-year yield's average absolute move in bp, and SPY's average absolute
    move in units of its own volatility over the ``vol_sessions`` before the
    day (so a stormy month does not make every release look large). Releases
    only count where both are known; None where a side has no days."""
    vol = spy.rolling(vol_sessions).std().shift(1)
    frame = pd.DataFrame({"dy2": dy2.abs(), "spy": spy.abs() / vol}).loc[pd.Timestamp(start):]
    is_release = frame.index.isin(release_days_index)
    rel, other = frame[is_release], frame[~is_release]

    def mean(series: pd.Series) -> float | None:
        v = series.dropna()
        return float(v.mean()) if len(v) else None

    return {"n": int(len(rel.dropna(subset=["dy2"]))), "n_stock": int(len(rel["spy"].dropna())),
            "dy2_release": mean(rel["dy2"]), "dy2_other": mean(other["dy2"]),
            "spy_release": mean(rel["spy"]), "spy_other": mean(other["spy"])}

