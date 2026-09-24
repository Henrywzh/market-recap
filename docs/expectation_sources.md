# Macro expectation sources: evaluation

What the free sources say about upcoming US macro releases, and how far each
can be relied on. Measured 2026-09-23/24 with `scripts/probe_expectations.py`
from a laptop and from GitHub's runners (`probe-sources.yml`, every three
hours until 2026-10-01; the summary below is the first three cloud runs and
is updated when the window closes).

Targets asked of every source: initial claims (09-24), durable goods (09-25),
core PCE and Q2 GDP final (09-30), September payrolls and unemployment
(10-02), September CPI (10-14), the October 28 FOMC decision.

## Verdict by source

| Source | Kind | What it gives | Lead time | Cloud success / median | Notes |
|---|---|---|---|---|---|
| Kalshi | market | full probability ladder per release | weeks (every target) | 6/6, 0.4 s | CFTC-regulated, public API. Liquidity varies: FOMC 1.86M contracts open, CPI y/y 272k, core PCE 8k (thin). Local latency once 28 s |
| Polymarket | market | Fed decisions (binary per outcome) | weeks | 6/6, 0.2 s | Fed only for US macro; no CPI/payrolls ladders |
| Fed funds futures (Yahoo `ZQ*.CBT`) | market | implied rate per month | months | 6/6, 0.6 s | Delayed quotes; one number per contract; per-ticker `history()` works, batch `download()` timed out |
| TradingView calendar | point consensus | forecast + previous, 340 US events / 30 d | forecast on 35% of events 0-2 d out, 14% 3-7 d, ~1% beyond | 6/6, 0.06 s | Needs `Origin: https://www.tradingview.com`; any UA. Unofficial. Already used by `alternative-data/event_consensus` |
| Nasdaq economic calendar | point consensus | consensus + previous, per date | 31% 0-2 d, 22% 3-7 d, 0 beyond | 4/6, 0.3 s | One request per date. Returned HTTP 200 with `data: null` overnight (04:57 UTC) |
| ForexFactory JSON | point consensus | forecast + previous | this week only (`nextweek` is 404) | 6/6, 0.1 s | Rate-limits hard: HTTP 429 locally after a few requests |
| Yahoo economic calendar (yfinance >= 1.7) | point consensus | expected + last | none beyond 7 d observed | 6/6, 0.1 s | Returns part of the window per call; throttled (60 s timeouts) after ~30 requests; needs a newer yfinance than the build pins |
| Cleveland Fed nowcast | official model | CPI / core CPI / PCE / core PCE, m/m and y/y, daily | current and next month | 3/3, 1.4 s | JSON is large (1.4 MB+); took >20 s once locally — `equity-research/daily-macro` uses a 20 s timeout |
| FRED | official | actuals, breakevens (1-day lag), GDPNow, EXPINF1YR | — | 6/6, 1.8 s | Holds any request whose UA has no contact address (15 s timeouts) and stalls Python TLS: use curl + the contact UA. UMich expectations (`MICH`) lag ~3 months on FRED |
| Philadelphia Fed SPF | official survey | median and dispersion files | quarterly (2026Q3) | 3/3, 0.8 s | Background, not event-level |
| Finnhub economic calendar | point consensus | — | — | HTTP 403 | Paid tier; the free key only covers quotes/earnings |
| Econoday | point consensus | consensus **range** on event pages | — | reachable | Only free source of a survey range, but HTML and its terms restrict scraping |
| Investing.com, MarketWatch, FXStreet, CME FedWatch | — | — | — | blocked | Bot protection / captcha / token / explicit IP block and ToS against scraping. Excluded |

## Do they agree?

| Target | Values |
|---|---|
| FOMC Oct 28, P(hike) | Kalshi 0.69 · Polymarket 0.68 · fed funds futures 0.70 |
| CPI y/y, Sep | Kalshi median 3.58 (p10 3.45, p90 3.75) · Cleveland nowcast 3.57 |
| Core CPI y/y, Sep | Kalshi 2.39 · Cleveland 2.39 |
| CPI m/m, Sep | Kalshi 0.53 · Cleveland 0.50 |
| Payrolls, Sep | Kalshi median 90k, p10 −10k (wide); no point consensus 9 days out |
| Initial claims (09-24) | TradingView 201 · ForexFactory 201 · Nasdaq 201k |
| Durable goods m/m (09-25) | TradingView −0.4 · ForexFactory −0.3 (panels differ) |

Previous prints against FRED: TradingView matched claims, payrolls,
unemployment, core PCE and durables; its Q2 GDP "previous" (2.1) was not the
second estimate FRED holds (1.5). CPI y/y "3.4" matches the release's
unadjusted basis.

Found while checking: FRED has no October 2025 CPI (shutdown), and counting
rows made "CPI y/y" compare 13 months — the build now matches changes by date
(`compute/periods.py`).

## Recommended stack

1. **Distribution, weeks ahead:** Kalshi for every release it lists, showing
   open interest and spread beside the ladder; Polymarket and fed funds
   futures as independent checks on the Fed.
2. **Point consensus, the final week:** TradingView (fastest, widest,
   previous prints mostly right), cross-checked by Nasdaq; ForexFactory once
   per run at most.
3. **Independent anchors:** Cleveland Fed nowcast (inflation), GDPNow,
   breakevens from FRED.
4. **Actuals:** the agencies via FRED, date-aligned.

Markets and surveys answer different questions: a Kalshi ladder is where
money is, with a risk premium and thin books in places; a survey median is
what economists wrote down. The page should label which is which.

## Mapping corrections (2026-09-24)

Two of the joins above were right as observations and wrong in the probe's
JSON. The success rates and the quoted medians are unchanged; what changed
is which contract is allowed to fill a target.

Nasdaq's `date` parameter is the calendar day after the US release. Thursday
2026-09-24 initial claims (consensus 201K, previous 196K) are on the 09-25
page; Friday 2026-09-25 durable goods (−0.3, previous 1.1) are on the 09-26
page; the 09-30 GDP and PCE prints are on the 10-01 page. The probe was
matching the page date to the release date, so `content` stayed empty while
the event name still showed up in `_names`. A page is now dated back one
day. The lead shares in the table were counted on the page date, one day
late. CPI, core CPI and core PCE are each listed twice under one name, with
identical descriptions; the yearly row is the one whose previous print is at
least twice the monthly one (3.4 against 0.4, 2.4 against 0.3, 3.3 against
0.2). When the two prints are less than twice apart, neither is used.

Kalshi's "earliest close on or after the release" rule answered a different
question twice. `KXGDP` has no open Q2-final contract; the rule returned Q3
growth, which closes 2026-10-30. `KXPCECORE` on 2026-09-30 is "how much will
core PCE increase in Aug", strikes of 0.1, not August year-over-year. An
event is used only when it closes on the release date and its title is that
print, so both of those stay unmatched and the ignored event is recorded.
Claims thresholds are worded "At least 180,000", not "Above"; those ladders
are read, in thousands.

## On the catalysts timeline

The same joins are what the CATALYSTS tab shows. A survey point comes from
TradingView, checked against Nasdaq and ForexFactory when they have a number.
A Kalshi distribution is shown only when that contract closes on the release
date and is the same transform, with its median, 10th to 90th percentile and
open interest. Cleveland's nowcast is shown only for the month the release
covers. The Q3 GDP contract is not attached to the Q2 final, and the August
core PCE market is labeled month-over-month, not year-over-year.
