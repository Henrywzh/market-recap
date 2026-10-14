# Buyback blackout: what can be tested

The positioning curve is an earnings-calendar proxy, not observed buyback
flow. It applies current index constituents/weights retrospectively, uses
generic report-date windows and does not preserve dates known at each
decision. Missing issuer history is not audited daily. Approximately one
year covers only a few earnings seasons. It cannot support a credible
point-in-time, causal or out-of-sample strategy test.

`python scripts/audit_blackout_backtest.py` performs an **exploratory,
biased retrospective association** using the existing positioning artifact
and cached adjusted closes. No fetches or dashboard publication. It excludes
future curve dates and incomplete outcome windows, uses shared 5/21/63-session
definitions, and reports mean/median return, positive-return probability,
mean worst drawdown and the probability of a 5% peak-to-trough fall. Both
overlapping daily rows and sequential nonoverlapping entry samples are shown.
Nonoverlap within a group does not make different groups independent.

Default research groups are below 25% and above 50% estimated blackout
weight, not optimized cutoffs. Local output is ignored by git:
`data/probes/blackout-association.json`. Do not read its hit rates as forecasts
or use its thresholds as signals. A serious follow-up needs historical
membership/weights, archived earnings announcements and issuer policy/plan
information over many years, with predeclared tests and a held-out period.

## Changes, velocity and acceleration

The UI now separates level, velocity and acceleration. Difference windows
are calendar days because issuer windows are calendar-day conventions;
`positioning.blackout_change_calendar_days` is their configuration source.
The default is the final configured window (currently 7D), with 1D available
to inspect concentrated issuer entry/exit jumps.

For the estimated basket-weight percentage B and h calendar days:

- Net change: B[t] − B[t−h], percentage points.
- Velocity: (B[t] − B[t−h]) / h, pp/day.
- Acceleration: (B[t] − 2B[t−h] + B[t−2h]) / h², pp/day².

These are backward finite differences, not analytic derivatives of a smooth
function. Missing days or inputs invalidate the window. Positive acceleration
does not imply positive velocity: a falling level may simply be falling more
slowly. Future changes remain separately labelled schedule scenarios; current
derivatives never use future values. The curve's artifact date is explicit,
not relabelled as “today” when the parent preview is newer.

The audit also reports predeclared rising/falling, accelerating/decelerating
sign groups and turns from nonpositive/nonnegative velocity, using the last
configured window. Turns compare successive priced sessions, while the
underlying differences are computed over calendar days before the trading-day
join. No cutoff search, significance claim or dashboard signal is added.

In the cached 2025-10-06 through 2026-10-06 curve (252 priced sessions), the
7D velocity-positive and velocity-negative groups each have only 8 sequential,
group-wise nonoverlapping 21-session windows. Their subsequent SPY median
returns are +2.05% and −0.16%, respectively, with positive-return shares 75%
and 50%. These windows are not independent across groups. This is a biased,
one-year exploratory comparison, not evidence that entering blackout improves
returns or that exiting blackout harms returns. Three-month sign-group samples
shrink to 2–3 windows. Derivatives do not repair the original proxy's biases.

`scripts/preview_blackout.py` adds the derived series to an existing local
artifact without fetching, refreshing dates/weights, or changing the manifest.

Some prearranged repurchase plans can operate in blackout periods, as stated
explicitly in [this issuer's SEC-filed announcement](https://www.sec.gov/Archives/edgar/data/1873951/000119312526239353/xzo-ex99_1.htm).
The current proxy must not be described as the whole market losing its
buyback buyer.
