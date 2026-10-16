# CPI release analysis (no forecast model)

RISK → RATES & MACRO opens on **Treasury rates** (the curve and MOVE), then
**CPI & macro** and **PPI · AI prices**. CPI, PCE and commodities keep their own reference dates. A
local CPI-only preview does not make the other artifacts current.
`PYTHONPATH=src .venv/bin/python scripts/preview_cpi.py`, then
`make site PYTHON=.venv/bin/python`, refreshes only CPI for that preview. The
normal `macro` builder includes it automatically on full refreshes.

## What this version includes

- Headline/core, MoM **SA** and YoY **NSA**, directly from a dated official BLS
  release. Reference month, Eastern publication time, read time, source URL and
  text SHA-256 are retained. These are dated release tables, not a claim that
  a first-print/vintage ledger has been reconstructed.
- TradingView calendar consensus joined on US country, release date, exact
  metric and `referenceDate` month. Ambiguous duplicates and missing forecasts
  stay null. The original survey provider and pre-release capture timestamp
  are not established: the page explicitly labels the forecast retrospective.
  Previous is the calendar's possibly revised prior value, not a first print.
- Official Table 6 relative importance, its reference month, SA monthly
  changes, effects on all-items CPI and sampling standard errors. Table 1
  supplies NSA YoY. Food/energy/core form the non-overlapping waterfall;
  the bridge bar is **Aggregation** (the unrounded headline from the index
  less their signed official effects) or, when the index month is missing,
  **Rounding** (the published rounded headline less the effects); neither is
  an additional economic category. The component detail includes
  overlapping parents and children and must not be summed.
- Component MoM heatmap (6/12/24 calendar months), raw change or prior-only
  percentile. A permanent **WEIGHT** column shows each row's official relative
  importance as an exact percentage and a blue bar on a shared 0–100% scale.
  Those are the latest release's weights (reference month stated), not
  historical weights for every month in the heatmap, and not risk colors.
  The same encoding is in the detail table; contribution tooltips include
  weights too. Current-vintage FRED indexes imply unrounded monthly changes;
  those can differ from the release's rounded figures. A common zero-centered
  raw scale saturates at ±1%; percentile colors center at 50. Percentiles and
  10–90% historical reference bands use up to ten earlier years and require
  60 prior valid monthly changes. They are not survey errors, future event
  probabilities, BLS confidence intervals or policy acceptance thresholds.
- Core 3/6-month compounded annualized rates, Atlanta sticky/core sticky YoY,
  Cleveland median and 16%-trimmed-mean 1M annualized CPI. Different bases are
  separate chart groups. All calendar months in an annualized window must be
  present, including both endpoints. Charts retain null months rather than
  joining across them. A secondary publisher behind the BLS reference month
  shows **pending**, with any older reading separately dated.

## Sources and implementation

Series IDs and category mappings live in `[macro.cpi]` of
`config/dashboard.toml`. `sources/cpi.py` discovers publication time from
[BLS](https://www.bls.gov/news.release/cpi.nr0.htm) on every build, and reads the
dated archive's Table 1 and Table 6 together. All network requests use the
project HTTP adapter. The dated body is cached; this does not independently
establish that an archived publisher page was never corrected.

Table IDs, column counts, header meanings, matching table months, prior-month
weights, mandatory actuals and archive publication dates are checked. BLS
footnotes and section headings are not category names. A refusal or parser
failure leaves a named CPI gap; existing PCE/commodities remain readable.
Optional CPI source failures are notices rather than a reason to block closes.

Calendar consensus reuses `sources/expectations.py` and its exact metric
catalog. Core CPI MoM's missing TradingView title mapping is now supplied.
The existing CPI calendar's YoY print series are corrected from SA indexes to
NSA `CPIAUCNS`/`CPILFENS`; no stored historical release actuals are rewritten.

FRED histories are current vintage and subject to annual SA revisions.
Fed-derived histories can contain their publishers' imputed 2025 shutdown
observations. They are not observed first-print backtest targets. The Fed's
2% objective is measured with PCE, not CPI; no CPI target line is drawn.

## Explicitly not included

Observed BLS/calendar versions and prior-month revision comparisons are now
retained by [the shared release ledger](inflation_releases.md). First observed
does not mean first published. The ledger does not reconstruct old vintages or
turn retrospective consensus into a pre-release record.

No research forecast model, Cleveland nowcast, component consensus, inferred
"priced-in percentage", weighted inflation-breadth score, causal energy-to-
services transmission result or minute-resolution market reaction is added.

Updates occur with the existing dashboard build. There is no release-window
collector, extra schedule, second-by-second polling, new Worker or deployment
in this change. The fast-path/revision-lock design remains a separate stage.

## Verification

`tests/test_cpi.py` checks schemas, footnotes, date/month and SA/NSA identity,
strict forecast joins, prior-only bands, missing months and named failures.
`tests/js/cpi.test.mjs` covers surprise labels, null/zero colors and signed
attribution. Rendered checks exercise both research panes, the heatmap modes
and periods, all three persistence groups, history ranges, component details,
keyboard navigation, a narrow viewport, pending publishers and BLS failure.
