# Expectations: what the data we hold can say (todo #21, researched 2026-10-23)

Three kinds of expectation, kept apart as #21 asks: the analyst consensus, the
buy-side "bar" (what holders expect beyond the consensus), and market-implied
quantities. This note records what was tested on data already in the build,
what it found, and what each finding allows on the page. Nothing here is a
signal; each is description unless a later test shows it leads.

## Data audited

| Source | What it holds | History | Usable for |
|---|---|---|---|
| EVENTS per-name history (`artifacts/events/<T>.json`) | per report: Nasdaq calendar EPS consensus and actual, surprise, first-session excess move vs the S&P 500, 5/20-day drift after | 8 reports per name, 499 names, 3,546 reports 2024-02 to 2026-10 | the buy-side bar tests below |
| Consensus snapshots (`data/snapshots/consensus/`) | nightly Yahoo EPS/revenue consensus per period, low/high, analysts, up/down revisions in 30 days | since 2026-09-30 | descriptive now; no pre-report history yet |
| Options snapshots (`data/snapshots/options/`) | nightly straddle, ATM IV, 25-delta skew, OI for ~50 names | since 2026-09-30, with gaps | implied vs realised, once a season accrues |
| Reverse DCF | growth and margin a price implies, under the page's stated WACC, terminal and reinvestment assumptions | computed in the browser per ticker | the implied-growth comparison (needs the solver in Python) |
| Yahoo earningsTrend (`sources/estimates`) | +1y/+2y EPS and revenue estimates and growth | current only | consensus growth beside implied growth |

The Nasdaq consensus is the calendar's figure on the report date, not a
consensus frozen before the report: close to it for most names, but not a
point-in-time record. The nightly snapshots are the frozen record from 2026-09-30.

## Findings (scratch scripts: `scratchpad/exp21/bar.py`, `bar2.py`)

1. **Consensus is a low bar.** 83% of reports beat the EPS consensus; 47% of the
   beats were followed by a fall against the S&P 500 on the first session, 65%
   of the misses. Median excess move: beat +0.39%, miss -1.95%.
2. **The market's bar sat about 3% above consensus.** Median first-session
   excess by EPS surprise: 0-1% beat -1.9% (worse than a 0-1% miss, -1.0%);
   1-2.5% -0.3%; 2.5-5% 0.0%; 5-10% +0.3%; 10-20% +1.3%; over 20% +1.9%. Share
   up crosses one half at a 2.5-5% beat. A surprise coefficient of +0.17 points of
   move per point of surprise (t 9.9, week-block bootstrap), intercept -0.95%.
3. **The run-up into a report does not set the bar.** Beats split by 20-day
   pre-report excess return: no monotone pattern (mean excess +0.1, +0.8, +1.5,
   +0.3, +0.9 low to high; share down 47/45/41/50/49%); the 60-day split is the
   same. In the regression the run-up adds +0.02 (t 1.2). Not usable as a proxy.
4. **A name's own beat-and-fall record reverses, it does not persist.** Among
   beats with three or more earlier beats on record (1,478), names whose earlier
   beats fell more than two thirds of the time had a median +1.2% on the next
   beat; under one third, 0.0%. Correlation of the past mean beat reaction with
   the next: -0.09. A per-name "bar" from past reactions would point the wrong way.
5. **By sector, beats fell most often in IT and Real Estate** (51-52%, median
   about 0) and least in Staples and Communication Services (39-40%, median about
   +1.1%). Two and a half years, so a description of this cycle, not a constant.
6. **The reaction does not carry**: first-session excess and the next 20
   sessions' drift correlate +0.04 (same sign 51%, n 3,487).
