# Weak markets and breadth: what the history says

Research note, 2026-10-08. Nothing here is built into the dashboard yet; this is
the evidence a module would be built from. All figures are descriptive.

Question asked: if the market is weak from next Monday, which sectors have held
up and which have not, does the answer depend on what is driving the weakness,
and is the market's strength broad or carried by a few stocks?

## What was used

| Layer | Data | Span | Unit |
|---|---|---|---|
| A. Weekly, long history | Fama-French 12 industries (value-weighted total return), daily | 1926-2026 | 5,259 non-overlapping 5-session weeks |
| B. Drawdown events | quantamental-lab three-index atlas: 208 cycles (DJIA, SPX, NDX) in 131 clusters; 112 clusters have industry returns | 1926-2026 | peak-to-trough, one row per cluster |
| C. Stock level | the 500 current S&P 500 members, closes | 2016-10 to 2026-10 | 502 weeks |
| D. Macro states | FRED: 10Y yield (1962), AAA and BAA (1919), CPI (1947), NBER recession flag; Fama-French factors (1926) | to 2026 | state at the start of each week |

Sources: `three_index_drawdown_atlas_v1` (`cross_asset_performance_long.csv`,
`daily_asset_panel.csv`), `three_index_drawdown_attribution_v1/attribution_master.csv`
and `bond_credit_regime_attribution_v0_1` (`raw_baa10y.csv`), all in
quantamental-lab; the dashboard's own price cache and `artifacts/industries.json`.

A weak week is one of the worst 20% of weeks for the market (the mean of the 12
industries in A, the equal-weighted member mean in C). In A the threshold is
-1.28% a week; in C it is -1.06% (average -3.2% across the 101 weeks).
"Excess" is an industry's return minus that market mean.

Weeks are tagged by what could be seen in the week itself, not by a cause named
afterwards: tech-led (business equipment 2.5 points or more worse than the
market), volatility spike (VIX up 4 points or more, 1990 on), credit widening
(BAA-10Y spread up 10 bp or more, 1986 on). Layer C adds rates up (10Y up 10 bp
or more) and credit by the HYG/LQD ratio (down 0.4% or more).

## Finding 1: the ranking is stable across a century

Weak weeks, 1926-2026 (n = 1,052). Mean excess in points, with the share of weak
weeks in which the industry beat the market:

| Industry | All weak | Share | Pre-1990 | 1990 on | 2010 on |
|---|---:|---:|---:|---:|---:|
| Telecom | +0.89 | 74% | +1.27 | +0.15 | +0.47 |
| Staples | +0.75 | 75% | +0.63 | +0.98 | +1.07 |
| Utilities | +0.70 | 71% | +0.45 | +1.20 | +1.35 |
| Health | +0.47 | 62% | +0.41 | +0.58 | +0.64 |
| Energy | +0.13 | 53% | +0.13 | +0.12 | -0.65 |
| Finance | -0.37 | 42% | -0.28 | -0.54 | -0.40 |
| Manufacturing | -0.57 | 27% | -0.58 | -0.56 | -0.60 |
| Tech / business equipment | -0.84 | 31% | -0.88 | -0.76 | -0.41 |
| Consumer durables | -0.88 | 31% | -0.65 | -1.32 | -2.00 |

Staples, utilities and health care lead and consumer durables, manufacturing and
tech lag in every sub-period. Telecom's lead has faded since 1990. Energy is not
a stable defensive: its sign flips with the driver and the era.

The event layer agrees. Across 112 drawdown clusters, peak to trough:
utilities +3.3 points (84% of clusters), telecom +1.9, staples +1.5, energy +1.2;
tech -2.8 (23%), consumer durables -2.0 (24%). Drawdowns of 10% or more widen
the gaps (utilities +6.0, tech -5.1, durables -4.1).

## Finding 2: the cause changes little, except for a few industries

Weak weeks by what the week looked like:

