# market-recap

Live: **https://market-recap-b5p.pages.dev**

A post-market recap dashboard for the US equity market, built entirely on
free, attributable data sources and published as a static site.

There is no API key and no paid data feed. A Python build step fetches the
day's sources, writes JSON artifacts, and a static page renders them. The one
piece of server code is the live strip's quote function (below); everything
else is the static build.

## What it shows

The views are grouped by the question they answer
(`docs/information_architecture.md`; the grouping itself is `web/js/routes.js`):

| Group | Views |
|---|---|
| **MARKET** | **Overview** (the default view) · Indices · Heat maps · Sectors (rotation and index/sector P/E) |
| **RISK** | **Risk** · Rates & macro · **Priced path** |
| **NAMES** | Monitor · Screen (VALUATION & QUALITY) · **Ticker** · Cross-listing |
| **CATALYSTS** | Calendar · Earnings · Themes · **AI chain** |
| **TOOLS** | Technicals · Trade Desk · ETF X-Ray · DCF |

**Overview** is the one-glance read: the live strip; stocks (S&P 500,
Nasdaq 100, Russell 2000, equal-weight S&P) with 1D/1W/1M/YTD and the
distance from the 52-week high; breadth (members up and down over a day, a
week and a month, the share above the 50- and 200-day averages, new highs
and lows); rates and credit (2Y, 10Y, 2s10s, real 10Y, HY and IG spreads)
with the next FOMC's pricing; the dollar, crude, copper, gold and VIX; the
latest macro prints; and the next three sessions. Each row carries six
months of line. **Indices** is the former MARKETS page (charts, movers,
sector tables). **Risk** opens with the **systematic anchor** (the frozen v1
exposure control from quantamental-lab, re-implemented and checked to
reproduce it exactly), a self-computed Fear & Greed gauge after CNN's
seven components, and ten core series -- trend, breadth, VIX and its
term structure, HY spread, real yield, the dollar, copper/oil and NFCI --
each a tile with level, 1Y and full-history percentile, week change and a
threshold written in `config/dashboard.toml` before the page drew it; never
a score. The other series are folded beneath (sources and probes:
`docs/risk_sources.md`). **Priced path** computes each FOMC meeting's
probabilities from fed funds futures beside Kalshi and Polymarket, the path
a week and a month ago, the SOFR path and every open Kalshi release ladder.

**Ticker** (`#ticker/AAPL`) is one company on one page, reached from any
ticker link. It opens with the name's situation (what the street expects,
how fast that moved, the multiple paid for it, how beats were taken), the
next or last report, a timeline of its own events and what is ahead
(peers' reports, macro dates, its themes' data releases, announced and
hand-kept company events), and WHAT MOVED IT -- every report and large move
with what happened that session, headlines included; then header readings, price and
trend, P/E against its own ten years, valuation against the sector median,
evidence (MONITOR's, plus insider buying from Form 4, short interest and
rating changes for focus names), earnings reactions to the last eight 8-K
releases against the options-implied move, the IV term structure, and the
filed statements. Each section is drawn by
the panel that owns it, so nothing is computed twice. Views that take a
ticker read it after a slash (`#dcf/MSFT`, `#technicals/NVDA`); hashes from
before the regrouping (`#financials`, `#fixed-income`, `#macro`, `?ticker=`)
still land on the right view.

**Trade Desk** (`#trade/SPY`) is for US stocks and index ETFs held overnight
to weeks. SETUPS & SIZE: a price chart on traded (split-adjusted, not
dividend-adjusted) closes with the 20/50/200-day averages and the prior
20-session and 52-week closing extremes; a price ladder of every level above
and below the close; ATR, 20-day dollar volume, the latest opening gap and,
with a same-session option snapshot, the ATM-straddle range; and a sizing
calculator capped by stop risk, position size and a share of dollar volume
(the spread is an assumption you enter). OVERNIGHT: ES/NQ, Asia and Europe,
and pre/post-market prints for the top 30 S&P 500 weights plus the
watchlist, polled only while that tab is visible. SCORECARD: forward returns
after the anchor's states (daily since 1993), Fear & Greed extremes and the
trend proxy, against any day -- descriptive and in-sample. Buyback blackout
and insider buying are on RISK → POSITIONING.

The panels, as each is built:

| Tab | Contents |
|---|---|
| **MONITOR** | Research queue over the S&P 500 and the watchlist. A name enters at a 20% drawdown from its 1Y high or when it trails its sector peers (company excluded) by 10 pp over 1M. **TODAY** lists what changed since the previous build (entered, stabilising, evidence turned, reported, left), with weak-as-a-whole sectors grouped as one event; **QUEUE** has a price-state × evidence-state 2×2; evidence for and against (FY1 EPS revisions from Yahoo, revenue, FCF, last quarter vs consensus) is listed, never scored; candidate history persists between builds, and watch/exclude reasons live in `config/monitor_notes.toml`. See [the monitor contract](docs/monitor.md). |
| **MARKETS** | A **live intraday strip** (see below), then the recap: SPY/QQQ/IWM quote strip, SPX/NDX drawdown with sessions since the high, advance/decline, a price + net-breadth + movers block for **each index**, a **watchlist** of names no index holds, sector performance / weight / **contribution**, sectors rebased to 100, % of each sector above its moving averages, SMA200 slope by sector |
| **CATALYSTS → CALENDAR** | Things to watch, in two lanes. **Macro & broad index**: BLS, BEA and Census releases at the time each agency publishes, FOMC decisions / press conferences / minutes and Board speeches from the Fed's calendar, announced Treasury coupon auctions, rule-based events (options expiry and quad witching, S&P rebalance, VIX expiry, jobless claims, ISM, EIA crude inventories) and hand-kept events (elections, deadlines) from the config — each with the previous print from FRED and the period it covers. **Single name**: earnings of every S&P 500 / Nasdaq-100 member and watchlist name with before-open / after-close timing, consensus EPS, estimates and index weight. A **last session** block shows what was released and who reported, with EPS vs. consensus and the day's move. Times in New York and the reader's own zone; every event says how its date is known | High-importance releases (FOMC, CPI, payrolls, GDP) are listed 45 days out. After a release the last-session block shows the actual against the survey point (TradingView).
| **CATALYSTS → EARNINGS** | S&P 500 earnings in three blocks. **FactSet Earnings Insight** figures read from its articles (growth, beat rates, forward P/E vs its 10-year average, the quarter's and year's EPS revision against FactSet's typical one; history from 2014). A **daily bottom-up revision tracker** built from every member's consensus trend (current quarter, this year and next, 7–90 days, by sector, with the names that moved it). The **reporting season** from Nasdaq's calendar: reported, beat rate, surprise, growth against year-ago EPS captured before each report |
| **CATALYSTS → THEMES** | Six groups of names that trade together (cloud & AI capex, semiconductors & memory, energy, banks, consumer, housing), each with a proxy (an ETF, or an equal-weight basket) and its run-in against the S&P 500, its bellwethers' next reports (scheduled, or projected from their own rhythm) with how far the proxy moved on their past reports, and a six-week calendar of those reports, the macro releases that bear on it and its own data's due dates. CLOUD adds hyperscaler capex from 10-Q/10-K XBRL, three Taiwanese AI-server makers' monthly revenue, OpenRouter tokens and estimated revenue by model author, and the Ramp AI Index; SEMIS adds TSMC and Nanya monthly revenue, Korean IC exports and the memory, DRAM and flash lines inside them, BLS semiconductor producer and import price indexes, ADATA's monthly memory note and UK retail memory/CPU prices read from PCPartPicker's trend charts; ENERGY adds EIA's weekly crude, gasoline, distillate and gas inventories against the same week of the last five years, refinery utilization and production, WTI/Brent/Henry Hub, the 3-2-1 crack and the pump price; HOUSING adds the 30-year mortgage rate, starts, permits, new home sales, months' supply and Case-Shiller; BANKS adds H.8 loans and deposits, the 2s10s and 3m10y curve, the high-yield spread, call-report delinquency rates and the loan officer survey; CONSUMER adds retail sales, real spending and the saving rate, consumer credit, Michigan sentiment and jobless claims (all from FRED, each dated by when its publisher releases it). A RELEASE DAYS card for each of the four shows how its ETF moved beyond the S&P 500 on the session of each past release of the series that bear on it (payrolls, core CPI, retail sales, claims, starts, new home sales, EIA crude stocks): the size of the move against any other day, and how often it rose after a print above or below the published forecast (TradingView's economic calendar, back to 2016), or its own trend where no forecast covers most releases. Each of the four also shows what moves the names: each bellwether's correlation and beta with oil, gas and the crack, the 10-year yield, the curve, the high-yield spread or gasoline futures, over the last year, and its series feed the stock cards' since-the-last-report table |
| **HEAT MAPS** | S&P 500 treemap sized by the **issuer-published SPY weight** and coloured by return; US ETF treemap sized by AUM and coloured by estimated net flow |
| **RATES & MACRO → FIXED INCOME** | Published par yield curve vs. 1 week / 1 month / start of year, level and bps change by tenor, 10Y−2Y and 10Y−3M spreads |
| **RATES & MACRO → MACRO** | Commodity futures/ETF proxies with multi-period returns, last 12 monthly inflation releases as a heat table |
| **TECHNICALS** | Any A/B relative-strength ratio with its moving averages and MACD over a chosen period; single-ticker price with **your own MA periods, slope window and period**, a ±1.5σ band, z-score regime, SMA slope, and forward return by z-score band. Every indicator is computed in the browser from the baked close history, by one module tested against pandas |
| **ETF X-RAY** | Every fund on the ETF heat map looked through to its holdings, from the **issuer's own file** (State Street, iShares and Invesco daily, Vanguard monthly): concentration (top-10 weight, effective N), sector and country weights against SPY, the top 25 holdings with each one's contribution to the day, overlap with every other fund, and a **valuation look-through** (P/E, P/B, ROE, FCF and dividend yield, growth, margin) aggregated like an index and joined to the VALUATION rows, with the share of the fund it covers. Bond funds show duration, yield to maturity, coupon and maturity buckets. Funds with no usable holdings file (the commodity funds) are listed with the reason, never proxied |
| **CROSS-LISTING** | A US line against its home-market line at the depositary ratio, with the diagnostics that say whether the series measures a dislocation or a session gap |
| **VALUATION → VALUATION & QUALITY** | Every S&P 500 / Nasdaq-100 member on one sortable table: P/E, EV/EBITDA, EV/Sales, P/B, FCF / dividend / shareholder yield, ROE, ROIC, gross profitability, margins, growth, accruals, leverage, interest cover, Piotroski F-score and margin stability — trailing twelve months from each company's own 10-Qs, market cap from the close. Valuation × quality scatter, sector medians, and colour by rank within sector. **P/E against each company's own ten years**: price ÷ TTM EPS as it was filed at the time, on operating earnings (stake gains, divestitures and one-off tax items taken out) or as reported, with its median, percentile band and where today sits |
| **FINANCIALS** | Ten fiscal years of income statement, balance sheet and cash flow for every S&P 500 and Nasdaq-100 member, with key ratios, each column's period end and last filing date, restatements applied and pre-split years put on today's share basis |
| **VALUATION → DCF** | SEC-filled 5-year history, your 5-year forecast, WACC, terminal value, equity bridge and a WACC × exit-multiple sensitivity grid |

