# TODO

Open items with the evidence gathered so far. Each needs a decision before
work starts; nothing here is scheduled.

## 1. RISK anchor: which risk model the card shows

The anchor card shows frozen v1 (`compute/anchor.py`). Research in
quantamental-lab questions whether it should stay the reference. Write-up:
`quantamental-lab/docs/tactical_slow_bear_v1.md` (script
`scripts/evaluate_tactical_slow_bear_v1.py`; both uncommitted in that repo).

Common replay, SPY 2001-11 to 2025-03, fed funds cash, 5 bps. Cells are
CAGR / Sharpe / maximum drawdown.

| Book | Result | Average exposure |
|---|---:|---:|
| Buy and hold | 9.07 / 0.552 / -55.2 | 100% |
| Frozen v1 | 5.36 / 0.723 / -15.4 | 52% |
| Copper/oil gate only | 9.35 / 0.677 / -35.0 | 77% |
| Tactical book + B (bear floor) | 9.63 / 0.760 / -26.6 | 75% |
| Tactical + B, times copper/oil | 8.49 / 0.816 / -25.8 | 59% |

What is known:

- Frozen v1's low CAGR comes from its 12% volatility target (binding 61% of
  days) and its drawdown ladder, not from the copper/oil gate. The ladder
  locks itself: in the year after 2020-03-23 SPY rose 79% while v1 averaged
  21% exposure. v1 was built as an overlay for the earnings sleeve, not for
  index timing.
- Tactical + B passes every check run: the S&P 1958–93 holdout, leave one
  episode out (7/7), costs 0–25 bps, a two-session lag, neighbour settings
  and four non-US indices. It is not shallower than v1 in 2002, 2008 or
  2020.
- Copper/oil alone has timing value over 2001–2025, but it all comes from
  2002, 2008 and 2022. It adds nothing since 2016, is off on 45% of days
  (2013 91%, 2021 93%), and has no history before 2000 to test on. WRDS has
  no Datastream access, so a longer copper series has to come from
  elsewhere.
- Fast crashes (1987, 2020, 2025-04) are untouched by every slow rule.

To decide:

- Show tactical + B, frozen v1, or both side by side.
- Whether to fix v1's ladder self-lock or retire v1 as the reference (the
  latter also changes quantamental-lab's CLAUDE.md).
- Whether the copper/oil gate is kept, pending a pre-2000 test.

## 2. Real-time news by theme

Dropped 2026-10-12: not wanted. The number stays so that the other items keep
theirs.

## 3. Trading layer

Scope chosen 2026-09-29: US stocks and index ETFs, overnight to weeks. Items
1–3 are deliberately deferred at the user's request; Trade Desk has no
account connection, messages or trade journal. Items 4–9 are implemented
within the free-source coverage limits below.

First, the workflow gaps:

1. **Holdings and portfolio risk.** Gross exposure, beta-adjusted SPX
   equivalent, sector concentration, risk to stops, day P&L attribution, and
   exposure against the RISK anchor ("model 50%, you 85%"). Positions from
   the local Futu OpenD. Private only: Cloudflare Access or local.
2. **Alerts.** Push instead of pull: SPX crossing its 200-day, a risk tile
   crossing its threshold, a holding moving after hours, a new headline on a
   tracked theme, the day before an earnings date. Telegram bot or email,
   checked by a Worker cron (GitHub Actions schedules are not punctual).
3. **Trade plan and review.** Attached to each trade, not a market journal:
   thesis, stop, target and catalyst date at entry; outcome computed at exit;
   hit rate by trade type once there are a few dozen.

Second, entries and exits:

4. **Levels and expected range.** Trade Desk: chart and price ladder on
   traded closes (20/50/200-day averages, prior 20/60-session and 52-week
   closing extremes, ±2 ATR), gap, ATR. The straddle range appears only with
   a same-session option snapshot; none has been captured yet.
5. **Pre-market and overnight.** ES/NQ, Asia/Europe, and a pre/post-market
   scan of the top 30 S&P 500 weights plus the watchlist. Not a whole-market
   mover feed.
6. **Position-size calculator.** Stop risk, position limit and dollar-volume
   caps with a 2× ATR stop shortcut; spread is a manual assumption.

Third, flows and positioning (all on RISK → POSITIONING):

7. **Who is forced to trade.** FINRA short interest, trend-follower flip
   levels, and the share of S&P 500 weight in an estimated buyback blackout
   (30 days before to 2 days after each report; a convention, not company
   policy).
8. **Insider buying.** Strict Form 4 purchases for every S&P 500 / Nasdaq-100
   issuer from EDGAR's daily index, clusters and the largest buys. Each build
   reads at most 1,500 new filings, so the 90-day window fills over about four
   nights; the page shows coverage. No alpha claim (the quantamental-lab
   cross-universe gate is blocked).
9. **Signal scorecard** (Trade Desk). Forward returns after anchor states
   (since 1993), Fear & Greed extremes (since 2024) and the trend proxy,
   against any day. Descriptive, in-sample. Blackout, insider and implied-
   range signals need archived daily history before they can be scored.