| Industry | Tech-led (n=150) | Vol spike (n=105) | Credit widening (n=61) |
|---|---:|---:|---:|
| Staples | +1.64 (89%) | +1.61 (83%) | +1.87 (84%) |
| Utilities | +1.39 | +2.15 (85%) | +1.88 (77%) |
| Health | +0.74 | +0.77 | +1.19 (77%) |
| Energy | +0.81 | -0.21 | -0.70 (46%) |
| Finance | -0.21 | -0.87 (34%) | -1.15 (36%) |
| Tech / business equipment | -4.12 (0%) | -1.22 | -0.84 |
| Consumer durables | -0.91 | -2.10 | -2.03 |

Using the atlas's own cause labels (an event can carry several), the ranking is
close to unchanged. The differences that stand out: energy +4.6 points when
inflation is a label (n=26) against +0.5 under growth/labor; durables -5.4 under
inflation; chemicals -1.6 under credit/funding. Labels are written after the
fact and `rates_duration` appears in 92 of the 112 clusters, so a label of
that kind does not separate one event from another.

Layer C (ten years, 101 weak weeks, S&P 500 sectors) gives the same shape:
staples +1.7, utilities +1.4, health +0.6, real estate +0.5; consumer
discretionary -0.8, tech -0.7. By driver, the differences are in the cyclical and
rate-sensitive sectors: consumer discretionary -1.5 and real estate -0.2 when
rates rise; financials -0.7 and -0.8 with credit widening and vol spikes (25% and
17% of those weeks ahead of the market); tech -2.4 when semiconductors lead the
fall (ahead of the market in 6% of those weeks).

Sub-industries in layer C (groups of five or more): packaged foods, electric and
multi-utilities, staples retail, pharmaceuticals, biotech, insurance brokers and
property and casualty insurers were the best in weak weeks; hotels and cruise
lines (-1.9, beta 1.9), regional banks (-1.5), semiconductor equipment (-1.3),
semiconductors (-1.3), asset managers (-1.3, ahead of the market in 20% of weak weeks) the worst.

## Finding 3: the market is narrow now; in ten years of stocks that did not predict weakness

Today (closes to 2026-10-07; index return rebuilt from start-of-window weights,
which matches SPY to within 0.1-1.3 points):

| Window | SPY | Equal-weight | Median stock | Names up | Beat the index | Top 10's share of the index gain |
|---|---:|---:|---:|---:|---:|---:|
| 1M | +1.8% | -2.2% | -3.5% | 32% | 25% | 119% |
| 3M | +3.7% | -0.5% | -3.3% | 40% | 32% | 98% |
| 6M | +15.6% | +8.5% | +1.4% | 55% | 24% | 51% |
| 12M | +17.0% | +19.3% | +5.2% | 59% | 34% | 37% |

Over the last month the index rose because ten names (38% of the index at the
start) rose; the other 490 on net subtracted. Over the quarter the ten supplied
98% of the gain. Two names account for half of the one-month gain. Over twelve months it is broader: the equal-weighted
member mean is ahead of the cap-weighted one. RSP is -2.2% against SPY +1.8% over
a month, IWM -5.4%.

Trend breadth: 48% of members above their 200-day average (64% a month ago; 17th
percentile of the last ten years), 31% above the 50-day, 11% within 5% of their
52-week high, 34% more than 20% below it. The index itself is 0.2% below its high.

Does that predict weakness? Not clearly in this ten-year stock-level sample (462
weeks, equal-weighted member mean as the outcome); the century-long industry-level
proxies in Finding 5 do show a link, of similar direction and larger sample:

| Start-of-week state | Weeks | Share that were weak weeks | Mean next 20 sessions |
|---|---:|---:|---:|
| All | 462 | 19% | +0.9% |
| Share above 200d, lowest third | 153 | 24% | +1.6% |
| Share above 200d, highest third | 152 | 15% | +0.4% |
| RSP minus SPY over 3M, lowest third | 153 | 21% | +0.5% |
| Index near high and share above 200d under 55% | 7 | 29% | +4.5% |

Low breadth goes with a modestly higher chance of a weak week (24% against 15%,
about two standard errors) and with better, not worse, returns over the next month.
Of the 101 weak weeks, 49% began from narrow breadth against 45% of all weeks. They
were deeper (-3.8% against -2.7%) but the sector ranking was the same. The state
the market is in now (index at its high, under half of members above their
200-day) occurred in seven weeks in ten years, too few for any statement.

