# Macro / CPI upgrade proposal

Status: design only, researched 2026-10-14. No CPI ingestion, scheduling,
infrastructure or deployment has been changed by this proposal.

## Goal and opening view

Answer four questions, in order: what surprised expectations, what contributed
to inflation, whether underlying pressure is broadening/persisting, and how
markets repriced. Keep commodities and the existing PCE table below the CPI
opening view, with detailed history folded rather than more top-level tabs.

1. **Release / surprise:** headline and core, each MoM SA and YoY NSA, actual,
   pre-release forecast, previous first print, revised previous print, and
   actual-minus-forecast in percentage points. Show reference month separately
   from publication time and fetch time. Forecasts from different providers
   remain separate; no invented average or survey range.
2. **Drivers:** signed contribution waterfall and an expandable component table
   with weight, weight reference month, MoM, official effect on all-items CPI
   (pp), expected change where available, forecast type, surprise contribution
   where defensible, and trailing historical percentile. Expand parents into
   children without adding both in a total. Keep a rounding/reconciliation
   note; do not force rounded effects to equal the rounded headline.
3. **Persistence:** core CPI 3/6-month annualized rates, official sticky/core
   sticky CPI, median/trimmed-mean CPI, shelter, and precisely defined core
   services excluding shelter. Use weighted component breadth only after
   coverage is audited, displaying observed basket weight and missing weight.
4. **Expectations / repricing:** separate calendar consensus, Cleveland model
   nowcast, and available event-market implied distribution. Event reaction
   uses comparable, time-stamped pre/post quotes; stale Yahoo futures or daily
   Treasury observations are not minute-resolution release reactions.

Use a simple release comparison, waterfall, then a component-by-month heatmap
and persistence line chart. Each component's heatmap can toggle raw MoM,
effect (pp), or prior-only historical percentile. Distinguish these color
scales rather than presenting them as a common inflation risk score.

## Existing building blocks and gaps

- `panels/macro.py` currently builds commodities and FRED PCE/income/spending
  history, with explicit current-vintage limitations; it has no BLS component
  weights/effects or release-time CPI snapshot.
- `sources/expectations.py` and `compute/expectations.py` already match calendar
  forecasts, Cleveland nowcasts and event-market contracts to releases. Reuse
  their source-specific matching, not a new unrelated expectations system.
- `snapshots/expectations.py` already archives raw futures/event-market quotes
  with fetch and quote times. It does not itself freeze calendar consensus or
  official first-release CPI values. Audit cadence and quote freshness before
  using it for release-window reactions.
- Calendar CPI YoY print configuration currently points to SA `CPIAUCSL` and
  `CPILFESL`. Official headline/core YoY comparisons should instead match the
  BLS NSA definitions. Correct this as part of implementation and test SA/NSA
  joins; do not silently rewrite recorded event actuals.
- The current macro chart's “Fed 2%” reference applies to PCE, not a CPI target.
  Do not reuse that label for new CPI charts.

## What “priced in” can and cannot mean

Known higher crude prices do not establish the market's forecast of the retail
gasoline CPI component. Crude, retail gasoline and gasoline CPI have different
measurement/averaging/seasonal-adjustment conventions. A component nowcast is
explicitly a model, not a surveyed market expectation.

Hypothetical example (not observed data): gasoline has a 4% basket weight,
expected component MoM is 7%, actual component MoM is 9%. The component miss is
**2 percentage points**, and its approximate extra headline effect is
`0.04 * (9 - 7) = 0.08 pp`, not 2 pp of headline CPI. This approximation is
not a replacement for official BLS effects. If the 7% is our model estimate,
label the error “vs model,” not “market surprise.”

Free broad CPI consensus is feasible through the existing feeds subject to
availability; comprehensive component-level consensus is not established.
Unavailable component expectations and surprise contributions stay null.
Event-market prices also have liquidity, spread and contract-definition
limitations; they are not interchangeable with an economist survey.

## Ordinary fluctuation versus persistent pressure

Keep three dimensions separate:

- **Unusual:** a component's change or model forecast error relative to its
  own prior observations. Start with prior-only empirical 80%/95% bands and
  percentiles, requiring adequate history and allowing structural-break and
  seasonal-adjustment caveats. These are reference bands, not guaranteed
  probabilities or policy acceptance thresholds.
- **Important:** signed effect on aggregate inflation, with the basket weight
  visible. A large volatile move in a tiny category need not dominate CPI.