## 4. From the reference dashboard (2026-09-29)

Its latest MACRO and SECTOR ROTATION tabs were compared with this site. The
content is already here: the commodity table (same instruments, DXY instead
of UUP), HY OAS, NFCI and the OFR stress index (on RISK, with longer history
from the archive), and the RS table with 1M/3M/6M/12M, breadth and quadrant
(here also the rotation graph and member contributions). It prices from
Twelve Data rather than Yahoo.

Taken (2026-09-29): a 6M / 1Y / 3Y / 5Y / MAX range switch on the history
charts (RISK core series, anchor, Fear & Greed; yields over time, commodity
and inflation charts on RATES & MACRO), and filled state tags (rotation
quadrant, anchor gates, Fear & Greed band, technical verdicts).

## 5. Catalysts by theme, and the event card after hours

Done (2026-09-30): the event card, read-through and index impact, and the
per-name timeline (see `docs/information_architecture.md`, Ticker page).
Open:

- **Theme calendars: built 2026-09-30** (CATALYSTS → THEMES, six groups;
  CLOUD and SEMIS carry industry data). Since added: Samsung / SK hynix
  (DART) and TSMC / ASML (6-K) report history, Korea's 1st-of-month trade
  release, NVIDIA Data Center revenue and capex guidance from the releases,
  the sector x day earnings heat map and theme tags on TICKER; bank report
  history now reaches back past SEC's one-year recent block. Still open:
  Samsung's early-quarter preliminary guidance (KRX KIND, not DART), DRAM
  contract prices (no free source), the 10-day export prints (needs a
  data.go.kr key), capex guidance given only on calls (MSFT, GOOGL, AMZN),
  and industry data for energy, banks, consumer and housing (mostly FRED).
- **Theme calendars (original plan).** Groups defined in config by what moves together,
  not by GICS sector (memory/semis, hyperscaler capex, banks, energy,
  consumer, health care, industrials/transport, housing). Each group: its
  bellwether reports (including foreign ones that file no 8-K, e.g.
  Samsung's preliminary results, SK hynix, TSMC), and its industry data
  (Korea's exports on the 1st and the 1-10 / 1-20 day prints, TSMC monthly
  revenue around the 10th, DRAM contract prices at month end, SIA/WSTS
  sales). Each industry series needs its own free source checked first.
- **Sector × day heat map** of index weight reporting over the next three
  weeks (from CATALYSTS alone; no new source).
- **After-hours move on the card.** The live Pages Function could quote
  the evening's reporters, so the outcome is visible before the next build.
- **Implied vs realised scorecard** over a season: the per-report implied
  move is now kept on each timeline report where the options snapshot has
  that afternoon; a season-level table needs a few weeks of snapshots.

## 6. Paper to study: Asymmetric Reversals (NBER w35840, October 2026)

Baldi-Lanfranchi, Collin-Dufresne and Daniel. Only the abstract has been
read: a stock's return splits into SYS (systematic risk and public
information releases, which continues) and RES (an orthogonal residual, which
reverses); positive RES shocks take much longer to reverse than negative
ones; a factor built on that (AIR) absorbs idiosyncratic volatility and
several short-horizon anomalies. The NBER page gives no sample, universe,
frequency, horizon or SYS/RES construction; read the PDF for those.

A rough check on this site's data (2026-10-07, not committed): the current 503
S&P 500 names over ten years, return minus market and sector-ex-self, equal
weighted quintiles. Next-week residual: losers +0.04%, winners -0.04%, spread
+0.08% a week (t 1.1). Next month: +0.18% (t 0.6). The sign is right, the size
is small, and no asymmetry shows. It is not a test of the paper: the residual
is cruder than SYS/RES, the universe is large caps with survivorship bias.

To decide, after reading the paper:

- Whether SYS (the part tied to public information) can be built from what the
  site already has: earnings releases, EPS revisions, the event cards.
- Whether the INDUSTRIES "sold off, estimates held" screen should be read as
  a RES-style signal and scored forward, which needs archived daily history.
- Whether a wider universe than the S&P 500 is available for a fair replication.

## 7. FTSE 100 as a second index (2026-10-08)

Idea: price, sector rotation and breadth for the 100 UK names, as NDX is
handled (`[[universe.indices]]`). Nothing built; nothing has been tested yet
beyond the Yahoo `.L` charts of 28 names.

What is known:

- Constituents: Wikipedia's FTSE 100 page has a 100-row table (company, EPIC
  ticker, ICB sector) listing the 1 October 2026 changes; `sources/wikipedia.py`
  does the same for the S&P 500. Community-edited, so check the row count.
- Weights should come from the issuer's file, as the repo does for SPY and
  QNDX. iShares Core FTSE 100 is the candidate; `sources/ishares.py` is wired
  to the US site and whether the London fund downloads in the same shape is
  untested.
