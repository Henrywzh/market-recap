# market-recap

Live: **https://market-recap-b5p.pages.dev**

A post-market recap dashboard for the US equity market, built entirely on
free, attributable data sources and published as a static site.

There is no backend, no API key and no paid data feed. A Python build step
fetches the day's sources, writes JSON artifacts, and a static page renders
them.

## What it shows

| Tab | Contents |
|---|---|
| **MARKETS** | SPY/QQQ/IWM quote strip, SPX/NDX drawdown with sessions since the high, advance/decline, a price + net-breadth + movers block for **each index**, a **watchlist** of names no index holds, sector performance / weight / **contribution**, sectors rebased to 100, % of each sector above its moving averages, SMA200 slope by sector |
| **HEAT MAPS** | S&P 500 treemap sized by the **issuer-published SPY weight** and coloured by return; US ETF treemap sized by AUM and coloured by estimated net flow |
| **FIXED INCOME** | Published par yield curve vs. 1 week / 1 month / start of year, level and bps change by tenor, 10Y−2Y and 10Y−3M spreads |
| **MACRO** | Commodity futures/ETF proxies with multi-period returns, last 12 monthly inflation releases as a heat table |
| **TECHNICALS** | Any A/B relative-strength ratio with 60/200MA and MACD; single-ticker price with 20/50/200 SMA and a ±1.5σ band, z-score regime, SMA slope, and forward return by z-score band |
| **CROSS-LISTING** | A US line against its home-market line at the depositary ratio, with the diagnostics that say whether the series measures a dislocation or a session gap |
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
make install
make refresh
make serve
```

`make refresh` is the whole pipeline: fetch, build, **validate**, prune. It
exits non-zero if anything would put a wrong number on the page, so it is also
what the nightly job runs. `make help` lists the rest.

Rebuild a single tab while iterating:

```bash
python -m market_recap.cli refresh --panels markets --skip-dcf
```

### Running it on a schedule

The nightly job is a GitHub Actions workflow,
[`.github/workflows/refresh.yml`](.github/workflows/refresh.yml): weekdays at
23:37 UTC it tests, refreshes with `--strict`, and deploys only if that passed.
It runs on GitHub's machines, so it does not depend on a laptop being awake —
the launchd job this replaced missed its first night because the lid was shut.

```bash
make status    # last five runs, and the as_of the live site is showing
make run-now   # trigger it now (gh workflow run refresh.yml)
```

A failed scheduled run emails the repo owner. `workflow_dispatch` takes a
`deploy` input, so a run can build and validate without publishing.

Not the closing bell, because the publishers this reads post after it: State
Street's holdings and NAV files land in the evening, and Treasury sometimes
does not post the par curve until early evening ET. A job firing at 16:00 ET
builds a page entirely from the previous session and reports itself perfectly
healthy. GitHub cron is UTC, and 23:37 UTC is after 18:30 New York in both
halves of the year:

| UTC | New York |
|---|---|
| 23:37 | 19:37 EDT (Mar – Nov) |
| 23:37 | 18:37 EST (Nov – Mar) |

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

`data/cache` is carried between runs with `actions/cache`. It is not state:
every artifact rebuilds from the publishers, so an evicted cache costs one
slow run and more requests to them, never a wrong number.

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

## Layout

```
config/dashboard.toml      the contract: indices, universe, windows, thresholds
src/market_recap/
  config.py                paths, definitions (a trading year), cache policy
  cache.py                 one on-disk cache for every feed, with pruning
  sources/                 one module per publisher
  compute/                 returns, breadth, technicals — one definition each
  panels/                  one module per tab -> one JSON artifact
  context.py               constituents + prices, fetched once per build
  build.py                 orchestrator, writes manifest.json
  validate.py              checks the artifacts against the contract
web/                       static site (ES modules, ECharts from CDN)
artifacts/                 generated JSON the site reads
data/cache/                raw snapshots and parsed frames, pruned each build
```

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

## Known limits

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
- Sector and sub-industry labels are current, not point-in-time. Members of
  the S&P 500 carry GICS labels; Nasdaq-100 members and watchlist names outside
  it are labelled from Yahoo's taxonomy mapped onto the same GICS sector names,
  so sub-industry wording differs between the two groups.
- Line items a filer did not tag are left blank and are editable in the model.

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
