# Information architecture

How the site is organised, what each page is for, and how fresh each kind
of number may be. Written 2026-09-26 as the plan for moving from ten
data-type tabs to a small number of decision-ordered modes. The panels'
own contracts stay in `README.md` and `docs/monitor.md`; this file decides
where things live and why.

Scope is the US market, with global cross-asset series as context. Asia
work (Hong Kong sectors, southbound flows) is paused, not removed.
CROSS-LISTING stays on the site.

## Why change

The page has ten top-level tabs grouped by the kind of data: VALUATION,
FINANCIALS, DCF and single-ticker TECHNICALS are four views of one company
in four places; MARKETS, HEAT MAPS and SECTOR ROTATION are one question
("what did the market do") split three ways. There is no entry point that
says what to look at today, and two steps of the trading loop have no page
at all:

```
risk budget → direction / sectors → names → timing → review
 (how much)       (where)          (who)    (when)   (was it right)
```

The site is strong on the middle three. It has no view of **how much risk
to run** (volatility, credit, positioning, what the rates market prices) and
no record of **decisions** to review against outcomes.

## Principles

1. **Order by decision, not by data type.** A page answers one question.
   Data that answers several questions is shown where each question is
   asked, from one artifact.
2. **One entity, one page.** Every ticker on the site links to the same
   ticker page.
3. **Deltas first.** The landing page shows state and what changed. Levels
   and history live one click down.
4. **Evidence, never a score.** As in MONITOR: each tile or row is one
   independent piece of evidence with its source. No composite risk score,
   no regime state machine.
5. **Thresholds are configuration.** A tile changes colour only when it
   crosses a threshold written in `config/dashboard.toml` beforehand, so the
   page's history of alerts can be tested the same way as a signal.
6. **Horizon is labelled.** Every signal is tagged `slow` (months:
   valuation against its own history, revision trend, macro, liquidity) or
   `tactical` (1–4 weeks: 5/20-session changes, vol term structure, credit
   ETFs, repricing, positioning extremes). The two groups are not mixed in
   one row.
7. **Calendar and pricing are different things.** The calendar says *when*
   (FOMC on 10-28). Pricing says *what the market expects now* (P(hike)
   69%, +12 on the week) and is a time series that moves every day,
   whether the event is two days or two months away. Pricing is never
   hidden behind an event-date window.

## Navigation

Four top-level modes plus a tools menu. Each mode has at most four views.

```
BRIEF                          landing page, the five-minute read
MARKET   Overview · Risk · Priced Path · Rates & Macro
NAMES    Monitor · Screen · Ticker · Cross-listing
CATALYSTS  Calendar · Earnings
TOOLS ▾  Relative strength · ETF X-Ray · DCF calculator
```

Every view has a stable hash URL (`#brief`, `#market/risk`,
`#names/ticker/AAPL`). Old hashes (`#valuation`, `#dcf`, ...) redirect to
their new home so bookmarks survive.

### Current tab → new home

| Current | New home | Change |
|---|---|---|
| MARKETS (live strip, recap, breadth, sectors) | MARKET → Overview | live strip moves to the top of BRIEF as well |
| HEAT MAPS | MARKET → Overview | S&P treemap and ETF flow treemap become sections |
| SECTOR ROTATION | MARKET → Overview | rotation graph becomes a section |
| FIXED INCOME | MARKET → Rates & Macro | unchanged content |
| MACRO | MARKET → Rates & Macro | unchanged content |
| — | MARKET → Risk | **new** |
| — | MARKET → Priced Path | **new**; takes the expectation sources out of the calendar |
| MONITOR | NAMES → Monitor | unchanged; tickers link to the ticker page |
| VALUATION & QUALITY table | NAMES → Screen | unchanged table |
| VALUATION P/E vs own ten years | NAMES → Ticker | per-company chart moves to the ticker page |
| VALUATION index & sector P/E vs own ten years | MARKET → Sectors | a market question, beside the rotation graph |
| FINANCIALS | NAMES → Ticker | ten-year statements become a ticker section |
| DCF | NAMES → Ticker (link) and TOOLS | the model opens pre-filled from the ticker page |
| TECHNICALS single ticker | NAMES → Ticker | price, MAs, z-score band as a section |
| TECHNICALS A/B ratio | TOOLS → Relative strength | exploratory, not daily |
| CALENDAR | CATALYSTS → Calendar | unchanged; distributions stay beside each release |
| EARNINGS | CATALYSTS → Earnings | gains implied move vs realised move (phase 3) |
| ETF X-RAY | TOOLS → ETF X-Ray | tickers in holdings link to the ticker page |
| CROSS-LISTING | NAMES → Cross-listing | unchanged; a listed pair's ticker page links to it |