- Prices: Yahoo `.L` quotes are in pence (GBp), not pounds; a USD view needs
  GBP/USD.
- Classification is ICB, one level, no sub-industry. 100 names over about 25
  sectors is about 4 each, so most groups fall under `min_members` and
  `thin_below`: INDUSTRIES would work at sector level only.
- Open: EPS revisions, forward P/E and its own-history percentile come from
  US-filer sources. No free source for UK estimates has been checked.

To decide: build the price layer first (constituents, weights, prices,
rotation, breadth) and look for a UK estimates source before promising the
valuation columns. The same pattern would extend to FTSE 250 or the euro area.

## 8. Implied move on the event card (2026-10-09)

The card shows `none in snapshot` for most reporters. Two causes found, and
a source that can fill in the past.

- **Expiry gap.** `compute.options.select_expiries` picks the nearest expiry
  plus the ones around fixed targets (`target_days`), not the first expiry
  after each reporter's date. JPM reports 13 Oct and needs 16 Oct; the
  snapshot holds 9 Oct, 30 Oct, 6 Nov. `build_universe` already knows who
  reports; pass each reporter's date through to the expiry choice.
- **Stale snapshot.** The 6 Oct build used the 30 Sep snapshot while the
  `snapshots` branch had options through 7 Oct. Check what
  `snapshot_store.latest_options_summary` takes and why.
- **No history from Yahoo.** Free chains are current only; our own snapshots
  start 30 Sep. Past implied moves cannot be fetched from yfinance.
- **Alpaca (paper key, free) can rebuild them.** Tried on JPM, PEP, JNJ,
  UNH, GS, C: 47 of 48 reports back to Oct 2024. Method: spot at the close
  before the reaction session, the first expiry with contracts on or after
  it, the strike nearest spot, call + put daily-bar close / spot. Expired
  contracts are listed by `/v2/options/contracts?status=inactive`; prices from
  `/v1beta1/options/bars`. Caveats: bar close is the last trade, not a mid
  (six of 48 had under 20 contracts: PEP once traded 1); expiries sit 1-4
  days past the report, so the figure carries a few ordinary days; the
  paper-account data policy may change.
- Over the 41 liquid ones: mean implied 4.9%, mean |move| 3.8%, move beyond
  implied 11 times, median |move| / implied 0.75. Six large caps, not a
  market result.

Proposed order: (1) snapshot the first expiry after each reporter's date and
fix the stale-snapshot read, no new secret; (2) local script backfilling the
straddle per past report into `events/{SYM}.json` history (drop under 20
contracts, show days to expiry), drawn beside the reaction bars; (3) event
premium = short expiry IV less the next-month IV, from the snapshots' multi-
expiry `atm_iv`; (4) IV level and percentile once the snapshots hold 2-3
months. Open: whether to put the Alpaca key in GitHub secrets so the nightly
build can use it; otherwise it stays a local script. Futu OpenD untested.

## 9. THEMES data signals: do they lead price? (2026-10-10)

The THEMES status board (60108f2) reads price (50-day line, relative
strength), estimate revisions and own-history valuation. It has no row for
the data behind a theme: capex, exports, inventories, orders, the series that
would say a theme's demand is improving before the price shows it.

Do not build the row first. Test whether it carries information:

- **Pick series per theme** from `config/dashboard.toml` ids only (FRED or
  TradingView): e.g. semis -- billings/shipments, ISM new orders; housing --
  permits, starts, new-home sales, mortgage applications; banks -- loan
  growth, deposit costs, the yield curve; energy -- inventories, rig count.
  A series with a hard-coded id in a builder is a bug.
- **Direction, not level.** Improving / deteriorating from the latest change
  against its own noise (robust scale, as `compute/scenarios.robust_scale`),
  with the release date and n shown. "Not detected" is a result.
- **The test, before any signal ships.** Does the direction of the series
  today predict the theme's excess return over the next 1-3 months, out of
  sample (fix a split, as `scenarios.persistence`)? Revisions and releases
  overlap in time and themes are not independent, so use a permutation test,
  not a p-value from the regression. Report per theme with n; a theme whose
  series do not lead price shows no data signal rather than a weak one.
- **Rollup**: count of improving / deteriorating series per theme on the
  board, only for themes whose series passed. Release lag matters: use the
  value known on the date, not the revised one (FRED vintages / ALFRED where
  the series is revised).

## 10. SCENARIOS to sub-industries (researched 2026-10-11, not built)

Scratch tests on 28 industry ETFs plus the 11 sector funds, 2008-2026
(scripts were in the session scratchpad). What held and what did not:

- **The page's nowcast R-squared is in sample.** Fitted on the prior year and
  scored on the next month, month after month since 2012, the median ETF
  scores 0.03. Only the commodity- and rate-linked ones carry real skill:
  XOP 0.32, XLE 0.31, OIH 0.29, GDX 0.20, XLP 0.16, XLU 0.12, XME 0.11,
  REITs 0.08-0.09; banks (KRE/KBE) about 0.06; XLK 0.03, XLF 0.03, XLI -0.01,
  XRT -0.03. **Done 2026-10-11**: the page showed an in-sample R-squared; an
  out-of-sample version was tried (rows under 0.03 muted) and judged not
  useful, so the nowcast card was removed. `compute/scenarios.walk_forward_r2`
  and `rolling_betas` stay, tested, unused by the page.