## Finding 4: 2020 onward on its own

Layer A (Fama-French, data to 2026-07-31), weak weeks by period. Mean excess in
points, with the share of weak weeks in which the industry was ahead of the market:

| Industry | 2010-19 (n=80) | 2020 (n=11) | 2021-26 (n=52) | 2020 on (n=63) |
|---|---:|---:|---:|---:|
| Utilities | +1.53 (84%) | +1.76 (91%) | +1.00 (75%) | +1.13 (78%) |
| Staples | +0.96 (76%) | +1.13 (64%) | +1.22 (81%) | +1.21 (78%) |
| Health | +0.40 (62%) | +1.95 (82%) | +0.74 (81%) | +0.95 (81%) |
| Telecom | +0.55 (69%) | +1.25 (64%) | +0.19 (63%) | +0.38 (63%) |
| Energy | -0.98 (31%) | -4.80 (9%) | +0.73 (60%) | -0.23 (51%) |
| Finance | -0.48 (35%) | -1.15 (18%) | -0.12 (44%) | -0.30 (40%) |
| Tech / business equipment | -0.58 (35%) | +1.26 (73%) | -0.51 (40%) | -0.20 (46%) |
| Consumer durables | -1.19 (21%) | -3.63 (36%) | -2.89 (25%) | -3.02 (27%) |

What carries over: staples, utilities and health care still lead (staples were
ahead in every year from 2020 to 2025; 2026 has four weak weeks so far and is
too short to read), and consumer durables are worse than ever (negative in every
year, -1.8 to -4.3). What changed: tech no longer reliably trails in weak weeks
(2020 was a tech-led rally within a falling market; 2021 on it is -0.5, ahead in
40% of weeks), and energy's sign depends on the year (-4.8 in the 2020 oil
collapse, +0.7 since).

The ten-year stock-level layer says the same for 2020 on (74 weak weeks, S&P 500
sectors): staples +1.9 (ahead in 84%), utilities +1.2, health care +0.8; financials
-0.5 (26%), tech -0.7 (31%), consumer discretionary -1.2 (31%). Real estate led
in 2016-19 (+1.7) and has been flat since (+0.0), consistent with rates being the
driver of its weak-week behaviour. In sub-industries: packaged foods +2.2,
biotech +1.8, pharma +1.6, staples retail +1.5, utilities, insurance brokers and
P&C insurers +1.1 to +1.3 lead; hotels and cruise lines -2.6, regional banks -1.8,
semiconductor equipment -1.4, asset managers -1.3, semiconductors -1.3 trail.

## Finding 5: breadth over a century

Stock-level breadth does not exist for most of this history locally (the lab's
point-in-time stock data starts in 2014). What does exist from 1926 are four
industry-level proxies, each measured at the close before the week starts:

- share of the 12 industries above their own 200-day average;
- share of the 12 with a positive trailing 60-session return;
- small minus big (SMB) over 60 sessions;
- the 12-industry equal-weight mean minus the value-weighted market, 60 sessions
  (positive when the many industries beat the big ones).

Each is ranked against its own past (expanding percentile, so nothing looks
forward) and averaged. Lowest third of the composite is "narrow", highest third
"broad". Industry-level breadth is coarser than counting stocks; it says how many
parts of the market are participating, not how many companies.

Share of weeks that turned out to be weak weeks:

| Period | Narrow | Mid | Broad |
|---|---:|---:|---:|
| 1926-59 | 29% | 21% | 15% |
| 1960-89 | 31% | 19% | 16% |
| 1990-2009 | 23% | 21% | 18% |
| 2010 on | 23% | 17% | 14% |
| All (n = 855 / 2,910 / 1,344) | 28% | 20% | 16% |

Narrow breadth goes with roughly 1.8 times the chance of a weak week and the
direction is the same in all four periods, though the gap has narrowed since
1990. It does not mean a falling market: the mean return over the next 20
sessions is +0.5% from narrow, +0.6% mid, +1.1% broad (except 1926-59, -0.6%
from narrow). Alone, the components differ: share above the 200-day (28% in the
lowest third against 16% in the highest), positive 60-day return (26% against
16%) and cross-industry dispersion (26% in the highest third against 15% in the
lowest) carry the signal; SMB and the equal-weight gap do not (about 20% across
terciles).

