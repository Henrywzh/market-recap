# Risk and pricing sources

Probe results for every source behind RISK → RISK and RISK → PRICED PATH,
in the style of `docs/expectation_sources.md`. Probed 2026-09-26 with the
project's own User-Agent (`market-recap/0.1 (research; <contact>)`). A source
that refuses that client is recorded as refused and left out; it is not
fetched with a browser's identity.

## Used

| Source | What | History | Notes |
|---|---|---|---|
| Cboe CDN `api/global/us_indices/daily_prices/{SYM}_History.csv` | VIX 1990, VIX9D 2011, VIX3M 2009, VIX6M 2008, VIX1Y 2007, VIX1D 2022, VVIX 2006, SKEW 1990, COR1M/COR3M 2006 | as listed | Official closes. Most of these were launched after their first row: the earlier part is Cboe's back-calculation (a *back-calculated history*, not what was published then). COR1M/COR3M are on a methodology revised and back-filled in 2022. Tiles say so. |
| Cboe CDN `data/us/futures/market_statistics/historical_data/VX/VX_{expiry}.csv` | Daily settlement of each monthly VIX future | each contract's life | Expiry = 30 days before the next month's third Friday; a holiday moves it a day earlier (the fetcher tries the day before). 13 expired contracts are read so the front-month spread has a year of history. |
| Cboe CDN `data/us/options/market_statistics/daily/{date}_daily_options` | Put/call ratios for one session | one file per session | Fetched one session at a time (≈260 files, cached a year each). Only the trailing year is used. |
| FRED `fredgraph.csv` | BAA10Y (1986), NFCI (1971), WALCL/WTREGEN (2002, weekly), RRPONTSYD (2003), DFII10, OVXCLS; EFFR, DFEDTARL/U, T5YIE, T10YIE, T5YIFR, DFII5, GDPNOW | as listed | Current vintage, not point-in-time. **ICE BofA spreads (BAMLH0A0HYM2, BAMLC0A0CM, BAMLH0A3HYC) are served for the last three years only** (first row 2023-09-26), so their percentiles span three years; Moody's Baa − 10Y is the long credit series. GDPNOW is one reading per quarter. |
| Yahoo | ^MOVE (2002), HYG (2007), IEF, LQD (2002), ^GSPC (1927) | as listed | ^GSPC extends the build's own index closes backwards; the build's closes win where both exist. |
| Yahoo chart API, `ZQ{M}{YY}.CBT` | Fed funds futures, daily closes per contract | about a year per contract | Delayed; read at the close. |
| Yahoo chart API, `SR3{M}{YY}.CME` | Three-month SOFR futures | **latest quote only** | No history on Yahoo: the week-ago and month-ago SOFR paths come from the snapshot branch once it has them. |
| CFTC Socrata `gpe5-46if` (TFF) | Leveraged-money long/short/OI | 2006 | Queried by contract code (13874A E-mini S&P, 209742 Nasdaq mini, 043602 10Y note, 1170E1 VIX), because CFTC renamed markets in 2022 and a name filter cuts the history there. Positions are as of Tuesday, published Friday. |
| Kalshi `trade-api/v2/events` | Fed decision (KXFEDDECISION) and release ladders | open markets | Mid when the spread is ≤ 10¢, else last trade. Meeting dates after the Fed's published calendar are taken from the Fed decision contracts' close dates. |
| Polymarket gamma API | Fed decision markets | open markets | Probability of a hike at a meeting. |
| Snapshot branch (`snapshots`) | Intraday rates and event-market pricing, option chains | from 2026-09-26 | Read from a shallow checkout at `[snapshots] root`; absent locally unless checked out. |

## Refused or not machine-readable (not used)

| Source | Result |
|---|---|
| AAII sentiment survey (`aaii.com/files/surveys/sentiment.xls`) | HTTP 403 to the project's client (serves a browser). Left out rather than fetched as a browser. |
| NAAIM exposure index | The page loads its data by script; no downloadable file. |
| CNN Fear & Greed | A composite score (the page shows no composites), and its endpoint refuses non-browser clients. |

## Thresholds

Each tile's threshold is in `[[risk.tiles]]` in `config/dashboard.toml`,
written on 2026-09-26 before the page drew any series. They are round
levels, not fitted; changing one is a commit with its reason.
