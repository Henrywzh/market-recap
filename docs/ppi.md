# PPI and AI-related industry prices

The PPI view is under **Risk → Rates & macro → PPI · AI prices**.
It is descriptive and contains no forecasting model or market-implied
expectations. It does not calculate an AI-demand index.

## Release identity and comparisons

`sources/ppi.py` discovers the publication timestamp from BLS's live summary,
then reads the corresponding dated archive's `ppi_nrtable1`. Discovery is
fresh on each build; the archive is cached through the shared HTTP/cache path.
Publication time is Eastern with DST. Parsing checks the publication identity,
reference month, table schema, unique final-demand commodity codes, valid
relative importance and required headline/core prints. Intermediate-demand
rows are excluded. The source URL, read time and decoded HTML SHA-256 remain
in `macro.json` under `ppi`.

The four cards show headline and **excluding food and energy**, MoM SA and
YoY NSA. This is not the separate exclusion of food, energy **and trade**;
that measure is shown separately in the official detail table.
TradingView consensus is joined only on US country, exact release day,
reference month and exact metric title. Duplicate or unmatched records leave
consensus blank. This is retrospective calendar consensus, not independently
frozen pre-release survey evidence. Actuals always come from BLS. Previous
values can include revisions; the detail table's prior MoM is BLS's own.

## Weights and attribution

BLS Table 1 reports relative importance with an annual reference month
(currently December of the previous year). Its date is displayed, unlike
CPI Table 6's preceding-month weight reference. Blue bars use a common 0–100%
scale and encode importance, not good/bad news or return predictions.
Goods + services + construction partition final demand; most other rows are
nested or overlapping. They must not be summed. No official monthly effects
are supplied by this parser, and weight times growth is not shown as an
official contribution. Trade-services indexes measure margins.

## AI-related industry observation set

The five IDs in `[macro.ppi].ai_series` match alternative-data's
`semiconductor_memory_data/sources/config.py` observation targets:

| Series | Official scope |
|---|---|
| PCU33443344 | Semiconductor and other electronic component manufacturing |
| PCU33423342 | Communications equipment manufacturing |
| PCU335313335313 | Switchgear and switchboard apparatus manufacturing |
| PCU334111334111 | Electronic computer manufacturing |
| PCU3341123341121 | Computer storage devices, excluding parts/attachments/accessories |

These are BLS industry output-price indexes via FRED, all monthly **NSA**.
Their coverage is not AI-only, and inflation cannot distinguish AI demand,
input costs, margins or sales volumes. No custom weights or weighted proxy
from the other project are imported. The five have no stated weight in the
headline final-demand basket here. They remain separate, with their own
dates, links and availability.

Their economic role is a selling-price observation for the producing industry;
for downstream buyers it can be a cost-pressure clue, not an observed input-cost
or profit-margin series. US domestic production does not mean AI-only output,
global GPU/HBM pricing, or the prices of all equipment purchased by US buyers.

## Producer inflation momentum

The release is followed by four overlapping final-demand groups, each configured
with its own **seasonally adjusted index level**, not an NSA industry proxy:

| Group / official code | FRED series |
|---|---|
| Ex food, energy and trade / FD 49116 | WPSFD49116 |
| Goods ex food and energy / FD 413 | WPSFD413 |
| Services ex trade, transportation and warehousing / FD 421 | PPITWS |
| Transportation and warehousing / FD 422 | PPIAWS |

The official release's rounded MoM is shown beside 3M and 6M index-implied rates.
For n months, annualized percent = `100 * ((I[t] / I[t-n]) ** (12/n) - 1)`.
Every calendar-month index level must be present, finite and positive. No rounded
MoM summation, endpoint interpolation or NSA annualization is used. Series are
clipped at the release reference month. A delayed series leaves that month's
rates null, names its actual latest month, and shows older rates separately.
Current-vintage index-implied MoM can differ from the release's rounded rate.
The category selector and date-range switch affect only the momentum chart;
the table always describes the latest release month. The chart compares 3M and
6M annualized rates on one unit basis, not unannualized MoM against annualized
rates. Missing points remain gaps. No aggregate score, threshold, PPI policy
target, inflation diffusion or causal transmission result is inferred.

## Observed release versions and revisions

See [the shared observed-release contract](inflation_releases.md). The folded
version table shows observations for this release month, not an unverified
first-print reconstruction. Its consensus observations remain retrospective.

Charts compare YoY or MoM changes, not raw index levels with different base
years. Changes require an exact calendar month/year comparator. Histories
are reindexed monthly; missing months remain null and lines do not connect
through them. A slow FRED update stays pending for the release month, with
its last actual month named; neither future points nor stale observations
are borrowed into the current month. An all-missing series leaves a named
gap. NSA MoM changes and their prior-only ten-year percentiles may reflect
seasonality; they are not seasonally neutral anomaly signals. At least 60
earlier monthly changes are required for a percentile.

History and heatmap controls have local scope. The heatmap offers 6M/1Y/2Y
and YoY/MoM/MoM-percentile; color saturation is ±10% YoY, ±1% MoM, or a
50-centered percentile. The trend offers independent date ranges and YoY/MoM.
Both use current-vintage history, subject to revisions and methodology changes.

## Refresh and failure behavior

The existing macro build writes `ppi` alongside `cpi`. BLS, consensus and
FRED errors are optional source notices, not a reason to publish invented
values or block the rest of the dashboard. This is refreshed by normal
dashboard builds, **not** a release-window live service. No new schedule or
deployment is created. `scripts/preview_ppi.py` builds PPI only into the local
macro artifact, preserving CPI, prices, PCE, session dates and the manifest;
`make site` assembles the preview. It refuses a concurrent macro artifact edit.

Primary references: [BLS PPI release](https://www.bls.gov/news.release/ppi.nr0.htm),
[BLS table 1](https://www.bls.gov/news.release/ppi.t01.htm),
[BLS PPI methods](https://www.bls.gov/opub/hom/ppi/), and the individual FRED
series links carried with each observation set.