Two cautions on reading it. Most low-breadth weeks come after a decline has
begun, so this is largely a trend and volatility effect, not a "narrow rally at
the top" effect. And when the market is within 3% of its 12-month high, narrow
breadth is rare (89 weeks of 2,469) and the odds are 20% against 14-15% for mid
and broad; since 1990 it is 26% (n = 53). That is the state the market is in
today, and the count is too small to lean on.

In weak weeks, the sector tilt is the same in every breadth state but larger when
breadth is narrow, mostly since 1990 (mean excess in points, 1990 on):

| Industry | Narrow (n=70) | Mid (n=213) | Broad (n=72) |
|---|---:|---:|---:|
| Utilities | +1.81 | +1.08 | +0.94 |
| Staples | +1.33 | +0.92 | +0.85 |
| Chemicals | +1.06 | +0.39 | +0.27 |
| Health | +0.64 | +0.75 | +0.01 |
| Finance | -1.08 | -0.41 | -0.41 |
| Tech / business equipment | -0.88 | -0.73 | -0.73 |
| Consumer durables | -2.25 | -1.29 | -0.50 |

Before 1990 the three states look alike. Part of the widening is scale: weak
weeks that start narrow are deeper (average -3.9% against -2.4% when broad), so
every gap is bigger in points.

## Finding 6: breadth crossed with the macro backdrop

Macro states are those known at the start of the week: realised volatility of the
market over 60 sessions (above or below its running median), 10-year yield change
over 60 sessions (1962 on), BAA minus AAA spread change over three months
(1919 on, published with a month's lag), CPI inflation (1947 on, lagged), and
the NBER recession flag (known only after the fact, so it describes the past and
cannot be used as a state).

Share of weeks that were weak weeks:

| Macro state | Narrow | Mid | Broad |
|---|---:|---:|---:|
| High volatility | 28% | 23% | 18% |
| Low volatility | 27% | 18% | 15% |
| Rates falling | 28% | 18% | 16% |
| Rates rising | 27% | 21% | 17% |
| Credit flat | 29% | 16% | 13% |
| Credit widening | 27% | 22% | 17% |
| Inflation under 2% | 25% | 15% | 11% |
| Inflation 4% or more | 31% | 22% | 21% |
| NBER recession (ex post) | 37% | 31% | 24% |
| Expansion | 24% | 18% | 15% |

Narrow breadth raises the odds in every macro state, by about 10 points in most.
Of the macro variables alone, inflation of 4% or more and recession raise the odds
of a weak week more than volatility, rates or credit do. The best case (broad
breadth, inflation under 2%) is 11%; the worst (narrow, recession) 37%.

Sector tilt in weak weeks, breadth by one macro variable, cells with at least 30
weak weeks (mean excess in points):

| State | Weeks | Utilities | Staples | Health | Finance | Tech | Durables |
|---|---:|---:|---:|---:|---:|---:|---:|
| Narrow, rates falling | 71 | +1.72 | +1.04 | +0.38 | -0.97 | -1.05 | -1.70 |
| Broad, rates falling | 58 | +0.97 | +0.37 | -0.36 | -0.36 | -0.62 | -0.14 |
| Narrow, rates rising | 86 | +1.30 | +0.37 | -0.08 | -0.27 | -0.82 | -0.46 |
| Broad, rates rising | 77 | +0.86 | +0.62 | -0.05 | -0.02 | -0.67 | -0.46 |
| Narrow, credit widening | 105 | +0.91 | +0.99 | +0.50 | -0.96 | -0.93 | -1.01 |
| Broad, credit widening | 36 | +0.59 | +0.41 | -0.14 | 0.00 | -0.96 | +0.20 |
| Narrow, high volatility | 155 | +1.37 | +0.77 | +0.34 | -0.63 | -0.94 | -1.20 |
| Broad, high volatility | 90 | +0.68 | +0.76 | +0.09 | -0.39 | -0.87 | -0.30 |

The ranking never changes. What breadth and macro change is the size: finance and
consumer durables lose most when breadth is narrow, especially with falling rates
or widening credit; health care's edge shows up only when breadth is narrow.

How to cut it. Time splits answer "is this stable"; scenarios answer "what
condition am I in". With about 1,050 weak weeks, breadth (three states) by one
macro variable (two or three states) leaves cells of 40 to 150 weeks, which is
about the floor. A three-way cross (breadth by macro by era) drops most cells under
30 and the numbers stop meaning anything. The sensible layout is: breadth by one
macro variable, with the era split shown beside it as a stability check, and n on
every cell.

## What this does and does not support

Supports: if the market is weak, the historical tilt is toward staples, utilities
and health care and away from consumer durables, manufacturing and technology;
the tilt widens with severity; it is steady across eras. With credit widening or
a volatility spike, financials and consumer cyclicals do worse than average and
energy loses its edge.

Breadth and macro: narrow industry-level breadth goes with about 1.8 times the
chance of a weak week across a century and in every sub-period, and with a larger
sector tilt since 1990. It is a measure of how exposed the market is, not a
forecast: forward returns from narrow states are positive on average, and most
narrow states follow a decline that has already started.

Does not support: knowing in advance which kind of week it will be. The driver
tags and the weak-week threshold use the week's own return, so none of this can be
applied before Monday; only the breadth and macro states, which are set at the
prior close, are usable in advance, and they shift odds, they do not name the
week. Today's state (market at its high, narrow breadth) has under 100 weeks of
precedent in a century. A century of industry data cannot say anything about this
year's single-name story (AI capex, the late-September selloff in insurers and
banks), which the factor attribution already covers.

