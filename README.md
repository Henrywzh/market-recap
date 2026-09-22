# market-recap

A post-market recap dashboard for the US equity market, built entirely on
free, attributable data sources and published as a static site.

There is no backend, no API key and no paid data feed. A Python build step
fetches the day's sources, writes JSON artifacts, and a static page renders
them.

## What it shows

| Tab | Contents |
|---|---|
| **MARKETS** | SPY/QQQ/IWM quote strip, SPX/NDX drawdown with sessions since the high, advance/decline, SPX price and net-breadth charts, top 10 gainers/losers, sector performance / weight / **contribution**, sectors rebased to 100, % of each sector above its moving averages, SMA200 slope by sector |
| **HEAT MAPS** | S&P 500 treemap sized by the **issuer-published SPY weight** and coloured by return; US ETF treemap sized by AUM and coloured by estimated net flow |
| **FIXED INCOME** | Published par yield curve vs. 1 week / 1 month / start of year, level and bps change by tenor, 10Y−2Y and 10Y−3M spreads |
| **MACRO** | Commodity futures/ETF proxies with multi-period returns, last 12 monthly inflation releases as a heat table |
| **TECHNICALS** | Any A/B relative-strength ratio with 60/200MA and MACD; single-ticker price with 20/50/200 SMA and a ±1.5σ band, z-score regime, SMA slope, and forward return by z-score band |
| **DCF** | SEC-filled 5-year history, your 5-year forecast, WACC, terminal value, equity bridge and a WACC × exit-multiple sensitivity grid |

## Data sources

Every one of these is free and requires no account.

| Source | Used for | Notes |
|---|---|---|
| **SSGA daily holdings** (`holdings-daily-us-en-<fund>.xlsx`) | S&P 500 and Nasdaq-100 constituents, official index weights, share counts | The issuer's own published basket with an explicit as-of date |
| **SSGA NAV / premium history** (`navhist-...`, `pdhist-...`) | Net flow and premium for State Street funds | Daily NAV, shares outstanding and premium back to 2003 |
| **BlackRock fund download** | Net flow for iShares funds | The workbook's `Historical` sheet carries NAV and shares outstanding back to inception; fund ids resolve through the iShares product screener |
| **Vanguard fund API** (`/vmf/api/<ticker>/{profile,price}`) | Premium to NAV, and whether an ETF is one share class of a larger fund | No shares-outstanding history, so no flow series |
| **Wikipedia** — List of S&P 500 companies | GICS sector and sub-industry | Current descriptive labels, cached weekly |
| **Yahoo Finance** via `yfinance` | Daily closes for constituents, ETFs and indices; ETF AUM and shares outstanding; commodity futures | Unofficial wrapper around a mutable service |
| **US Treasury** daily par yield curve XML | The yield curve | Official publication; "latest published" is not always today |
| **FRED** `fredgraph.csv` | PCE, core PCE, trimmed-mean PCE, personal income and spending | Keyless CSV export; current vintage, not point-in-time |
| **SEC** XBRL company facts | DCF historical line items | Annual 10-K/20-F/40-F figures with their filing dates |

### Two things worth knowing about the feeds

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
pip install -e .
python -m market_recap.cli refresh
```

Then serve the repository root and open `web/index.html`:

```bash
python3 -m http.server 8000
```

Rebuild a single tab while iterating:

```bash
python -m market_recap.cli refresh --panels markets --skip-dcf
```

## Layout

```
config/dashboard.toml      the contract: universe, labels, series ids
src/market_recap/
  sources/                 one module per publisher
  compute/                 returns, breadth, technicals — one definition each
  panels/                  one module per tab -> one JSON artifact
  context.py               constituents + prices, fetched once per build
  build.py                 orchestrator, writes manifest.json
web/                       static site (ES modules, ECharts from CDN)
artifacts/                 generated JSON the site reads
data/cache/                raw snapshots and the day's price cache
```

## Design rules this repo follows

- **Absence is rendered as an em dash, never as zero.** "No data" and "no
  change" are different statements.
- **A panel that fails leaves a named gap.** An empty tab with no explanation
  reads like a true report of a quiet market.
- **One definition per concept.** A "1M return" is 21 trading days on every
  tab, or the tabs contradict each other.
- **Every number carries a source and an observation date**, shown in the
  footer with a freshness label.
- **Area and colour stay independent on the heat map.** Tile size is the
  published index weight; colour is return.

## Known limits

- **ETF net flow covers 27 of 34 funds.** It is the daily change in the
  issuer's published shares outstanding valued at that day's NAV, taken from
  State Street's or BlackRock's own history, so it is measured and reaches back
  to each fund's inception. Vanguard, Invesco and USCF publish no equivalent
  daily share history, and a sampled substitute is not offered: a vendor's
  `sharesOutstanding` for QQQ disagrees with its own assets-over-price by 67%,
  and day-over-day changes in a field that inconsistent would be fiction.
- **Four tiles are drawn too large.** VOO, VTI, VEA and VWO are single share
  classes of funds that also have investor, admiral and institutional classes,
  and the reported total assets cover all of them — $2.3tn for VTI. Vanguard's
  own `hasMoreThan1ShareClass` flag is what detects this; the tiles are marked
  `*` and the caption says so.
- Change in NWC is the year-over-year move in current assets less current
  liabilities as filed. It does not strip out cash, so a company that banked
  cash shows a working-capital build. The DCF tab says so beside the row.
- FRED values are the current vintage and reflect later revisions. They are a
  release table, not a record of what was known on the day.
- Sector and sub-industry labels are current, not point-in-time.
- Line items a filer did not tag are left blank and are editable in the model.

## Not investment advice

This is a research and teaching tool. The DCF tab in particular is a model you
fill in yourself; it does not produce a recommendation.