- **Shrinking an industry's betas toward its parent sector's does not help**
  (mean 0.050 unshrunk, 0.046-0.051 shrunk). The earlier plan to use shrinkage
  is dropped.
- **Against its parent sector** an industry's nowcast skill is smaller still
  (mean 0.03): real only for OIH 0.13, XOP 0.08, GDX 0.19, XME 0.08, REITs.
  Semis, software, biotech, retail, transports, defence: nothing beyond the
  sector.
- **Surprise ordering, 41 series, split 2022-01-01, 2000 permutations**:
  payrolls rho 0.64 (p 0.004; 23 hot / 8 cool releases after the split),
  core CPI 0.46 (p 0.036), hourly earnings 0.42 (p 0.07); the other eight
  drivers show nothing or reverse. Eleven drivers tested, so only payrolls
  clears a Bonferroni line (0.0045), narrowly. The payrolls ordering is
  largely the funds' oil and credit loadings (rank correlation with those
  0.50-0.51), and core CPI's is high-beta funds doing worse (-0.33 with market
  beta): an industry adds nothing the factor loadings do not already say.
- **Proposed scope**: the nowcast card is gone, so there is no row to extend.
  What remains of this item: sub-industry columns in the release-class tables
  and sector bars, payrolls and core CPI orderings only, labelled as marginal.
  No new classification of releases.

## 11. Weak-market / breadth module (researched and built 2026-10-11: MARKET STATE on INDICES)

Breadth from price series with no survivorship (RSP/SPY, IWM/SPY, the share of
the 11 sector funds above their 200-day line), 2009-2026, forward 63-session
outcomes, 95% intervals from a moving-block bootstrap (63-day blocks):

- **Narrowness alone does not predict.** RSP lagging SPY by over 2 points
  in 3 months: forward 63-day return +1.0 points vs other days (interval -1.4
  to +3.8), forward worst drawdown 1.5 points deeper (-4.0 to +0.5). IWM
  lagging by over 3 points: nothing.
- **Narrow and at the high** (RSP lagging, SPY within 5% of its high; 550
  days): return -2.1 points (-4.8 to +0.3), drawdown 1.5 deeper (-4.6 to +0.7).
  Suggestive; not detected. By period: 2009-16 60 days (-0.4 return), 2017-26
  490 days (+2.1 vs +4.1 elsewhere).
- **What does carry information is volatility**: VIX above 25, sector breadth
  below half, or SPY 10% off its high all go with *higher* 63-day returns
  (+4 to +5 points, intervals above zero) and a *deeper* worst drawdown
  (-1.6 to -1.9) and more drawdowns of 5% or worse (+0.23 to +0.30 in
  probability). That is a risk state, not a direction call.
- Sector breadth below half *and* SPY near its high: 45 days in 17 years.
- **Now (2026-10-09)**: SPY 0.1% from its 252-day high; 5 of 11 sector funds
  above the 200-day line, 3 above the 50-day; RSP-SPY -4.2 points over 3
  months; IWM-SPY -8.5; VIX 14.8.
- **Proposed module**: a state card (the numbers above, each with how many days
  in history looked like it), a plain count of such days and what followed with
  the interval, and the statement that no direction is detected. Constituent
  breadth (advancing share, new highs) is already partly in MARKETS
  (`breadth_by_sector`); it has survivorship in any backtest, so it stays
  descriptive.

## 12. Pre-release and post-release features per driver (researched and built 2026-10-11: SCENARIOS regime card and release-day size)

Per-day SPY, 2016-2026, one observation per release day (drivers released
together averaged):

- **Release days are not much noisier for stocks.** |SPY| scaled by the
  prior 20 days' volatility: 0.76-1.00 on release days vs 0.80 on others; only
  payrolls reaches 1.00 (about +25%, 2.9 standard errors). Rates are:
  |2Y move| 5.8 bp on payrolls days and 5.4 bp on CPI days vs 3.4 other days.
  So a "pre-release expected move" belongs on yields, not stocks.
- **The sign of the stock reaction depends on the regime**, as you suspected.
  The pre-day 60-session correlation of SPY with the 10Y yield is negative now
  (-0.40, "rates drive stocks"). Per sd of hawkish surprise: growth regime
  +0.05 points (t 1.6), rates regime -0.06 (t -1.3); the difference -0.116
  (t -1.74, permutation p 0.066). Since 2022 -0.25 (t -2.1, 494 release days);
  before 2022 -0.04 (t -0.5). Borderline, concentrated after 2022.
