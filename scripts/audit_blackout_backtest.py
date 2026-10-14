"""Exploratory retrospective association, NOT a point-in-time/OOS backtest.

Uses existing artifacts and cached adjusted closes only. Never fetches data,
changes a trading model, or publishes the biased results to the dashboard.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from market_recap.compute.market_state import forward_outcomes
from market_recap.compute.blackout import calendar_momentum
from market_recap.config import ARTIFACT_DIR, CACHE_DIR, PERIOD_TRADING_DAYS, load_config
from market_recap.util import clean_float, write_json


def summarize(outcomes, mask, horizon):
    sample = outcomes.loc[mask].dropna()
    positions = np.flatnonzero(mask.to_numpy() & outcomes.notna().all(axis=1).to_numpy())
    # A second view starts on the first qualifying day, then waits a full
    # horizon before taking another. Daily rows are not independent trades.
    chosen, last = [], -horizon
    for position in positions:
        if position - last >= horizon:
            chosen.append(position)
            last = position

    def stats(frame):
        return {
            "n": len(frame),
            "mean_return_pct": clean_float(frame.ret.mean(), 2),
            "median_return_pct": clean_float(frame.ret.median(), 2),
            "positive_return_probability_pct": clean_float((frame.ret > 0).mean() * 100, 1) if len(frame) else None,
            "mean_worst_drawdown_pct": clean_float(frame.worst_dd.mean(), 2),
            "fall_5pct_probability_pct": clean_float(frame.hit.mean() * 100, 1),
        }

    return {"daily_overlapping": stats(sample), "nonoverlapping_entries": stats(outcomes.iloc[chosen].dropna())}


def momentum_groups(velocity, acceleration):
    """Predeclared sign groups, not optimized thresholds. Turns compare the
    previous priced session; nulls must not be counted as a sign crossing.
    """
    known = velocity.notna() & acceleration.notna()
    prior = velocity.shift(1)
    return {
        'coverage_rising': known & (velocity > 0),
        'coverage_falling': known & (velocity < 0),
        'rising_accelerating': known & (velocity > 0) & (acceleration > 0),
        'rising_decelerating': known & (velocity > 0) & (acceleration < 0),
        'falling_accelerating': known & (velocity < 0) & (acceleration < 0),
        'falling_decelerating': known & (velocity < 0) & (acceleration > 0),
        'upturn_from_nonpositive': known & prior.notna() & (velocity > 0) & (prior <= 0),
        'downturn_from_nonnegative': known & prior.notna() & (velocity < 0) & (prior >= 0),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--low', type=float, default=25, help='low-blackout group: weight below this percentage')
    parser.add_argument('--high', type=float, default=50, help='high-blackout group: weight above this percentage')
    parser.add_argument('--prices', type=Path, default=CACHE_DIR / 'prices/closes-10y.parquet')
    parser.add_argument('--output', type=Path, default=Path('data/probes/blackout-association.json'))
    args = parser.parse_args()
    if not 0 <= args.low < args.high <= 100:
        parser.error('require 0 <= low < high <= 100')
    payload = json.loads((ARTIFACT_DIR / 'positioning.json').read_text())
    b = payload['blackout']
    config = load_config()
    h = config['positioning']['blackout_change_calendar_days'][-1]
    momentum = calendar_momentum(b['dates'], b['share_pct'], b['as_of'], [h])['windows'][0]
    market = next(row['holdings_etf'] for row in config['universe']['indices'] if row.get('primary'))
    price = pd.read_parquet(args.prices)[market].dropna().sort_index()
    price = price.loc[:b['as_of']]  # no outcomes after this artifact's cutoff
    curve = pd.Series(b['share_pct'], index=pd.to_datetime(b['dates']), dtype=float).loc[:b['as_of']]
    curve = curve.reindex(price.index).dropna()
    v = pd.Series(momentum['velocity_pp_per_day'], index=pd.to_datetime(b['dates']), dtype=float).reindex(curve.index)
    a = pd.Series(momentum['acceleration_pp_per_day2'], index=pd.to_datetime(b['dates']), dtype=float).reindex(curve.index)
    groups = momentum_groups(v, a)
    results = {}
    for label in ['1W', '1M', '3M']:
        horizon = PERIOD_TRADING_DAYS[label]
        outcomes = forward_outcomes(price, horizon, 5).reindex(curve.index)
        results[label] = {
            'sessions': horizon,
            'high': summarize(outcomes, curve > args.high, horizon),
            'low': summarize(outcomes, curve < args.low, horizon),
            'all': summarize(outcomes, curve.notna(), horizon),
            'derivative_groups': {key: summarize(outcomes, mask, horizon) for key, mask in groups.items()},
        }
    report = {
        'status': 'exploratory_biased_proxy_not_OOS', 'as_of': b['as_of'], 'market': market,
        'from': curve.index.min().date().isoformat(), 'through': curve.index.max().date().isoformat(),
        'sessions': len(curve), 'zero_share_sessions': int((curve == 0).sum()),
        'thresholds_pct': {'low_strictly_below': args.low, 'high_strictly_above': args.high},
        'momentum_window_calendar_days': h,
        'results': results,
        'limitations': [
            'Current constituents and weights applied retrospectively: survivorship/composition bias.',
            'Earnings dates reconstructed later, not dates known at each historical decision: look-ahead risk.',
            'Missing issuer report history can look like zero blackout. Current coverage is not historical coverage.',
            'Generic earnings minus/plus calendar-day window, not actual issuer policies or repurchase flow; 10b5-1 plans may continue.',
            'About one year, confounded with earnings season and market regime; no credible OOS split or causal attribution.',
            'High/low groups and baseline share market dates. Nonoverlap is within each group, not independence between groups.',
            'No strategy returns, significance claim, threshold optimization or transaction-cost model.',
            'Derivative sign groups are exploratory and unadjusted for multiple comparisons; acceleration is not velocity.',
        ],
    }
    write_json(args.output, report)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