## Caveats

- Industries in A and B are Fama-French groups, not GICS. "Staples" is NoDur
  (food, tobacco, apparel, household), "tech" is business equipment, and the
  groups do not map one to one to the sub-industries in INDUSTRIES.
- A and B compare each industry with the mean of the 12, not with a cap-weighted
  market, so the numbers are relative and sum to roughly zero.
- Layer C uses today's constituents (survivorship) and, for the trend-breadth
  series, today's membership throughout. It has no breadth before 2016. The
  century-long breadth in Finding 5 is industry-level (12 groups), not stock-level;
  stock-level breadth over a longer span would need point-in-time membership, and
  the lab's Nasdaq point-in-time set starts in 2014 and was not used.
- The composite breadth score, the 60-session windows and the macro cut-offs
  (volatility above its running median, yield change above zero, spread change
  beyond 0.05 points, inflation at 2% and 4%) were set before looking at results
  and not tuned. Terciles of the expanding percentile are not exactly equal
  groups. One unit error was caught and fixed during the work (Fama-French factor
  returns are decimals, not percent) and everything above was rerun after it.
- The NBER recession flag is known only afterwards. Moody's AAA/BAA are monthly,
  so the credit state is lagged a month and is coarser than the weekly CDS or
  high-yield spreads a live module would use.
- Thresholds (weak = bottom 20%, flags at 2.5 points, 4 VIX points, 10 bp) were
  chosen before looking at results but not tuned or tested for sensitivity beyond
  the sub-periods shown.
- Weeks overlap in drivers (a vol spike and credit widening often come together);
  cells with n under about 60 are indicative.
- Cause labels in the atlas are ex post and flagged `model_feature_eligible=false`
  by its authors.
- Hit rates and means describe history; they are not a trading rule and carry no
  costs, borrow, or position sizing.

## If this becomes a dashboard module

Not started. Candidates: a weekly classifier showing which driver flags are lit
(rates, credit, vol, tech-led) next to the matching table of historical sector
excess with n and hit rate; and a breadth strip with RSP minus SPY, the top-10
share of the 1M and 3M gain, the share above 50 and 200 days, and 52-week highs
and lows. Anything shown needs n, the era split and the survivorship note beside
it. The analysis scripts are in the session scratchpad, not the repository, and
read quantamental-lab files by absolute path; they would need to move and be
parameterised first.