- **Post-release (rates already moved)**: SPY per bp of 2Y move on release
  days is -0.024 in the rates regime (t -3.4, 360 days) and +0.039 in the
  growth regime (t 5.7, 768 days). Fit before 2022 and scored on 2022 onward,
  the regime-specific line scores R-squared -0.02 (pooled -0.27): the sign is
  right, the size is too small to forecast a day.
- **Proposed**: show the regime and the two conditional slopes with their n on
  each driver's detail; for the next release: the typical 2Y move, not a stock
  forecast. Do not show a stock-direction call for any driver.

Other regime variables tried for the same split (2026-10-11, 1,128 release days,
hawkish surprise x flag on SPY, HC1 t and a 500-shuffle permutation p; all known
the day before): VIX above 20 (p 0.78), VIX above its 1-year median (0.72),
realised volatility above its median (0.55), market 5% off its high (0.16), core
CPI over 3% / 2.5% year on year (0.91 / 0.75), Fed hiking / cutting over 6
months (0.45 / 0.51), 2-year yield rising over 6 months (0.35): none. Only the
rate level does something: 10-year above 4% (interaction -0.19, t -2.4, p 0.002)
and an inverted curve (-0.15, p 0.028), but both hold almost only from 2022 on
(no days before it), agree with the rates-driven flag at correlation 0.5, and
cannot be told apart from "the 2022-onward period". Twelve tried: only p under
0.004 would count. HY spread could not be tested (FRED serves about 3 years of
it). Conclusion: keep the one regime variable; more would split 1,128 days
(roughly 200 separate stretches) into cells too small to read.

Window check for the stock-yield correlation (2026-10-11, same 1,128-ish release
days, windows of 20 to 250 sessions, 500 shuffles each): the rates-driven minus
growth-driven difference is negative at every window (-0.03 to -0.17 per sd) but
its strength is not stable: permutation p 0.006 (20d), 0.020 (30d), 0.110 (40d),
0.052 (60d, the page), 0.020 (90d), 0.132 (120d), 0.614 (180d), 0.008 (250d).
From 2022 on it is -0.24 to -0.29 at 20-90 and 250 sessions, -0.08 to -0.12 at
120-180. The fit-before-2022, scored-after R-squared of the regime lines is
-0.15 to +0.01 at every window. Today reads rates-driven at every window
(correlation -0.31 to -0.56). Reading: the sign is robust, the size is not;
choosing the best window would be picking a result, so the page keeps 60.

## 13. Investment-banking revenue and market activity (researched 2026-10-11, not built)

Question: can IPO, volume and spread data tell how GS, MS and JPM's investment
banking fees will come out, and move the stock? Scratch scripts only.

- **Data that exists.** Quarterly `InvestmentBankingRevenue` from SEC company
  facts (first-filed value; Q4 = year less nine months): GS 2012Q3 on, MS 2008,
  JPM 2008; the 2025-26 values match the press releases. Priced IPOs by month
  from Nasdaq's calendar (`api.nasdaq.com/api/ipo/calendar?date=YYYY-MM`, back to
  2011 at least; 4,643 deals). SPACs are a third of the rows and must be
  flagged (name and a 10.00 unit price); direct listings (Coinbase, Spotify,
  Roblox) carry a reference value, not proceeds, so each deal is capped at $5bn.
  Not free: M&A announcements (advisory fees lag them by 2-3 quarters), bond
  issuance by quarter. HY spread history on FRED is only about 3 years; Baa-10Y
  was used instead.
- **Explains revenue, 2013Q1-2026Q2, average of the three banks' year-on-year log
  change (54 quarters, Newey-West t).** IPO proceeds ex-SPAC R-squared 0.59
  (t 6.1); IPO count 0.49; SPY 4-quarter return 0.53; 10-year yield volatility
  0.39 (negative); SPY quarter return 0.15; VIX level 0.05, SPY dollar volume 0.00.
  Without 2020Q1-2022Q4: 0.28, 0.16, 0.35, 0.16. Not stable by period: IPO proceeds
  0.50 in 2013-19 and 0.02 in 2023-26 (14 quarters); SPAC proceeds 0.03 then
  0.53; only the SPY 4-quarter return is positive and similar throughout
  (0.27 / 0.35 / 0.37).
- **Nowcast of the quarter, expanding window from 2018Q1 (34 quarters).**
  IPO proceeds plus last quarter's year-on-year: RMSE 0.184 against 0.233 for
  "same as last quarter" and 0.338 for the mean (Diebold-Mariano t 1.77: not
  significant); 2023 on 0.125 against 0.182; the direction of the change in the
  growth rate is right in 71% of quarters. A better guess about the level, not a
  large one: the error is still about 18%.
- **Does it move the stock or the EPS surprise? No.** Report-day move against the
  financials fund, 53 quarters with the banks averaged: IB-fee acceleration
  r +0.08 (t 0.6), proxy-predicted acceleration +0.17 (t 1.0, n 37), IB fees
  against the proxy model -0.07. EPS surprise: IB acceleration +0.25 (t 1.9),
  proxy-predicted acceleration -0.21 (t -1.2); IB fees above the proxy model
  go with a larger EPS surprise (+0.51, t 3.5) but that is only the revenue
  line showing up in EPS, known at the report, not before it.
