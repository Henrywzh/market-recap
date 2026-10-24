# Reverse DCF: conditional operating scenarios

`#dcf/<ticker>` opens Reverse DCF; BUILD YOUR OWN preserves the existing manual
forward model. The reverse view uses VALUATION's full ticker list and FINANCIALS'
per-ticker annual statements, not the forward model's 120-name history subset.
It creates no additional network data source or scheduled job.

## Inputs and scope

`[dcf.reverse]` owns every opening scenario, axis and business exclusion.
`dcf.json` publishes those settings. Price/EV come from `valuation.json`; annual
revenue and EBIT come from `financials/<ticker>.json`, with their dates. The two
input artifact sessions must match. A consistently older pair is explicitly
labelled historical when the manifest is newer; no date is changed to make it
current. `dcf.json`'s old date is not a price observation in this mode: it supplies
configuration only. No full refresh is performed for a UI preview.

The base revenue is an annual run-rate proxy at the price date. Model year 1 is
the following hypothetical year, not a fiscal-year projection from the old
annual endpoint. No already elapsed fiscal-year cash flow is added to value.

Financials, REITs/Real Estate, Utilities and Biotechnology are outside this
first operating template. Missing/uninterpretable annual EBIT, operating losses,
future or stale annual periods, mismatched tickers and unknown classifications
block it. Missing EBIT is not replaced with net income. This is a narrow scope
gate, not certification of every other company's business model.

Working EV starts at the dashboard's published aggregate EV proxy only when
positive with a known debt basis and positive market cap. A missing debt tag
leaves EV blank. A user may enter a reviewed EV as an explicit assumption.
Cash, preferred/minority claims, non-operating investments, lease consistency
and the full enterprise-to-common-equity bridge are not independently rebuilt.
No per-share price target or equity-return percentage is produced.

## Model

All formulas use decimal rates internally, dollars for amounts, end-year
discounting and a 1–30-year explicit horizon.

- Revenue grows at the chosen constant rate during the explicit horizon.
- Operating margin transitions linearly from reported annual EBIT/revenue to
  the selected sustainable margin over the chosen transition years, then holds.
- NOPAT = revenue × operating margin × (1 − assumed operating tax).
- Explicit net reinvestment = revenue × assumed net reinvestment share.
- Explicit FCF = NOPAT − net reinvestment.
- Next-year terminal revenue = final explicit revenue × (1 + terminal growth).
- Terminal reinvestment = terminal NOPAT × terminal growth / terminal ROIC.
- Continuing value = terminal FCF / (WACC − terminal growth).

Net reinvestment includes net fixed/intangible investment plus operating working
capital investment. It is **not** gross cash CapEx, cash CapEx plus leases,
CFO minus CapEx, or the existing unreviewed current-assets/current-liabilities
NWC proxy. SBC stays expensed in operating profit; no addback is made.
Cash CapEx is shown as historical context and never calibrates the future rate.
Growth and investment can change abruptly at the terminal boundary; this is a
visible simplified scenario, not a forecast of that transition.

Require 0 < WACC ≤ 50%, 0 ≤ terminal growth < WACC, terminal ROIC > terminal
growth, 0 ≤ operating tax < 100%, and 0–100% sustainable operating margin.
The required margin is solved within the configured bounds (0–100% initially).
With the remaining assumptions fixed, EV is affine in the sustainable margin,
including terminal reinvestment. Outside-bounds roots are labelled, never
clamped to the nearest boundary. Empty/invalid inputs remove the outputs.

## Reading the page

The guided view answers three questions in order: what the company delivered
(the longest configured historical revenue CAGR and the recent reported
operating-margin median, with actual coverage), what the working price/EV
requires, and how sensitive the answer is (terminal dependence and an expandable
chart).

Section 02 leads with **required margin** at the chosen growth / WACC and the
**scenario operating margin** the user selected. The historical median is a
reference, not a target or a forecast. The conditional required-margin marker
retains its historical-range color; it is not a cheap/expensive signal.

Inside DETAILS & AUDIT:

- **Implied discount rate**: the rate at which model EV equals working EV, with
  growth, margin, tax, reinvestment and terminal assumptions held. It is solved
  by bisection between just above terminal growth and 50%. A target outside that
  span is named ("< x%" / "> 50%"), never clamped. It is shown against the build's
  10-year Treasury yield (`dcf.json` `risk_free_rate`). It is an enterprise-level
  rate, not an expected share return. Its difference from the Treasury yield is
  not an equity risk premium.