7. **Implied vs realised move: not enough yet.** 15 of 54 reports since
   2026-10-01 had a straddle recorded before them (local snapshot gaps); median
   implied 4.3%, median |excess| 2.8%, realised above implied on 20%. The straddle
   spans 2 to 44 days and the excess removes the market, so the two are not like
   for like; an event-implied move (the straddle less ordinary days' variance)
   and a full season are needed before stating anything.

## By sector and sub-industry (scratch: `exp21/groups.py`, `habit.py`)

Breakeven = the EPS surprise at which a straight-line fit of first-session
excess on surprise (both capped) crosses zero; bands are 10-90% of a
week-block bootstrap. It reads higher than the bucket medians above (about 5.5%
for all names against about 3%) because the mean fit is pulled by large moves;
compare groups on the same measure, not the two measures with each other.

| Sector | n | beat rate | median surprise | beats that fell | median miss | slope | breakeven (10-90%) |
|---|---|---|---|---|---|---|---|
| Industrials | 593 | 86% | 4.9% | 46% | -3.4% | 0.22 | 3.9 (1.3-5.5) |
| Consumer Staples | 236 | 86% | 5.2% | 39% | -2.2% | 0.18 | 4.3 (0.8-7.2) |
| Consumer Discretionary | 352 | 75% | 4.6% | 47% | -0.6% | 0.18 | 4.5 (2.3-7.6) |
| Health Care | 421 | 91% | 5.7% | 46% | -7.2% | 0.30 | 6.5 (4.7-8.1) |
| Information Technology | 561 | 84% | 6.5% | 51% | -4.7% | 0.21 | 6.5 (3.9-9.4) |
| Financials | 539 | 84% | 5.5% | 45% | -2.6% | 0.16 | 8.3 (6.8-9.9) |
| Real Estate | 196 | 85% | 2.7% | 52% | -0.3% | 0.00 | none: EPS does not move it |
| Utilities | 215 | 73% | 4.8% | 50% | -0.5% | 0.09 | 5.2 (-0.5-12.0) |

- **The groups differ in how much a surprise moves them more than in where
  the bar sits.** Most breakeven bands overlap; Financials (6.8-9.9) against
  Industrials (1.3-5.5) is the clearest gap. The slope separates more: Health
  Care 0.30 and its misses -7.2%, Tech hardware 0.52 (misses -8.5%), against
  Utilities 0.09 and Real Estate 0.00 -- for REITs and utilities EPS is not
  what the price answers to (FFO, rate base, rates), so a bar in EPS would
  mislead there and should not be shown.
- **Sub-industries (n >= 40; bands are wide, about 6-8 names each):** the
  highest bars are Pharmaceuticals (11.5, 8.4-14.2; 60% of beats fell, misses
  -13.6%), Property & Casualty Insurance (11.5, 7.5-15.4; median surprise 15%:
  the consensus there is habitually far below), Payments (10.2) and Semiconductors
  (10.6, 1.4-26.6; 59% of beats fell, median beat -1.3%). The lowest that are
  measured: Life Sciences Tools, Health Care Equipment, Industrial Machinery,
  Regional Banks (3.4-4.7). Asset managers and exchanges fell on only 37-38% of
  beats. Restaurants, systems software, communications equipment and E&P have
  no measurable slope.
- **The bar is each name's usual beat.** Among 1,778 reports with at least three
  earlier ones for the name (and ten for its sub-industry), all from before
  the report: beats above the name's own median past surprise, median excess
  +1.43% and 60% up (n 905); beats at or below it, -0.70% and 42% up (n 615).
  Against the sub-industry's usual beat: +1.16% / 58% up against -0.41% / 45%.
  Surprise relative to the usual beat explains a little more of the reaction
  than the raw surprise (R2 0.049-0.057 against 0.045), and all of them little:
  EPS surprise is about 5% of the first-session variance; revenue, guidance and
  the call carry the rest.

## What this allows on the page

- **The bar, per report card, as the name's usual beat:** "Usual beat: +6.1%
  (median of its last 7 reports). Beats above a name's usual beat rose on 60%
  of days, beats below it on 42%." Then the sub-industry's line where it has a
  measurable slope (n, beats that fell, median miss), and no EPS bar at all for
  REITs and utilities. Built from earlier reports only, recomputed each build;
  the usual beat is a count of what happened, not a whisper number. (The run-up
  and the beat-and-fall record stay out: findings 3 and 4.)
- **Consensus quality, from the snapshots now:** revision breadth (Yahoo's own
  up/down counts in 30 days over analysts) and dispersion ((high - low) / |mean|)
  per name and rolled up per sector and theme, with the frozen pre-report
  consensus kept per report. Whether breadth or dispersion before a report
  changes the reaction can only be tested once the snapshots span a season or
  two (from about 2027-02).
- **Implied growth against consensus growth:** port the reverse-DCF solver to
  Python (the page's assumptions, unchanged) and set the growth today's price
  implies beside the +1y/+2y consensus growth and the name's own past growth.
  Two rows, never one blended score. Needs the port and a check that the two
  solvers agree.
- **Market-implied, macro:** JUST OUT can show a release against both the survey
  forecast and the Kalshi ladder's median where PRICED PATH holds one; the
  before/after of the policy path around FOMC and CPI from the recorded quotes.
- **Not now:** any score or rank built from these, the pre-report run-up as a
  bar, a per-name beat-and-fall bar, and implied-vs-realised statistics before a
  full season with event-implied moves.

## Proposed order

1. Report-card and event-card line for the bar: the name's usual beat and the
   sub-industry's reaction profile (by-sector section), recomputed each build
   from the EVENTS history so it updates as reports accrue.
2. Consensus quality from the snapshots (breadth, dispersion, frozen pre-report
   record), per name and rolled up.
3. Reverse-DCF port and the implied vs consensus growth rows.
4. After a season of snapshots: test breadth, dispersion and event-implied move
   against the reaction, with the week-block bootstrap used here.
