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

The site answers what the market did, how much risk is on, what is coming
and which names to look at. For trading it does not yet answer what is held,
where to get in or out, or when to look. In priority order, free data only:

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

4. **Levels and expected range.** For SPX/NDX and holdings: distance to the
   20/50/200-day averages, prior highs and lows, gaps. The week's
   option-implied range (from VIX or the ATM straddle), so a move can be read
   against what was priced.
5. **Pre-market and overnight.** ES/NQ, the biggest pre-market movers in the
   universe, Asia and Europe overnight. Existing Yahoo endpoints.
6. **Position-size calculator** (TOOLS). Account risk and stop to shares via
   ATR, with average daily value traded and spread beside it.

Third, flows and positioning:

7. **Who is forced to trade.** Built 2026-09-29 as RISK → POSITIONING: FINRA
   short interest and the trend-follower flip levels. Still open: the
   buyback blackout calendar.
8. **Insider cluster buys** from SEC Form 4, limited to the universe;
   quantamental-lab already has the insider event study.
9. **Signal scorecard.** Historical hit rate and average forward return next
   to each signal (Fear & Greed extremes, the anchor's cuts, the implied-move
   gap), so it is clear which ones deserve weight.

To decide: holding period (intraday, swing, longer), instruments (stocks,
index ETFs, options), and where holdings and trade records may live
(behind Cloudflare Access, or local only). Suggested start: 1, 2 and 4.
The user has said the third group (7–9, flows and positioning) is the most
interesting of these.

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