Under them, one bar puts three things on a 0-to-top margin scale:
- the company's reported operating-margin range;
- the industry peers' TTM margins (dots);
- the required margin (a marker, amber / blue / neutral as below).

The required-margin frontier is drawn on a growth axis fitted to the company: the
evidence box and the scenario, with 3 points below and 5 above. It is drawn at half
the configured growth step. The height fits the chosen-WACC curve over the box's
growth span, so a narrow margin range stays visible; other curves may leave the
top.

The shaded **reference ranges** span:
- growth: analysts' revenue growth low–high across both fiscal years. Without a
  range it uses their means, and without consensus the reported CAGRs, widened to
  at least 1 point;
- margin: the company's reported operating-margin range.

The axes combine different horizons: near-term FY consensus (or historical CAGR)
and historical margins. Crossing this box does not validate a jointly feasible
long-term outcome. It is not a probability region. A scenario above/below its WACC curve has model EV above/below working
EV; neither is an automatic share valuation verdict. Future economics must be
judged against credible expectations, not mechanically extrapolated from history.

The assumption editor is folded below the requirement summary, with key inputs
and default/edited status always visible. All fields and origin labels remain
available; missing EV opens the editor and its advanced section automatically.
Audit EV/gap statistics, source rows and paths are retained in folds. History
opens by default; the reader can collapse it. Historical and sensitivity charts
draw only when their own fold is open; toggling re-renders
without resetting edits, and closing disposes hidden charts. No formula, opening
assumption, source, date or new valuation judgement is introduced by the guided
layout.

FY revenue consensus is shown as one card per fiscal endpoint: mean growth,
analyst count, low–high band and a mean dot, with a zero-growth reference. All
cards share a growth-% scale for this company, so band widths are comparable.
No year-ago revenue marker is placed on a growth axis. Missing means omit the
dot; missing/inverted/vendor-flagged ranges or a mean outside the supplied range
omit the band. Equal endpoints and zero/negative means remain real observations.
The band describes analyst dispersion, not confidence, accuracy or probability.

The 2026-10-24 evidence UI trial does not alter any solver, formula, opening
scenario or input artifact. Growth fade, growth-linked reinvestment, competitive
durability and a reviewed EV-to-equity bridge remain separate model work, not
features this layout claims to deliver.

Each map cell is `scenario EV / working EV − 1`. It is **not stock-price upside**
and not a probability. A cell selection updates growth and margin controls.
The required margin, chosen EV, EV gap and cash-flow path recompute together.
The forecast fold reports terminal dependence, which may exceed 100% when
explicit-period FCF is negative. Negative forecast FCF is flagged; financing
and future dilution are not modelled. Reset restores the explicitly labelled
opening assumptions; it does not refresh data or obtain a consensus forecast.

## Evidence context and charts

Every editable field identifies its opening source:
- **Growth** opens on the company's own evidence:
  - analysts' revenue growth for the later fiscal year (ANALYST FY REVENUE GROWTH);
  - else the longest complete reported CAGR (COMPANY nY REVENUE CAGR);
  - only then the shared default.

  It is held flat for the horizon. That is a scenario anchored to the company,
  not a ten-year forecast.
- **Margin** opens on the company's last reported operating margin, as a
  starting seed.
- **EV** opens on the published, unreviewed EV proxy.
- **Every other field** opens on the shared configuration.

WACC deliberately stays on the shared default. A two-year weekly beta is too
noisy for one company; PG's is 0.22. The implied discount rate answers the WACC
question from the price instead. Changing a field labels it USER SCENARIO;
reset restores the original source labels. No company-specific WACC, sustainable
margin, future growth or net-reinvestment calibration is claimed.

The existing annual statement amounts supply dated historical revenue growth,
gross and EBIT margins and gross cash CapEx / revenue. Gross profit uses its
reported amount, or revenue less cost of revenue when both exist. Missing
amounts remain null. Growth requires adjacent roughly annual periods (330–400
days), not an interpolated missing year. Configured revenue CAGRs require a
complete sequence of annual revenues and use actual elapsed years; no ten-year
CAGR is invented from ten year-end observations. Recent margin / CapEx ranges
use the last configured number of available annual columns and report the
actual finite denominator. Periods and filings later than the input session
are excluded. The available filing vintage may include restatements; this is
historical context, not a point-in-time backtest or probability distribution.