## Pages

### BRIEF

The only page meant to be read top to bottom every day. Text, numbers and
sparklines; no full-size charts. Every line links to the view that explains
it.

1. **Live strip.** The existing intraday quotes, with source and age.
2. **Systematic anchor.** The state of the frozen v1 technical/drawdown
   control from `quantamental-lab` (exposure it would hold today and why).
   This is the default; a discretionary override is a decision to log
   (phase 4), not a silent departure.
3. **Risk strip** (`tactical` and `slow` rows kept apart). About eight
   tiles: trend (SPX vs 200-day, drawdown), breadth (% above 200-day),
   volatility (VIX/VIX3M, implied minus realised), credit (HYG/IEF trend,
   HY OAS percentile), rates volatility (MOVE), dollar, correlation /
   dispersion, positioning extremes. Each tile: value, 1Y percentile,
   5-session change, colour only past a configured threshold.
4. **Priced strip.** Next FOMC P(move) with 1-day and 1-week change,
   cumulative cuts/hikes priced to a fixed horizon, the next CPI median from
   Kalshi, SPX 30-day implied vs realised. Independent of how far away the
   event is.
5. **What changed.** Tiles that crossed a threshold, names that entered or
   left MONITOR, revision breadth that turned, large post-earnings moves.
6. **Next 72 hours.** Scheduled releases with their distribution, earnings
   of watchlist names with implied move.
7. **My list.** Watchlist names with price state, next checkpoint and next
   event. Holdings plug in here later (see Deferred).

### MARKET → Overview

What the market did. Existing MARKETS recap, both treemaps, sectors rebased,
breadth by sector, rotation graph, plus a global context row (major
non-US indices, DXY, USDJPY, gold, copper, oil) with multi-period returns.

### MARKET → Risk

How much risk the market is pricing and how crowded it is. Sections:

| Section | Series | Horizon |
|---|---|---|
| Volatility | VIX9D, VIX, VIX3M, VIX6M, VVIX, SKEW; SPX 20-day realised; implied minus realised; VIX futures settlement curve | tactical |
| Rates volatility | MOVE | tactical |
| Credit | HYG/IEF and LQD/IEF ratios; HY, IG and CCC OAS where available | tactical |
| Correlation / dispersion | Cboe implied correlation; realised dispersion of S&P members (computed) | tactical |
| Liquidity | Fed balance sheet − RRP − TGA; NFCI | slow |
| Positioning | CFTC TFF net positions (ES, NQ, ZN, VX); AAII; NAAIM; put/call | slow, read at extremes |

Each series shows level, 1Y percentile, change, and its configured
threshold. Fetchers for credit, VIX, COT and Fear & Greed already exist in
`alternative-data/src/global_market_regime`; they are **ported** into
`sources/`, not read from that repository at run time.

### MARKET → Priced Path

What the rates market and event markets expect, and how that has moved.

- **Policy path by meeting.** Probability of each outcome per FOMC meeting,
  computed from fed funds futures (`ZQ*`) by the standard meeting-month
  method, beside Kalshi and Polymarket for the same meeting. Disagreement
  beyond a configured gap is shown, not averaged away.
- **Longer path.** Implied rate by quarter from SOFR futures, drawn for
  today, one week ago and one month ago.
- **Release distributions.** Kalshi ladders for CPI, payrolls, claims and
  others (median, p10–p90, open interest), matched by the rules in
  `docs/expectation_sources.md`.
- **Anchors.** Cleveland Fed inflation nowcast, GDPNow, breakevens, real
  yields.

The calendar keeps showing each release's distribution beside the event;
this page is where the same numbers are read as a series.

### MARKET → Rates & Macro

Existing FIXED INCOME and MACRO content: par curve and its changes,
spreads, inflation heat table, commodity proxies.

### NAMES → Monitor

Unchanged (`docs/monitor.md`). Every ticker links to the ticker page.

### NAMES → Screen

The VALUATION & QUALITY table and scatter, unchanged.

### NAMES → Ticker