- **Live case, Q3 2026 (reports next week), proxies: IPO proceeds flat on a
  year ago, 26 IPOs against 65.** Model: GS fees about $3.3bn (+22% on Q3 2025,
  Q2 was +44% at $3.4bn), MS $2.8bn, JPM $3.0bn (Q2 $3.2bn). No consensus for IB
  fees is available here, so no beat or miss is implied.
- **Reading.** The proxies describe the revenue a quarter before it is reported;
  the market and the consensus already use them, and nothing here predicts the
  surprise or the reaction. If built: show the nowcast and the proxies on the
  bank themes' card as context with the error range, never as a beat/miss
  call. Management's mid-quarter remarks (June and September conferences)
  are the stronger signal and are not data. Extending to C and BAC is
  cheap (same XBRL tag); M&A and debt issuance would need a paid source.

Buy-side activity against the banks' trading and commission lines (2026-10-11,
scratch; same method as above, year-on-year log changes, Newey-West t):

- **Targets in SEC XBRL.** `BrokerageCommissionsRevenue` (client execution
  commissions: GS 2009 on, JPM 2009 on, MS 2017 on); `PrincipalTransactionsRevenue`
  (JPM) and `TradingGainsLosses` (MS) as trading revenue. GS's market-making line
  is not in XBRL (its trading tag stops in 2019); segment lines (FICC, equities,
  JPM "Markets") are in the press releases only. Both trading tags include
  hedges, financing offsets and, for JPM, treasury items: a contaminated target.
- **Proxies tried.** Dollar volume of 13 equity ETFs and of 5 bond ETFs;
  leveraged-fund gross positions (long + short, CFTC TFF) in S&P and Nasdaq
  futures and the 10-year note, and their open interest; VIX level and change;
  10-year yield volatility; SPY 4-quarter return.
- **Commissions (GS and JPM average, 65 quarters).** Equity ETF volume R-squared
  0.23 (t 3.3), 0.41 in 2010-19 and 0.01 from 2023; VIX year-on-year change 0.18
  (t 3.9), steady at 0.12-0.16; leveraged-fund positions and bond volume: nothing.
  Out of sample from 2018 (34 quarters) the volume model's error is 0.124 against
  0.136 for the mean and 0.178 for last quarter's change: a small gain.
- **Trading revenue (MS and JPM average, 66 quarters).** Nothing: R-squared 0.00-0.06
  for every proxy, signs flip between periods (bond volume 0.56 from 2023, 0.01
  before); out of sample no proxy beats the mean (0.25 against 0.25-0.29).
- **Reading.** "Buy-side activity helps" is not shown by these proxies. Either the
  proxies are not buy-side flows (ETF volume is mostly not institutional client
  flow; leveraged funds in futures are a sliver of hedge fund activity), or the
  target is too noisy. Next, if pursued: FINRA margin debt (monthly, the financing
  side), the NY Fed's primary dealer transaction volumes, TRACE corporate-bond
  volume, OCC options volume, FINRA ATS block volumes; and parse segment revenue
  (equities, FICC) from the earnings releases for a cleaner target.