The required-margin and difference figures use three visual states against the
selected company's recent reported operating-margin range: amber when the
required margin is above the range, blue when it is below, and neutral when it
is within the range or coverage is insufficient. Outside the range, the label
also gives the percentage-point distance to the nearest historical extreme.
The configured minimum is five finite annual observations. Color communicates
how demanding the price-implied
operating hurdle is relative to that company's history. It does not label the
shares expensive or cheap, estimate a future margin, or imply a probability.

The page adds two comparison sources beneath the required-margin chart:

- Yahoo `earningsTrend` revenue consensus for fiscal years `0y` and `+1y`, with
  fiscal year end, vendor-average revenue growth, vendor low/high growth, and
  analyst count. Growth uses Yahoo's own prior-year revenue denominator; that
  denominator may also be estimated. The low/high values describe analyst
  dispersion, not probability bounds. The cache observation timestamp is shown;
  it is a fetch time rather than Yahoo's estimate-revision time. The data is
  short-term context: only the later year's mean opens the growth field (labelled,
  editable), and the low–high range draws the evidence box. Nothing is fitted.
  Same-day intraday alignment with the closing price is not established. No
  adjusted-EPS growth is substituted for revenue or margin forecasts.
- Dated TTM operating margins for other issuers in the same GICS sector and
  sub-industry, drawn from the existing valuation artifact. The selected CIK
  and duplicate share classes are excluded; missing or future-dated filings,
  stale periods older than `peer_max_age_days`, and margins based on lagged
  revenue / EBIT inputs are omitted. Lagged unrelated fields such as buybacks
  do not remove an otherwise usable operating margin. Individual company
  figures stay visible. A median is shown only when at least `peer_min_count`
  issuers have usable observations. GICS is a broad classification, not a
  confirmation of equivalent business models, and these actual margins are
  not a forward margin consensus.

Forward operating-margin consensus and reviewed company guidance are not
available in this data set. Revenue expectations plus historical operating
margins can help frame candidate scenarios, while they cannot establish whether
the required margin is achievable. The page therefore keeps the model's growth
and margin assumptions editable and labels the overall output as conditional.

Three chart sections reuse the dashboard's existing ECharts renderer:

- Annual gross / operating margins or YoY revenue growth, with separate dashed
  scenario points. The historical series end at their dated fiscal endpoints;
  NOW is the price-date run-rate proxy, followed by hypothetical M1…Mn, not
  future fiscal-year dates. No future gross margin is fabricated.
- Growth versus required sustainable operating margin under configured WACC
  shifts. Invalid / out-of-bounds roots are gaps, never clamped. A diamond marks
  the selected scenario; a dotted historical-margin median is context only,
  not a paired long-horizon growth/margin expectation.
- Model EV versus WACC under configured net-investment shifts, with working EV
  as a dotted reference. Other parameters remain fixed. Invalid combinations
  are gaps, not zero. Terminal PV / total EV is always visible and may exceed
  100%; it is dependence, not probability. Growth and explicit reinvestment
  remain independent assumptions, not a validated growth-capital feasibility
  model.

Historical inputs / filing dates and all plotted curve / sensitivity numbers
are inspectable in adjacent folds. Blank scenario inputs remove conditional
plots while retaining observed history. Changes and ticker loads dispose old
charts, and stale queued chart draws are ignored. Sources, missing consensus
and the absence of business-model-matched peer calibration stay explicit.

## Local preview and checks

```sh
PYTHONPATH=src .venv/bin/python scripts/preview_reverse_dcf.py
make site PYTHON=.venv/bin/python
node --test tests/js/reverse-dcf-math.test.mjs tests/js/reverse-dcf-ui.test.mjs
node --test tests/js/reverse-dcf-context.test.mjs
```

The preview helper changes only local DCF configuration metadata, preserving
all input dates and the manifest. It does not fetch or deploy anything.

Tests independently check one-year discounted FCF and a zero-growth perpetuity,
root reconstruction, invalid boundaries, empty versus zero, object-shaped
financials metadata, actual UI input/cell/reset transitions, stale asynchronous
company loads and unsupported/missing data. Context tests cover estimate dates,
revenue-only growth, inconsistent ranges, historical-range color states and
peer deduplication / filing dates. They validate a conditional calculator,
not forecast performance or economic calibration.