One page per company, reached from any ticker anywhere on the site.
Top to bottom:

1. **Header.** Price, drawdown from 1Y high, return vs sector peers, next
   event, MONITOR state if queued.
2. **Thesis and checkpoints.** Why the name is followed and what would
   falsify it, from `config/monitor_notes.toml` (extended with a
   checkpoint list and dates). Light by design; the entity/timeline model
   of `alternative-data`'s Research Control Tower is the reference, not its
   artifact machinery.
3. **Evidence.** FY1 EPS revisions, last-quarter surprise, revenue and FCF
   trend; later insider cluster buys (Form 4), short interest and days to
   cover (FINRA), rating changes. Listed for and against, never scored.
4. **Valuation.** Multiples against the company's own ten years and its
   sector.
5. **Financials.** The ten-year statements.
6. **Earnings and options.** Past reactions; implied move before the next
   report against the realised moves of the last eight; IV percentile and
   term structure once history exists.
7. **Technicals.** Price with MAs, z-score band, relative strength vs
   sector.
8. **DCF.** Opens the model pre-filled.

### NAMES → Cross-listing

The existing CROSS-LISTING panel, unchanged: a US line against its home
line at the depositary ratio, with its diagnostics.

### CATALYSTS

Calendar and Earnings as today. The Earnings view gains implied vs realised
move for reporters (phase 3).

### TOOLS

Relative-strength lab, ETF X-Ray, DCF calculator. Reached from a menu and
from links on other pages; not part of the daily read.

## Data freshness

Three tiers. A number's tier is fixed by where it is produced, and the page
says which tier every number belongs to.

| Tier | Cadence | Content | Mechanism |
|---|---|---|---|
| **Live** | seconds–minutes | index/ETF quotes, key yields; later VIX term structure and the next-meeting FOMC probability | Pages Function, allow-listed symbols from a deploy-time contract |
| **Snapshot** | every 2–3 hours on weekdays | expectation markets, policy path | scheduled GitHub Action appending timestamped rows |
| **Close** | nightly | everything else, with history and validation | `make refresh` |

Rules:

- **Live numbers are displayed, never stored.** History is written only by
  the snapshot and close tiers, each row with its fetch time and source.
  This keeps every stored series usable for backtests.
- **Each live endpoint is separate.** Quotes stay on `/api/quotes`; pricing
  gets its own endpoint (`/api/priced`) with its own contract file, cache
  window and slower refresh. One failing never blanks another.
- **Fed funds futures on Yahoo are about ten minutes delayed**, and event
  markets are re-priced far less often than a quote, so pricing refreshes
  every five minutes at most, or on demand.

### Load of the live function

Measured from the code on 2026-09-26 (`functions/api/quotes.js`,
`web/js/live.js`, `[live]` in `config/dashboard.toml`):

- The browser polls every 60 s **only while the session is open and the tab
  is visible**; every 300 s when the market is closed; not at all in a
  hidden tab. One tab open for a full session is about 390 requests a day.
- The function answers every reader from one upstream fetch per 15 s per
  isolate (`server_cache_seconds`), keeps the in-flight promise so
  concurrent readers share it, and sends `Cache-Control` for the same
  window.
- It fetches only symbols in `/live.json`, so it cannot be used as an open
  proxy. Each source has a 4 s timeout and fails to a dash with the reason;
  the previous prices stay up with their growing age.
- The static site does not depend on it. If the function fails, the strip
  shows the error and every other panel renders from the nightly build.

At personal-use traffic this is far inside Cloudflare's free function
allowance. The real risks are not load but **source behaviour**: Yahoo's
chart endpoint and CNBC's quote service are unofficial and can change or
refuse without notice. The mitigation is what exists already (per-source
failure, visible age, no fallback substitution) plus a probe in CI.

Adding series to the live tier should keep these properties: allow-listed
symbols, one upstream fan-out per cache window, per-source failure,
separate endpoint per concern, and a symbol budget in the contract that
the build refuses to exceed.

## Collections to start early

Some history cannot be downloaded later for free, so it must be recorded
from the day it starts. These start in phase 0, before their pages exist.

### Option chain snapshots

- **Universe:** SPY, QQQ, IWM, the watchlist and current MONITOR names
  (about 50 underlyings). Not the whole index.
