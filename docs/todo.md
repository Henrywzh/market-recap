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

Short-term moves follow headlines (US–Iran talks, tariffs, Fed speakers).
Goal: per theme, a headline timeline beside the linked assets' intraday
moves and the matching Polymarket/Kalshi probability.

Sources measured 2026-09-28, 17:30 UTC, US session open:

| Source | Newest item | Last 2 hours | Notes |
|---|---:|---:|---|
| Google News RSS search, "Iran" | 4 min | 34 | No key; unofficial endpoint, so poll gently. Aggregates Reuters, Axios, Bloomberg |
| Google News RSS, "stock market" | 5 min | 26 | |
| CNBC top news RSS | 11 min | 8 | Sends `Access-Control-Allow-Origin: *` |
| BBC Middle East RSS | 21 min | 1 | |
| Finnhub `news?category=general` | 92 min | 0 | About 30 items a day, Reuters/CNBC/Bloomberg. Curated, not real-time; nothing new in a 70 s re-poll |
| Finnhub `company-news` | 1–4 h | | Mostly Yahoo syndication; NVDA 248 items in two days |
| Alpaca (Benzinga) | not tested | | Needs an account. Real-time WebSocket, 600–900 headlines a day, from 2015. Launched as a free beta in 2022; the current pricing page does not mention news. Stock-centric, weaker on geopolitics |

Finnhub `quote` works free and real time; `stock/candle` and
`news-sentiment` return 403. Intraday bars can come from the Yahoo chart
endpoint the live strip already uses.

Proposed build:

- Themes in `config/dashboard.toml`: keywords, linked symbols, and optional
  Polymarket/Kalshi market ids. The user edits the list.
- A `/api/news` Pages Function beside `/api/quotes`, with the same live-tier
  rules: allow-listed theme queries from a deploy-time contract, one
  upstream fetch per theme per 5 minutes, per-source failure, and no
  substitution.
- Google News RSS for the theme timelines. Finnhub general news as "top
  market news". Headline, source, time and link only; no article text.
- Later: Alpaca, if an account confirms free news and bars, for per-stock
  "why is it moving" headlines.

To decide:

- The first themes.
- Placement: a NEWS page, or a "themes today" strip on OVERVIEW.
- Whether headlines are also stored (snapshot tier) so that news can later
  be lined up against price moves, or only displayed like live quotes.

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