Financing, dealer volume and margin debt (2026-10-11, scratch; 50 quarters from
2014Q1, year-on-year log changes, Newey-West t). Sources: FINRA margin
statistics (monthly, 1997 on; `finra.org/sites/default/files/2021-03/margin-statistics.xlsx`,
the page's table shows only the last 13 months), NY Fed primary dealer
statistics (weekly, from 2013-04; `markets.newyorkfed.org/api/pd/get/{keyid}.json`:
PDTRCS-TOT corporate, PDTRCSIND-G13 / -BELG13 investment-grade and high-yield
bonds, PDTRGSC-* Treasury coupons by maturity, PDTRGST-TOT bills and TIPS,
PDSORA / PDSIRRA-UTSETTOT Treasury repo and reverse repo). FINRA's TRACE
corporate-bond volume is not on a free API we could find; the NY Fed's dealer
corporate transactions stand in for it.

- **Commissions (GS, JPM) and trading revenue (MS, JPM): nothing holds.**
  Dealer corporate volume 0.02 and 0.01, Treasury coupons 0.07 / 0.07 (wrong
  sign for trading), Treasury repo 0.01 / 0.03, margin debt 0.04 / 0.02. High-yield
  dealer volume explains trading revenue at 0.32 (t 3.3) but is 0.25 in 2014-19
  and 0.02 from 2023. Out of sample from 2018 no model beats the expanding mean
  for either line (trading: 0.258-0.265 against 0.249; commissions 0.128-0.129
  against 0.127).
- **Margin debt explains investment-banking fees, not trading.** R-squared 0.65
  (t 5.9) on the three banks' average IB-fee growth, and stable: 0.72 without
  2020-22, 0.55 in 2014-19, 0.79 from 2023. But it moves with the market (0.77
  correlation with the S&P's 4-quarter return) and with IPOs (0.65): it is a
  leverage-appetite version of the market level. Together with IPO proceeds
  R-squared 0.76 against 0.61 (IPO alone), 0.70 (IPO and S&P return). Out of
  sample from 2018, IPO plus margin debt has error 0.179 against 0.183 (IPO and
  last quarter's change), 0.202 (IPO and S&P return), 0.233 (last quarter's
  change): a small gain; Diebold-Mariano t 0.94 against the IPO model.
- **Now.** Margin debt July-August 2026 averaged $1.44tn against $1.04tn a year
  earlier (+32% log; +42% in Q2). September's figure comes out in mid-October.
- **Reading.** Buy-side leverage and activity, as measured here, tells where the
  deal market is (it is the same cycle), not what trading desks earned. The
  financing proxies (repo, margin) do not explain trading either. Nothing here
  clears the bar to put on a page; the IB-fee nowcast could use margin debt in
  place of the S&P return. Next, if pursued: segment revenue from earnings
  releases as a cleaner target.

SCOOS, the Fed's Senior Credit Officer Opinion Survey on Dealer Financing Terms
(2026-10-11, scratch). Quarterly since 2010Q2, 17-23 dealers answering; the
whole history is one csv from the Data Download Program
(`federalreserve.gov/datadownload/Output.aspx?rel=SCOOS&series=d7ddcd636ef03b879c632a42477a0535&filetype=csv&label=include&layout=seriescolumn&type=package`,
needs the Choose.aspx page as referer; the DDP's "Build Your Package" goes in
November but this csv is a preformatted package, so check it survives).
Columns are counts per answer; net percentage = (increased or tightened less
decreased or eased) / respondents. Questions used: 8 (hedge funds' use of
leverage), 9 (unused leverage available), 4 and 5 (price and non-price terms to
hedge funds), 53 / 57 / 61 (client demand for funding of high-grade bonds,
high-yield bonds, equities). The 2026 September survey is already in the file.
Each answer is a change over three months, so the page-level quantity is the sum
of the last four.

- **Trading revenue (MS, JPM): nothing.** Hedge-fund leverage 4-quarter sum
  R-squared 0.01; unused leverage 0.01; price terms 0.04; non-price terms 0.06;
  high-grade funding demand 0.11 (t 3.7) but 0.07 / 0.09 / 0.05 across periods.
  Out of sample from 2018: 0.254-0.290 against 0.248 for the mean.
- **Commissions (GS, JPM): equity funding demand 0.13 (t 3.5),** 0.03 in 2011-19
  and 0.28 from 2023; out of sample 0.122 against 0.130 for the mean: a small
  gain. Hedge-fund leverage 0.06; worse than the mean out of sample.
- **Investment-banking fees: client equity-funding demand 0.34 (t 3.8), high-grade
  bond demand 0.33.** But equity-funding demand correlates 0.79 with margin
  debt: with IPO proceeds and margin debt already in, adding it leaves R-squared
  at 0.76 and the out-of-sample error at 0.181 against 0.179. It is the same
  market-cycle signal.
- **Now (2026 September survey, 4-quarter sums of net %):** client demand for
  equity funding +171, high-grade bonds +55, high-yield +41; hedge-fund leverage
  used +15, unused leverage +5, price terms +5 (tightened), non-price terms +21.
  Strong funding demand, a year of modest hedge-fund leverage growth, and terms
  tightening a little. None of it has predicted a revenue line beyond what the
  market level already says.
- **Verdict.** The dealers' own read of hedge-fund leverage and terms does not
  explain the banks' trading or commission revenue (n 62; the lines are noisy and
  contaminated, see above). Funding demand tells the cycle, as margin debt does.
  The With Intelligence prime-broker client counts (GS 320 of 579 funds, MS 288,
  JPM 237, BofA 167, Jefferies 17; second half of 2025 data, published
  2026-04-29; JPM has the most funds above $10bn) stay unusable as a signal: one
  snapshot a year, a count and not a balance.

Result of the data-signal test (2026-10-12, scratch; nothing built):

- **Method.** Four themes whose series have long free histories: housing (ITB;
  7 FRED series), consumer (XRT; 8), banks (KRE; 8; the HY spread has only 3
  years and was left out) and energy (XLE; EIA stocks of crude, gasoline and
  distillate against their 5-year same-week average, and refinery utilization).
  Cloud and semis rest on short custom series (hyperscaler capex, TSMC and Korean
  export lines) and could not be tested. Each series: its change over three
  months (energy: the deviation from the 5-year average, and its 13-week change),
  scaled by the robust spread of the changes known so far (at least four
  horizons of history), signed by what is good for the proxy (mortgage rate,
  months' supply, delinquencies, claims, saving rate: down is good), known only
  after its release (the lag read from the build's own `available` dates, e.g.
  starts 47 days after the label date, retail sales 45, delinquencies 142, EIA 5).
  Month-end signal = mean of the oriented z-scores (clipped at 3); outcome = the
  proxy's excess return over SPY for the next 21 and 63 sessions; Spearman
  correlation, p from 1,500 circular shifts of the signal (keeps its serial
  dependence), halves, and a control for the proxy's own past 3-month excess
  return. Revised FRED values were used, so the test is slightly kinder than
  real time (ALFRED vintages would fix that).
- **Composite signals do not lead price.** 2009-2026, 210 months. Spearman and p:
  housing 1M -0.09 (0.18), 3M -0.11 (0.23); consumer -0.06 (0.40), -0.06 (0.52);
  banks +0.13 (0.030), +0.01 (0.91); energy level +0.08 (0.21), +0.08 (0.57),
  energy 13-week change +0.07 (0.36), +0.22 (0.025). Twelve tests, two nominal
  hits, none near a 0.004 line; the two hits sit in one half of the history
  (banks 1M: halves +0.15 / +0.09 hold; energy 3M: +0.07 / +0.35 do not).
  Housing's sign is the wrong way in both horizons.
- **Per series (46 tests, banks, consumer, housing).** Three nominal at 0.05,
  2.3 expected by chance; one survives a Benjamini-Hochberg 5%: credit-card
  delinquency (down is good), 1 month ahead, rho +0.15. It has 66 distinct
  values (quarterly), and by period -0.05 (2009-13), 0.00 (2014-18), +0.31
  (2019-22), +0.19 (2023-26): it exists in the last eight years only.
- **The data lag the price more than they lead it.** The composite signal
  correlates with the proxy's past 3-month excess return at +0.23 (housing),
  +0.27 (banks), -0.04 (consumer); what price did, the data then agree with.
  Controlling for that momentum: banks 1M +1.2 pp per z (p 0.035), consumer 1M
  -0.8 pp (p 0.004, the wrong sign for a signal and not there without the
  control), housing 3M -2.5 pp (p 0.10).
- **Decision.** Do not add a data-signal row to the THEMES board: no theme's
  data direction has been shown to lead its price. The board keeps price,
  revisions, valuation. The series stay on the theme pages as context, with
  their release dates. If revisited: ALFRED vintages for real-time values, and
  a test per theme of "data surprise on release day against the proxy's move"
  (the board's RELEASE DAYS card already does it) rather than of a monthly
  direction.

## 14. CRUISE and DEFENSE themes (2026-10-12)

Added to THEMES: CRUISE (equal-weight CCL, RCL, NCLH; Viking is in no tracked
index) and DEFENSE (equal-weight LMT, RTX, NOC, GD, LHX, HII). Each has the
status board, run-in, report calendar and macro dates, and a sensitivity table
from the group's `drivers` in the config (no theme-specific code).

What the tests that shaped it showed (scratch, 2010-2026 unless noted):

- **ITA is a poor proxy for the primes.** Daily excess return on the day's
  moves in VIX, oil, gold, 10-year yield, credit and dollar: ITA R-squared 0.006,
  the six primes' average 0.058 (VIX +0.12 per point, t 7.4; since 2023 R-squared
  0.17, credit -0.70 per 1%). ITA also holds Boeing, GE Aerospace and
  suppliers. The proxy is the basket.
- **The primes are defensive.** The beta to the VIX is positive in every
  period (+0.01 in 2010-16, +0.11 in 2017-22, +0.24 in 2023-26) and persisted
  from one year to the next (correlation 0.63 between a year's beta and the
  next year's); oil 0.55; gold, 10-year, credit, dollar 0.0-0.2.
- **Cruise** (basket, R-squared 0.07): VIX -0.29 per point (t -4.7), dollar
  -0.60 per 1% (t -4.0), oil -0.07 (t -2.0) but -0.13 / +0.05 / -0.20 by period;
  credit +0.34 / -0.25 / +1.8: the sign of the credit beta is not stable.
  Year-to-year persistence of the betas is 0.3 to 0.4.
- **Defense data do not lead price.** XBRL backlog growth (LMT, RTX, NOC, GD,
  LHX; 107 firm-quarters from 2018, taken at the filing date): next-3-month
  excess return rho -0.22 (permutation p 0.025, the wrong way), within a quarter
  across firms -0.02. USAspending DoD contract obligations (trailing 12 months
  against the 12 before, usable 100 days after the month, DoD data publish with a
  delay): by firm rho -0.24 to +0.17 with no consistent sign (RTX +0.17,
  p 0.02; GD -0.24, p 0.05; the rest nothing), and total DoD obligations
  against ITA +/-0.05 to -0.07 (p 0.4, 0.5). Not shown as signals.
- **Not usable.** TSA passenger volumes, the Defense/War Department daily
  contract announcements and the CDC cruise outbreak page answer 403 to a
  scripted client; they would need a browser-looking client, which the project
  does not use.
- **Open.** A defense data block (backlog in years of sales, obligations by
  prime) as context, labelled as not leading; a cruise block on fuel and the
  consumer. Neither earns a signal.