- **Time:** once per session, inside 15:10–16:00 New York (the job is
  scheduled for 15:25). After the close, free chains often show zero bids or
  stale quotes: on a Saturday check, XLU had no strike quoted on both sides
  for three of five expiries.
- **Expiries:** the nearest at least two days out, plus those either side of
  30 and 60 calendar days, so a constant-maturity vol can be interpolated.
- **Per underlying and expiry, stored:** fetch time, spot, parity-implied
  forward, ATM implied vol, 25-delta put and call IV, ATM straddle mid and as
  a share of spot, open interest and volume totals. Vols are solved from
  bid/ask mids of out-of-the-money contracts under Black-76, never Yahoo's
  last-trade IV. Contracts within 25% of spot are kept raw (gzipped CSV).
- **Derived later:** IV percentile and rank (after about a year), term
  structure, skew, implied move before earnings.
- **Source:** Yahoo option chains via `yfinance`, subject to the same
  coverage-gap rule as prices: a missing chain is recorded as missing.

### Expectation snapshots

Four runs a weekday (09:41, 12:41, 15:41 and 18:41 New York in summer).
Each stores inputs, not derived probabilities: the next 12 fed funds futures,
the next 8 quarterly SOFR futures, every open market in the configured
Kalshi series (Fed decision, Fed rate, CPI, core CPI, payrolls,
unemployment, GDP) and Polymarket's Fed markets, each row with source, quote
time and fetch time. One gzipped CSV per run (about 900 rows, 27 KB). Kalshi and Polymarket
publish some price history, so these can be partly backfilled; ZQ closes
can be backfilled from daily history; intraday repricing cannot.

### Storage

`.github/workflows/snapshots.yml` commits each run to the orphan
`snapshots` branch, which holds data only. Measured on 2026-09-26: a full
options run is about 16,000 raw contracts at about 30 compressed bytes each,
so roughly 120 MB a year, plus about 35 MB for expectations. Scheduled workflows
run only from `main`, so recording starts once this is merged there.

## Phases

| Phase | Work | Depends on |
|---|---|---|
| 0 | This document; new navigation with redirects; ticker page assembled from existing valuation, financials, DCF and technicals panels; **start option-chain and expectation snapshots** | — |
| 1 | MARKET → Risk (ported fetchers, Yahoo vol and rates indices, computed dispersion); MARKET → Priced Path (own meeting probabilities, SOFR path, event markets) | probes for Cboe files |
| 2 | BRIEF | phase 1 |
| 3 | Ticker evidence and options: implied vs realised move, IV percentile once history allows, Form 4 clusters, FINRA short interest, rating changes | probes; snapshot history |
| 4 | Decision log: entries, passes and overrides of the systematic anchor with a reason, reviewed against outcomes | phase 2 |

Each new source gets a probe and an evaluation note in the style of
`docs/expectation_sources.md` before it reaches a page.

## Phase 2 as built (2026-09-26)

- **BRIEF is the default view** (`panels/brief.py`), assembled from this
  session's RISK, PRICED PATH, CATALYSTS, MONITOR, anchor and journal
  artifacts; one that did not build is named at the top and its line stays
  empty. Lines: live strip; systematic anchor; priced strip (next FOMC with
  its 1D / 1W change, priced to year end, next CPI's Kalshi median, VIX
  against 20-day realised); risk strip in a tactical and a slow row
  (`[brief]` names the tiles); what changed (risk lines crossed this week,
  MONITOR entries and exits, post-earnings moves ≥ 5%); the next three
  sessions (high- and medium-importance releases, not speeches; earnings of
  watchlist names and the 20 largest weights); my list (watchlist names and
  names with an open journal checkpoint).
- **Systematic anchor** (`compute/anchor.py`, `panels/anchor.py`): the
  frozen v1 friend-plus-joint control re-implemented from quantamental-lab,
  checked on 2026-09-26 to reproduce that repository's daily exposure and
  NAV exactly over 8,472 sessions (1993-01-29 to 2026-09-25). The recession
  gate is that repository's model output and is not ported; it is neutral,
  the frozen rule's own policy for a missing input. Its five-year daily
  history is kept for the journal.
- **Not done:** "revision breadth that turned" (needs the tracker's history
  as a series) and the implied move beside each earnings name (phase 3).

## Phase 1 as built (2026-09-26)