## Data sources

Every one of these is free and requires no account.

| Source | Used for | Notes |
|---|---|---|
| **SSGA daily holdings** (`holdings-daily-us-en-<fund>.xlsx`) | S&P 500 and Nasdaq-100 constituents, official index weights, share counts | The issuer's own published basket with an explicit as-of date |
| **SSGA NAV / premium history** (`navhist-...`, `pdhist-...`) | Net flow and premium for State Street funds | Daily NAV, shares outstanding and premium back to 2003 |
| **BlackRock fund download** | Net flow and ETF X-RAY holdings for iShares funds | The workbook's `Historical` sheet carries NAV and shares outstanding back to inception; fund ids resolve through the iShares product screener |
| **Vanguard fund API** (`/vmf/api/<ticker>/{profile,price,characteristic,portfolio-holding}`) | Premium to NAV, whether an ETF is one share class of a larger fund, that share class's month-end net assets (tile size), and monthly stock holdings for ETF X-RAY | No shares-outstanding history, so no flow series; holdings published weeks after month end, with no sector or country |
| **Wikipedia** — List of S&P 500 companies | GICS sector and sub-industry | Current descriptive labels, cached weekly |
| **Yahoo Finance** via `yfinance` | Daily closes for constituents, ETFs and indices; ETF AUM and shares outstanding; commodity futures | Unofficial wrapper around a mutable service |
| **US Treasury** daily par yield curve XML | The yield curve | Official publication; "latest published" is not always today |
| **FRED** `fredgraph.csv` | PCE, core PCE, trimmed-mean PCE, personal income and spending | Keyless CSV export; current vintage, not point-in-time |
| **BLS / BEA** iCalendar feeds, **Census** indicator calendar, **Federal Reserve** calendar JSON, **Treasury** fiscaldata upcoming auctions | CATALYSTS macro lane | Each agency's own schedule with its release time; Treasury lists auctions only once announced, about a week ahead |
| **Invesco** holdings API (`dng-api.invesco.com/.../shareclasses/<CUSIP>/holdings/fund`) | ETF X-RAY holdings for QQQ and RSP | Unofficial JSON behind invesco.com; asked by ticker it answers for QQQ only, so funds are named by CUSIP. No shares-outstanding history, so still no flow |
| **FactSet Insight** Earnings Insight articles (`insight.factset.com/topic/earnings`) | CATALYSTS → EARNINGS FactSet block | Figures parsed from article text (parser shared with alternative-data's `factset_earnings_data`); history before the first build is the committed seed `data/reference/factset_earnings_insight.csv`. Weekly at best; numbers only, credited and linked |
| **Nasdaq** earnings calendar (`api.nasdaq.com/api/calendar/earnings`) | CATALYSTS single-name lane | Unofficial JSON behind nasdaq.com; timing, consensus EPS and, for past dates, reported EPS. Not marked company-confirmed |
| **SEC** XBRL company facts | FINANCIALS, VALUATION & QUALITY and the DCF | Annual and quarterly 10-K/10-Q figures with their filing dates, plus the cover-page share count; one parse per filer feeds all three tabs |
| **MOPS** (`mops.twse.com.tw/mops/api/t05st10_ifrs`) | THEMES: TSMC, Nanya, Quanta, Wiwynn, Wistron monthly revenue | The TWSE's disclosure system; published by the 10th. No publication date in the answer, so the date first seen here is kept |
| **Korea Customs Service** trade statistics (`tradedata.go.kr`) | THEMES: Korean IC (HS 8542) exports, plus memories (HS 854232) and the DRAM, flash, multi-chip and MCO lines inside it | Confirmed monthly figures, mid-month; certificate verification on. The breakout is export value, and value per kilogram of customs weight. It is not a spot price |
| **ADATA Industrial** Memory & Flash Market Watch | THEMES: monthly DRAM / NAND note | A module maker's read, quoted; its charts are images and are not read |
| **PCPartPicker** UK price trends (`uk.pcpartpicker.com/trends/price/{memory,cpu}/`) | THEMES: retail memory-kit and CPU prices | Read from the chart images' pixels (the page has no numbers); only ratios are reported, with the source linked. Its Cloudflare refuses cloud servers (HTTP 403) and is not worked around: the nightly build reads the committed ratios in data/feeds/pcpartpicker.json and does not ask the site. scripts/refresh_pcpartpicker.py refreshes that file from a home connection |
| **DART** (FSS electronic disclosure, public search `dsab007/detailSearch.ax`) | THEMES and AI CHAIN: Samsung Electronics and SK hynix results dates (the preliminary results first) | Their "영업(잠정)실적" fair disclosures, corrections dropped; no key needed |
| **Korea MOTIE** monthly trade release (`motir.go.kr`, PDF attachment) | THEMES: 1st-of-month semiconductor and total exports | Read with `pdftotext` (poppler, installed by the workflow); the site is slow, so only the last 13 releases are read, each cached once |
| **SEC EDGAR** earnings releases (8-K Item 2.02, Exhibit 99.1) | THEMES: NVIDIA Data Center revenue and outlook; capex guidance quoted from the releases | Segment revenue is not in XBRL company facts; matched text is quoted as written. Older submissions pages are read when a heavy filer's recent block (one year for the big banks) holds fewer than eight earnings releases; TSMC and ASML results come from their 6-K filings |
| **EIA** weekly history pages (`eia.gov/dnav/pet/hist`, `/dnav/ng/hist`) | THEMES: weekly crude, gasoline, distillate and gas inventories, refinery utilization, crude production | Keyless HTML tables, petroleum back to 1982, gas storage to 2010; current vintage. The 5-year average is the same week of the five years before |
| **Yahoo** front-month futures (CL, BZ, NG, RB, HO) | THEMES: oil, gas and the 3-2-1 crack | Cached apart from the members' prices |
| **Yahoo** market cap (quoteSummary `price`) | VALUATION: the market cap of a company whose filings count shares only class by class (Berkshire, Hershey, Ares), so P/E, EV and yields exist for it | Labelled on the row's share basis; such a row stays out of the index and sector P/E aggregates, as its per-share EPS may be in another class's shares |
| **FRED** BLS semiconductor prices (PCU334413334413, PCU3344133344131, IZ3344, IR21320) | THEMES: US producer and import price indexes for semiconductors | Public domain, keyless CSV, current vintage. BLS indexes of its own product basket, not DRAM or NAND spot quotes. Ids live in config/dashboard.toml |
| **FRED** housing series (MORTGAGE30US, HOUST, HOUST1F, PERMIT, HSN1F, MSACSR, CSUSHPINSA), GASREGW, DGS10 | THEMES: housing data, the pump price, rate sensitivity | Current vintage, keyless CSV |
| **Finnhub** company news (`FINNHUB_API_KEY`) | TICKER: headlines on large-move days and company events announced ahead (investor days, product events, FDA dates) | Free tier: about a year of news, 60 requests a minute; a budget per build, settled days kept a year; without the key, moves are explained from filings, ratings, peers and data only |
| **EDGAR filing index pages** | Earnings releases' acceptance time (Eastern), for the eight reports measured | The submissions JSON stamp ran twice the Eastern offset late in October 2026; fetched once per filing and kept |
| **ALFRED** (FRED's vintage archive, `FRED_API_KEY`) | THEMES: the day each FRED observation was first published and its first print (with the year-earlier figure as then known), for the release-day studies and the stock cards' since-the-last-report table, which marks a figure revised since | Free key; GitHub secret in CI, alternative-data's `.config` locally; without it, release lags are approximated |
| **FRED** bank and consumer series (TOTLL, DPSACBW027SBOG, T10Y2Y, T10Y3M, BAMLH0A0HYM2, DRALACBS, DRCCLACBS, DRCRELEXFACBS, DRTSCILM; RSAFS, RSFSXMV, PCEC96, PSAVERT, TOTALSL, UMCSENT, ICSA, CCSA) | THEMES: banks and consumer data, curve/credit sensitivity, stock-card drivers | Current vintage, keyless CSV; release dates approximated from each publisher's schedule (ICE BofA OAS: last three years only; Michigan sentiment a month behind) |
| **Yahoo** earnings archive (the visualization API `get_earnings_dates` reads) and quoteSummary `earnings` / `calendarEvents` | AI CHAIN: every report of 67 companies in seven markets, with its time of day and EPS surprise, and the next date | The archive stopped taking rows in mid-2025 (kept a year at a time); the last four quarters come from quoteSummary. The reports of July–September 2025 are missing for a company outside SEC filing and stay missing |
| **EDGAR full-text search** (`efts.sec.gov/LATEST/search-index`) | AI CHAIN: the sentence of each company's 10-K / 20-F / 40-F that names the other end of a link | Run by hand (`scripts/chain_evidence.py`) when the graph changes; the result is committed as `config/ai_chain_evidence.json` |
| **alternative-data** (github.com/Henrywzh/alternative-data) normalized files | THEMES: OpenRouter daily tokens and estimated revenue; Ramp AI Index | Read from the public repo, with the commit that last touched each file |

### Two things worth knowing about the feeds

DRAMeXchange spot and contract prices are not on this site. Its terms forbid republication, and contract history sits behind the member login. scripts/refresh_dramexchange.py archives the public homepage on this machine only, under data/private/dramexchange/, which is gitignored and is not read by the build.


**Identify yourself honestly.** FRED's edge accepts curl's own identifier
instantly and stalls the identical request when it carries a Chrome
User-Agent, because the claim contradicts the TLS fingerprint. `sources/http.py`
sends `market-recap/0.1 (research; ...)` and every feed accepts it.

**Yahoo drops symbols.** A single batch request for the S&P 500 returns 503
columns on one run and 497 on the next, and a second full sweep within a few
minutes comes back half empty. `sources/yahoo.py` re-requests what is missing
in smaller batches under a time budget and caches the day's closes, so a
rebuild costs seconds. Whatever is still missing is reported as a coverage
gap, never back-filled.

## Install and run

```bash
make install
make refresh
make serve        # static build only; make serve-live adds the quote function
```

`make refresh` is the whole pipeline: fetch, build, **validate**, prune. It
exits non-zero if anything would put a wrong number on the page, so it is also
what the nightly job runs. `make help` lists the rest.

Rebuild a single tab while iterating:

```bash
python -m market_recap.cli refresh --panels markets --skip-sec
```

### Running it on a schedule

The nightly job is a GitHub Actions workflow,
[`.github/workflows/refresh.yml`](.github/workflows/refresh.yml): weekdays at
23:47 UTC it tests, refreshes with `--strict`, and deploys only if that passed.
It runs on GitHub's machines, so it does not depend on a laptop being awake —
the launchd job this replaced missed its first night because the lid was shut.

```bash
make status    # last five runs, and the as_of the live site is showing
make run-now   # trigger it now (gh workflow run refresh.yml)
```

Two feeds are not fetched from GitHub's machines. PCPartPicker refuses cloud IPs, so a local job runs scripts/refresh_pcpartpicker.py each morning and commits data/feeds/pcpartpicker.json; the nightly build only reads that file. DRAMeXchange's terms forbid putting its prices on this site, so scripts/refresh_dramexchange.py archives the public homepage under data/private/ and never commits it.

A failed scheduled run emails the repo owner. `workflow_dispatch` takes a
`deploy` input, so a run can build and validate without publishing.

Not the closing bell, because the publishers this reads post after it: State
Street's holdings and NAV files land in the evening, and Treasury sometimes
does not post the par curve until early evening ET. A job firing at 16:00 ET
builds a page entirely from the previous session and reports itself perfectly
healthy. GitHub cron is UTC, and 23:47 UTC is after 18:30 New York in both
halves of the year:

| UTC | New York |
|---|---|
| 23:47 | 19:47 EDT (Mar – Nov) |
| 23:47 | 18:47 EST (Nov – Mar) |

GitHub can start a scheduled run late under load; minute 37 avoids the
on-the-hour and half-hour slots that are delayed most.

The run uses `--strict`, so a warning fails it. Nobody reads the output of an
unattended job, and a job that exits 0 on a degraded build is how a stale page
stays up for a week.

The job installs from `requirements.lock`, not from `pyproject.toml`'s ranges.
The first cloud run resolved pandas 3 and yfinance 1 — both newer majors than
anything this was tested on — and failed. `make lock` re-resolves the lock on
purpose; upgrading is then a commit that was tested, not something a clean
machine does on its own one night.

Two checks sit around the deploy, because `--strict` validates a build
against its own contract and cannot see the calendar:

- **Daily files expire at the session rollover, not after 24 hours.** Prices
  and issuer files count as fresh only if fetched after the latest weekday
  18:30 New York. With a plain 24-hour lifetime, a run starting a few minutes
  earlier than the night before reuses yesterday's closes and publishes a page
  one session behind that passes every check.
- **A deploy never moves the site backwards.** `scripts/guard_deploy.py`
  refuses a build whose `as_of` is older than the live page's, and refuses
  when it cannot read the live page — a guard that allows what it cannot check
  is not one.

`data/cache` is carried between runs with `actions/cache`. It is not state:
source-derived readings rebuild from the publishers, so an evicted cache costs one
slow run and more requests to them, never a wrong number. MONITOR's observation
ledger is different: cloud refreshes restore the last published monitor artifact,
and refuse to reset it if restoration fails. The workflow also archives that
artifact for recovery. Manual follows live in the reader's browser and can be
exported/imported. The cache key
includes `requirements.lock`'s hash: files written by other library versions
are not reused.

### Deploying

```bash
make deploy        # refresh, validate, then publish to Cloudflare Pages
make deploy-only   # publish what is already built
```

`make serve` and `make deploy` look at the same directory. The site is
assembled into `dist/` — `index.html` at the root with `artifacts/` beside it
— and that is the tree both serve and deploy read. Serving `/web/index.html`
locally while production served `/` would mean the deploy step rewrote asset
paths, and a path rewrite is the kind of build-time magic that works until the
day it silently does not, on the copy nobody runs locally.

The Pages project is `market-recap`. Creating it needed
`wrangler pages project create market-recap --production-branch main --force`,
because current wrangler delegates Pages commands to Workers and reads this
`wrangler.toml` as a Workers config with no entry point. `--force` is needed
only once, for the create; deploys run against Pages directly.

Credentials for the nightly job are two repository secrets,
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The token needs one
permission: **Account → Cloudflare Pages → Edit**. The account ID is required
because a Pages-only token cannot list accounts for wrangler to pick from.

wrangler is pinned in `package.json` rather than invoked through `npx
wrangler@latest`: a nightly job should not resolve a new major version over
the network overnight and find out what changed.

Deployment is by direct upload rather than Pages' git integration. The
artifacts are rebuilt every session and are not in git, so a git-triggered
build would check out a repository whose `artifacts/` is ignored and publish
an empty dashboard. Locally, authentication is `wrangler login` once; the nightly job uses the
secrets above and deploys only after `--strict` validation passes, because putting the bad page
in front of people and then telling a log file about it is not a deploy
strategy.

### Validation

`make validate` re-checks the artifacts on disk without refetching:

| Check | What it catches |
|---|---|
| `period_label` | a table offering a window nothing defines |
| `as_of` | one tab dated to a different session than the rest of the page |
| `coverage` | index members that never got a price |
| `preset` | a relative-strength preset naming a ticker no panel baked |
| `ratio_provenance` | a cross-listing ratio with no cited filing |
| `flow_attribution` | a fund with flow but no named provider |
| `freshness` | a source past its own staleness window |

These are not hypothetical. Every one of them has fired on this repository.

`make smoke` then opens every view of the built site -- plus the largest
names, a share class typed as `BRK.B`, a fund, an index and each theme -- in
headless Chrome (the installed one, through `playwright-core`), and fails on a
page that throws, logs an error, asks for a file the build lacks, renders
nothing, or prints `NaN` / `undefined`. The nightly job runs it after the build
and publishes nothing when it fails. `make test` runs pyflakes before the
Python and JavaScript tests.

## Layout

```
config/dashboard.toml      the contract: indices, universe, windows, thresholds
src/market_recap/
  config.py                paths, definitions (a trading year), cache policy
  cache.py                 one on-disk cache for every feed, with pruning
  sources/                 one module per publisher
  compute/                 returns, breadth, filed-statement ratios — one definition each
  panels/                  one module per tab -> one JSON artifact
  context.py               constituents + prices, fetched once per build
  build.py                 orchestrator, writes manifest.json
  validate.py              checks the artifacts against the contract
  snapshots/               recorded option chains and market pricing (not read by the page yet)
web/                       static site (ES modules, ECharts from CDN)
  js/technicals-math.js    every technical indicator; tested against pandas from tests/
artifacts/                 generated JSON the site reads
data/cache/                raw snapshots and parsed frames, pruned each build
data/snapshots/            checkout of the `snapshots` branch (recorded history)
```

## Recorded snapshots

Some history cannot be downloaded later for free, so
`.github/workflows/snapshots.yml` records it from the day it runs and
commits each run to the orphan `snapshots` branch (data only):

- **Option chains**, once a session from 15:10 New York (GitHub starts
  scheduled runs hours late, so the window runs to midnight: options stop
  trading at 16:00 and a later run records the closing quotes; a zero bid is
  unusable). About 50-90 underlyings (`[snapshots.options]`: index, sector
  and macro ETFs, the largest index weights, the watchlist, every name
  reporting within three days, and up to 15 MONITOR candidates).
  Per expiry, ATM IV, 25-delta put and call IV, the ATM straddle and open
  interest, all solved from bid/ask mids under Black-76 against the
  parity-implied forward, never Yahoo's last-trade IV. Contracts within 25%
  of spot are kept raw.
- **Market pricing**, four times a weekday: fed funds and SOFR futures,
  every open Kalshi market in the configured series, Polymarket's Fed
  markets. Inputs only; probabilities are derived from them later.
- **Consensus EPS**, each weekday evening: Yahoo's estimates (this and next
  quarter and fiscal year) for every company VALUATION values. Free sources
  publish only today's consensus, so this is the only way a forward P/E gets
  a history: each company's and each index's and sector's forward P/E is
  drawn from the recorded days, starting 2026-10-01. Until a year is
  recorded it is compared across companies and with FactSet's index figure,
  not with its own past.

Forward P/E is price over next-twelve-months consensus EPS (this fiscal
year's and next year's estimates, weighted by how much of each the coming
twelve months covers). Yahoo's estimates are on the analysts' basis --
adjusted EPS for most companies -- so a forward multiple is not the same
measure as the trailing one on filed EPS. The S&P 500's own forward P/E,
with its 5- and 10-year averages, comes from FactSet: the blog's articles in
season and the weekly Earnings Insight PDF every Friday (its text, via
pdftotext; the sector page is an image and is not read).

`make snapshot-options` and `make snapshot-expectations` write the same files
under `data/snapshots/` locally. The plan they serve is
`docs/information_architecture.md`.

## Live intraday strip

The top of MARKETS carries intraday prices for the quote strip, the indices
and the watchlist (Yahoo's v8 chart) and the 2Y/10Y/30Y Treasury yields
(CNBC's quote service). It is the only thing on the page that changes during
the session, and it is labelled that way: each price shows its source and its
age, the strip says whether the session is open, a price older than
`stale_after_seconds` during the session is marked STALE, and one that did not
arrive is a dash. The recap beneath it is untouched: every other figure is
the nightly build's close.

- **Refresh.** Every `refresh_seconds` (60) while the regular session is open
  and the tab is visible; every `closed_refresh_seconds` (300) otherwise, to
  notice the open. A hidden tab or another dashboard tab does not poll. The
  REFRESH button fetches on demand.
- **Server side.** `functions/api/quotes.js` is a Cloudflare Pages Function,
  deployed with the site because `wrangler pages deploy` picks up
  `functions/` from the repository root. It fetches only what `dist/live.json`
  lists; `site.build` writes that file from `config/dashboard.toml`
  (`[universe]`, `[[watchlist]]`, `[live]`), so the endpoint cannot proxy
  arbitrary symbols. Readers share one fetch per `server_cache_seconds` (15)
  per Cloudflare isolate, so clicks do not multiply requests to Yahoo.
- **Session.** Open means now falls inside the regular period Yahoo reports
  for the symbols, which handles weekends and exchange holidays without a
  calendar here. Change is against Yahoo's previous close.
- **Sources were chosen by measurement** from Cloudflare's edge (2026-09-24
  after the close, 2026-09-25 mid-session): Yahoo chart ~45 ms with prices a
  few seconds old, CNBC ~120 ms and ~15 s behind. Nasdaq (2-3 s per call) and
  Cboe (15-minute delay, up to 0.3% off) were not used.
- **Locally**, `make serve` has no function, so the strip reports HTTP 404;
  `make serve-live` runs the same tree under `wrangler pages dev` with it.

## Design rules this repo follows

- **Absence is rendered as an em dash, never as zero.** "No data" and "no
  change" are different statements.
- **A panel that fails leaves a named gap.** An empty tab with no explanation
  reads like a true report of a quiet market.
- **One definition per concept.** A "1M return" is 21 trading days on every
  tab, or the tabs contradict each other.
- **Every number carries a source and an observation date**, shown in the
  footer with a freshness label. The header shows how old the build is, not a
  ticking clock: this is a static build, and a live-looking clock beside stale
  data is a lie the page tells for free.
  The live strip is the one intraday element, and it carries its own age per
  price instead of borrowing the header's.
- **Short history degrades per reading, not per ticker.** A recent listing
  keeps the readings its history supports and names what the rest would need
  ("needs 200 sessions, has 51") rather than vanishing from the tab.
- **Area and colour stay independent on the heat map.** Tile size is the
  published index weight; colour is return.
- **A number that is a choice lives in `config/dashboard.toml`; a number that
  is a definition lives in `config.py` with a name.** A trading year is 252
  sessions whatever anyone wants; which windows a table offers is a preference.
  Nothing analytic is written as a literal in a builder — adding a third index
  is a config change, not a code change.
- **Identity is resolved from the publisher, never remembered.** A hard-coded
  BlackRock portfolio id for SHY returned the 0–1 Year Treasury fund, and
  nothing downstream would have shown that the flow series belonged to a
  different fund. Ticker→id now comes from BlackRock's own screener.
- **The build validates itself.** See the table above.
- **A new 10-Q reaches the page the night it is filed.** Company facts are
  megabytes per filer and SEC answers no conditional request for them, so they
  used to live out a fixed three-day cache: a 10-Q filed on Monday showed on
  Thursday. Each night the build now reads every filer's submissions index
  (tens of KB, updated as filings are accepted; six in parallel under SEC's
  ten-a-second limit, about a minute for 515 filers) and refetches only the
  company facts older than the latest 10-K/10-Q/20-F/40-F or amendment. A
  copy fetched within six hours of that filing is fetched again the next
  night, in case SEC had not processed it yet. The thirty-day cache lifetime
  is only the backstop. The manifest's `sec_filings` says how many were
  checked and refetched and keeps the latest filing date. Submissions-index
  freshness uses the oldest actual index-fetch date, so a quiet filer does
  not look like a failed fetch and a stale cache fallback stays visible.

## Known limits

- **Yahoo's recent sessions are checked against IVV's closes, and rebuilt when
  wrong or missing.** Yahoo has served a session as NaN, dropped one outright
  (1D then spanned two days), and on 2026-09-22 served adjusted closes that
  were a stale snapshot -- RCL +1.6% on a day it closed −6.1%, advancers 291
  against 248 -- which passed every check because every name had a price.
  Now the last five rows are checked against the NYSE calendar (a skipped
  session becomes an empty row), and the session on the IVV holdings date is
  compared name by name with the prices the fund's NAV was struck at; a
  median disagreement over 0.1% marks it wrong. A wrong or missing session is
  rebuilt from IVV (S&P 500 members), Nasdaq's historical quotes (other
  stocks, ETFs) and FRED (S&P 500 and Nasdaq-100), put on the adjusted basis
  with each name's factor from the session before. The MARKETS tab says so at
  the top, with the counts by source and anything still missing. IVV's file
  comes out the morning after, so the night's own session is checked against
  Nasdaq's closes for the 30 largest members instead; when too few answer,
  the page says the session was not cross-checked.
- **Optional feeds cannot hold back the page.** Validation has three levels:
  an error is not publishable, a warning makes `--strict` refuse the deploy,
  and a notice is shown on its tab and nothing more. The catalyst calendars
  and the ETF holdings files -- several of them unofficial endpoints -- report
  notices; prices, index holdings and SEC filings report warnings.
- **CATALYSTS notices a renamed release.** The macro lane matches agency
  titles by pattern, so a renamed release would silently vanish. The key ones
  carry `expect_within_days`; none found that far ahead in the agency's own
  calendar is reported on the tab.
- **The repository lives in `market-recap.nosync`.** macOS syncs the Desktop
  to iCloud, which was leaving `dist 2`, `dist 3`… conflict copies; a folder
  ending in `.nosync` is not synced, and `market-recap` is a symlink to it.

- **ETF X-RAY matches holdings within a market.** A ticker only names the same
  company on one exchange: EFA's `DG` is Vinci in Paris and its `EL` is
  EssilorLuxottica, and matching by ticker alone priced them as Dollar General
  and Estée Lauder. Lines are keyed by ticker *and* market (an iShares line by
  its exchange, a Vanguard line in an international fund by a US ISIN), so
  only US listings are priced or joined to VALUATION. That leaves the
  international funds' look-through valuation blank: under 50% of a fund
  matched, a fund multiple describes the matched names, not the fund. Sectors
  for SSGA and Vanguard funds, which publish none, come from this build's GICS
  labels or another fund's file in the same market; what stays unclassified
  (mostly Canada in VEA, and Indian and Thai names in VWO) is shown as such.

- **The cache is compressed where it pays.** SEC company facts are 3–4 MB of
  JSON per filer, of which the DCF reads six line items; 121 of them filled
  472 MB. They are stored gzipped now — the raw document, so nothing about
  reproducibility changes — which takes the whole cache from 557 MB to 55 MB.
- **ETF net flow covers 27 of 34 funds.** It is the daily change in the
  issuer's published shares outstanding valued at that day's NAV, taken from
  State Street's or BlackRock's own history, so it is measured and reaches back
  to each fund's inception. Vanguard, Invesco and USCF publish no equivalent
  daily share history, and a sampled substitute is not offered: a vendor's
  `sharesOutstanding` for QQQ disagrees with its own assets-over-price by 67%,
  and day-over-day changes in a field that inconsistent would be fiction.
- **EFA and EEM flows go unknown when iShares stops updating.** Their published
  share count has sat unchanged for up to 127 sessions (every other fund moves
  within 19), so past 20 unchanged sessions a window lying wholly inside that
  stretch is shown as unknown, not as a measured zero; longer windows that
  contain real changes are kept.
- **Vanguard tiles are month-end and rounded.** VOO, VTI, VEA and VWO are one
  share class of larger funds; a vendor's total assets cover every class
  ($2.3tn for VTI). They are sized by Vanguard's own share-class net assets
  (`/characteristic`, month end, published to one decimal: VOO's "$1.0
  trillion" is good to about 5%). A tile falls back to the whole-fund figure,
  marked `*`, only if that call fails.
- Sector and index rows in the sector table are the buy-and-hold return of
  **today's members at today's published weights**, from dividend-adjusted
  closes. Over days and weeks that tracks the index to a few basis points;
  over YTD it runs ahead of the price index by roughly the dividends plus
  whatever joined the index after rallying (+1.7pp in September 2026).
- Change in NWC is the year-over-year move in current assets less current
  liabilities as filed. It does not strip out cash, so a company that banked
  cash shows a working-capital build. The DCF tab says so beside the row.
- FRED values are the current vintage and reflect later revisions. They are a
  release table, not a record of what was known on the day.
- Sector and sub-industry labels are current, not point-in-time. Members of
  the S&P 500 carry GICS labels; Nasdaq-100 members and watchlist names outside
  it are labelled from Yahoo's taxonomy mapped onto the same GICS sector names,
  so sub-industry wording differs between the two groups.
- Line items a filer did not tag are left blank and are editable in the model.
- FINANCIALS reads US-GAAP only. IFRS filers (ASML, CCEP, FER, TRI) and
  registrants with no annual report yet are listed on the tab as not
  extracted, with the reason. Fiscal years are named by their period end,
  which matches NVIDIA, Microsoft and Apple; retailers whose year ends in late
  January call it the year before, so the period end is printed beside every
  label.
- VALUATION's market cap is the close times a filed share count, so its
  weak point is the count. Three things are handled and one is checked: a
  cover page that lists one class of several (then the diluted count is used),
  a diluted count with a units error (Waters filed 98.2 *billion*), and a split
  after the last filing (Amphenol, Monster in 2026 — applied from the split
  record Yahoo returns with the prices). Every count is then compared with the
  company's SPY weight, by company rather than listing; a count more than 2.5x
  off is listed on the tab. Berkshire, Visa and a few other multi-class filers
  tag no complete count at all and have no market cap rather than a guessed one.
- The P/E history is point in time. Each quarter's TTM EPS is built only from
  filings made by the day that quarter was first reported, and applies from
  the next session; every part is put on today's share basis by the splits
  after its own filing date. Prices are split-adjusted but not
  dividend-adjusted (`Close`, not `Adj Close`): a multiple on dividend-adjusted
  prices understates every past P/E by the dividends paid since. An EPS with
  no successor for two quarters expires rather than being carried forward
  (Monster stopped tagging `EarningsPerShareDiluted` in 2011). The table's P/E
  (market cap / net income) and the history's (price / EPS) are computed
  independently and compared; the ~2% that disagree by more than 25% are
  listed on the tab — mergers and spin-offs that move the share count,
  preferred dividends, large minority interests.
- The P/E history, its percentile and the index and sector P/E lead with
  **operating** earnings; REPORTED is one click away. Reported EPS counts
  whatever sits below the operating line: Alphabet's 2026 Q2 carried $99bn of
  gains on its equity stakes (Anthropic, SpaceX) against $41bn of operating
  income, and on reported EPS it sat at the bottom of its own ten years.
  Operating TTM EPS is pre-tax income capped at operating income less
  interest paid, taxed at the median of the company's own trailing tax rates
  over twelve quarters (bounded 0–35%), less minority holders' share, over
  diluted shares — every input as filed by the day the quarter was reported.
  Only a net gain below the line is removed: some filers' operating line
  leaves costs out (Disney tags its segment total), so a net loss stays.
  Financials and utilities, whose ordinary earnings are partly below the line,
  and companies that tag no operating line (Merck, J&J, Deere), are on
  reported EPS less gains on equity securities after tax. A company with too
  little operating history to rank stays on reported. The table's own P/E
  column stays reported; `P/E operating` sits beside it.
- A 10-Q never replaces a 10-K's figure for a whole year: Comfort Systems'
  2026 Q1 10-Q tagged its Q1 2025 operating income as all of 2025, and as the
  later filing it had won. A diluted share count 20x away from the one the
  filing's own net income and EPS imply is a units error (Waters) and the
  implied count is used.
- TTM is last fiscal year + year to date − the same span a year earlier. A
  line the latest 10-Q did not tag (Alphabet's Q2 2026 dividends) is taken
  from the quarter before, at most one quarter stale, and starred on the row.
  EBIT falls back to pre-tax income + interest, and D&A to depreciation +
  intangible amortization, for filers that tag no combined line.
- SEC's ticker map points at a company's *current* registrant. After a
  holding-company reorganisation (Exxon, 2026) that CIK has no history, so the
  extraction follows the accession-number prefix to the predecessor CIK, and
  only when the entity name matches.

## The cross-listing premium, and why it ships with diagnostics

Comparing two listings of one company looks like subtraction and is not. Two
inputs decide whether the number means anything, and both fail quietly.

**The depositary ratio must come from the filing.** SK hynix's Nasdaq line
prices at roughly 7.2 Korean shares per ADS if you back it out of today's
quotes — and using that figure forces the premium to zero and draws a flat
line forever. The 424B4 says one ADS is one-tenth of a common share, and at
that ratio the premium is about +40%. The panel cites the filing on the page.

**The home market closes first.** Seoul shuts roughly fourteen hours before
New York, so a same-date comparison sets a fresh US close against a stale one.
On this pair the daily change in the premium correlates +0.55 with the US
leg's own return and −0.63 with the home leg's, its day-to-day swing (11.7pp)
exceeds the spread of the level itself (9.0pp), and its autocorrelation is
0.14. Those are the fingerprints of a timing artifact, not a moving
dislocation, so the tab says to read the level and not the change.

What the gap does make usable is the lead: the US return today correlates
+0.59 with the home market's *next* session against +0.30 with the same date.
That is an overnight indicator, and it is what a desk actually uses an ADR
premium for.

## Not investment advice

This is a research and teaching tool. The DCF tab in particular is a model you
fill in yourself; it does not produce a recommendation.