- **Persistent:** several releases of higher short-run core rates, broader
  sticky/service pressure and median inflation. Sticky classification is based
  on price adjustment frequency; it does not prove an energy shock caused
  subsequent service inflation.

BLS sampling standard errors measure a different uncertainty than historical
volatility or forecast uncertainty. Show them in methodology/details, not as
the market surprise denominator. Any transmission indicator remains
“consistent with broadening” rather than a causal claim. A later transmission
study would require pre-specified lags, controls and out-of-sample testing.

## Publication-day fast path (proposed, not configured)

Use the official release calendar and America/New_York time zone; do not hard
code a UTC hour. Before release, archive available expectations with provider,
reference month, basis, source timestamp where supplied, and fetch timestamp.
Only a value demonstrably captured before publication qualifies as a frozen
forecast. A forecast recovered later is flagged retrospective, not PIT.

During the release window, a small collector reads official BLS release HTML
and Table 6 through `sources/http.py`, validates month/basis/schema and stores
raw first-seen payloads with checksums. Publish the first valid headline/core
snapshot separately from later component/derived updates. A candidate target
is tens of seconds to roughly a minute after the source becomes accessible;
measure latency first, with bounded polling/backoff and no subsecond SLA.

Serve a small versioned JSON through the existing Cloudflare backend/storage;
the frontend can poll every 20–30 seconds during the release window, stop
afterwards and show last successful fetch/source status. Do not depend on a
full GitHub Actions build or pretend a cached prior month is a new release.
Any Worker adaptation must keep network fetching in the approved common
fetch abstraction rather than adding an ad-hoc scraper.

Component details, Atlanta sticky CPI and Cleveland median CPI are independent
stages with their own publication/reference dates. Atlanta says its sticky
series is published by 11:00 ET on CPI release day; until the matching month
arrives, show “pending” alongside clearly dated prior-month history.

Archive first prints immutably and later revisions as separate versions. The
nightly full build consumes the latest validated snapshot without regressing
the live artifact. Publication needs atomic version selection and a single
writer/monotonic release revision gate to prevent stale build overwrites.

## Sources and historical feasibility

- [BLS Table 6](https://www.bls.gov/news.release/cpi.t06.htm) provides component
  relative importance, changes, effects and standard errors. Prefer official
  [effects](https://www.bls.gov/cpi/factsheets/contributions-effects.htm) over
  approximate weight-times-change attribution.
- [BLS aspect metadata](https://www.bls.gov/cpi/factsheets/using-cpi-metadata-aspect-files.htm)
  documents relative importance and effects beginning March 2012 for eligible
  series. Audit actual coverage/footnotes before promising complete history;
  do not infer that all metadata or effect series are unrevised first vintages.
- [BLS seasonal adjustment](https://www.bls.gov/cpi/seasonal-adjustment/) explains
  annual revisions to the previous five years of SA indexes. Current history
  alone is insufficient for first-print surprise backtests.
- [Atlanta sticky CPI](https://www.atlantafed.org/research-and-data/data/sticky-price-cpi)
  supplies the official classification and stated publication timing.
- [Cleveland median CPI](https://www.clevelandfed.org/indicators-and-data/median-cpi)
  and [daily nowcasts](https://www.clevelandfed.org/our-research/indicators-and-data/inflation-nowcasting)
  are separate statistical measures and models. October 2025 interpolation/
  substitution notices must be carried through into historical quality flags.
- [Federal Reserve target definition](https://www.federalreserve.gov/faqs/economy_14419.htm)
  specifies 2% inflation measured using PCE, not CPI.

## Suggested implementation sequence and acceptance

1. BLS ingestion, correct SA/NSA basis, contribution waterfall and first-print
   archive; reuse the existing calendar forecasts but expose their provenance.
2. Freeze pre-release forecasts, validate fast-path latency/failure/revision
   behavior, then deploy the release-window collector with appropriate access.
3. Sticky/median/breadth and component model nowcasts, after coverage and
   prior-only forecast error calibration are audited.

Tests must cover old-month HTTP 200 pages, table schema changes, missing
forecasts, forecasts captured too late, mismatched SA/NSA/reference months,
double-counted parents, signed effects and rounding, revisions, DST release
time, stale market quotes, imputed historical months, and stale nightly builds.
Mock release failures should leave the previous valid snapshot with explicit
staleness rather than inventing a value or reporting successful publication.