- **Navigation.** MARKET could not take Risk and Priced Path within the
  four-view limit, so they have their own mode ahead of it, in the order of
  the trading loop: BRIEF · RISK · MARKET · NAMES · CATALYSTS · TOOLS.
  RISK holds Risk, Priced Path and Rates & Macro; MARKET holds Overview,
  Heat maps and Sectors.
- **RISK → RISK** (`panels/risk.py`, `compute/risk.py`): 30 series in seven
  sections, tactical and slow kept apart. Each tile: level, 1Y and
  full-history percentile, week change, its configured threshold
  (`[[risk.tiles]]`) and whether it crossed that line within the week.
  Sources and their probes: `docs/risk_sources.md`. Not included: AAII and
  CNN Fear & Greed refuse the project's client; NAAIM has no file.
- **RISK → PRICED PATH** (`panels/priced.py`, `compute/priced.py`):
  meeting-by-meeting probabilities from fed funds futures by the
  meeting-month method, beside Kalshi and Polymarket, flagged not averaged
  when they differ by more than `[priced] disagreement_bp`; the path today,
  a week and a month ago; the next meeting's pricing through time; the SOFR
  path (today only until the snapshot branch has history); every open
  Kalshi release ladder; FRED anchors.
- **Snapshots read back.** The nightly workflow checks the `snapshots`
  branch out read-only at `data/snapshots`; `sources/snapshot_store.py`
  reads it and every section that needs it says "not recorded yet" when it
  is absent.

## Phase 0 as built (2026-09-26)

- **Navigation** follows `web/js/routes.js`: MARKET · NAMES · CATALYSTS ·
  TOOLS. BRIEF does not exist yet, so MARKET → Overview is the landing view.
  Until Risk and Priced Path exist, MARKET keeps Heat maps and Sectors
  (the rotation graph, then index and sector P/E against their own ten
  years, `#rotation`; `#sectors` also opens it) as their own views rather than folding them into Overview, and
  Rates & Macro stacks the two existing panels on one page.
- **Ticker page** is assembled from exported section renderers
  (`renderPeHistory`, `renderStatements`, `renderSingleTicker`) that the
  SCREEN, FINANCIALS and TECHNICALS code also uses. A fund or index gets its
  technicals and one line saying why the company sections are absent. The
  standalone FINANCIALS view is gone; its hash opens the ticker page.
- **Ticker page order** is price and trend first (default windows, a
  period switch; the inputs and the forward-return table stay on TOOLS →
  TECHNICALS), then P/E against its own ten years (axis capped at 1.6× the
  90th percentile when a near-zero-earnings spike would flatten it), then
  the sector comparison beside the evidence, then filings. Method notes sit
  in the ⓘ fold; the research note card appears only when there is a note.
- **Links to the ticker page** (`routes.tickerHref`) from MONITOR, SCREEN,
  HEAT MAPS tiles, SECTORS' contributor bars, EARNINGS movers and the
  CALENDAR's earnings rows. ETF X-RAY holdings are not linked yet.
- **Research note** shows the existing `config/monitor_notes.toml` fields
  (status, since, reason, outcome). A checkpoint list is not added yet: the
  note is part of the MONITOR ledger that cloud builds restore and validate
  (`sources/monitor_state.py`), so changing its shape is its own change.
- **Snapshots** are recorded as described above; they start when the
  workflow reaches `main`.

## Deferred

- **Holdings.** Not connected yet. BRIEF's list and the ticker page reserve
  a position field (size, cost, horizon) so holdings plug in without a
  layout change, and so risk tiles can later be read against actual
  exposure.
- **Intraday options.** Free chains are delayed and rate-limited. If this
  starts, the route is a broker API (Futu OpenD is already installed
  locally), after checking that the account has US options real-time quote
  entitlement. Dealer gamma estimated from free open interest is not shown:
  open interest updates daily and the sign assumptions are unreliable.
- **Asia.** Hong Kong sector pages and southbound flows stay in their
  existing homes until the US structure settles.
- **Themes.** The AI and industry alternative-data dashboards in
  `alternative-data` remain separate weekly/monthly research surfaces.

## Invariants carried over

Unchanged from `README.md` and `AGENTS.md`: `config/dashboard.toml` is the
single source of truth for universe, labels and series ids; fetches go
through `sources/http.py`; missing input stays `None` to the page; periods
are defined once in `config.PERIOD_TRADING_DAYS`; `make refresh` fails the
build rather than publish a wrong number.
