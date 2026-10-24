# Valuation comparison: evidence, not a fair multiple

The branch trial adds the same A/B component to SCREENER (`#valuation`) and a
company's VALUATION pane, folded: open on SCREENER only when the route names a
ticker, and below the company's own valuation on its page. It reads existing `valuation.json` rows only, with the
artifact's price date. No fetch, forecast, artifact mutation or schedule is added.
The universe and Financials label come from the published configuration contract.

## Definitions and controls

- Select two covered tickers; COMPARE / Enter, SWAP and SUGGEST PEER redraw.
  Blank or unknown names clear results, never silently substitute another name.
- The label is VALUATION MEASURE: NTM consensus P/E is the default; operating /
  adjusted TTM P/E, reported TTM P/E, P/B and P/TBV are alternatives. They never
  blend. Only finite positive multiples compare; unavailable is an em dash.
  Each selected measure explains its denominator directly below the headline.
- Adjusted TTM P/E reads the existing `pe_operating` field, without recalculation
  or fallback to reported P/E. `pe_basis=operating` uses the dashboard's operating
  earnings adjustment; `ex_gains` removes equity-security gains/losses after tax
  (including for banks). These are not Price / EBIT, analyst NTM earnings, or
  interchangeable adjustments. Missing or unequal basis labels withhold
  directional evidence even if descriptive numeric multiples remain available.
- Displayed premium = `(A multiple / B multiple − 1) × 100`. The inverse is not
  its negative; swapping recomputes it. This is descriptive, not justified value.
- Suggestions prefer the same GICS sub-industry and then nearest market cap
  within sector, excluding the same issuer (CIK). No cross-sector fallback.
  Classification and size do not establish a business-model match.

## Evidence readings

Labels describe one measured difference **for the higher-multiple issuer**:
SUPPORTING FACT / COUNTERPOINT / SIMILAR, never the size of a justified premium.
There is no aggregate score or return prediction. Changes invisible at the
displayed precision do not receive a directional label.

Directional labels require distinct issuers, matching nonempty sector and
sub-industry labels, known statement/filing dates no later than the price date,
and available primary multiples. Known dates are displayed, not certified as
point-in-time history or as business comparability.

- Period alignment: statement period ends (and forecast fiscal year-ends) within
  45 days count as the same window, because 52/53-week fiscal calendars rarely
  share a day (HD 2026-08-02, LOW 2026-07-31). The gap is stated on the row;
  beyond 45 days the row withholds direction.
- Growth uses only the dated **+1y** revenue consensus growth. Fiscal year-ends
  must align and observation dates must not postdate prices. No current-FY
  substitution or inference of long-term persistence.
- Price-implied growth over consensus: the reverse-DCF growth at today's margin
  and the shared assumptions (`implied_growth`) less the +1y revenue consensus
  (`consensus_growth`), in percentage points, both already in `valuation.json`.
  A smaller excess supports the higher multiple. Both figures are on the row.
- Capital return uses reported TTM ROIC for nonfinancial firms, ROE for financial
  P/E or P/B, and ROTCE for financial P/TBV. TTM period ends must match and known
  carried return lines withhold direction. Accounting returns are not incremental
  future returns or proof of a moat.
- Cash conversion = `fcf_yield / earnings_yield × 100`, because both share market
  cap: `(OCF − cash CapEx) / reported net income`. Requires positive net income;
  cash can be zero or negative. Context only, with aligned TTM endpoints. Working
  capital and SBC can distort this measure; it is not FCFE / distributable cash.
- Operating-margin volatility is reported annual standard deviation, context
  only: history coverage may differ. It is not future uncertainty.
- Leverage uses net debt / EBITDA; lower is one supporting risk dimension.
  Requires aligned TTM endpoints and a known debt basis. Unknown debt is not zero.
- P/B and P/TBV directional comparisons are withheld outside Financials.
  Financial asset-quality/capital-buffer inputs remain explicitly unavailable;
  even identical GICS groups can contain different financial business models.

## Intangibles and anchoring

No goodwill / brand value is invented, and no blanket capitalization of R&D or
marketing expense is performed. The audit explains that acquired goodwill,
unrecorded internal intangibles, buybacks and leverage affect accounting returns
and book multiples. Quantifying comparable intangible capital is future work.

Historical P/E lives beneath business history in a collapsed context fold. Its
canvas initializes when opened, not at zero hidden width. Historical percentiles
are descriptive, not a valuation target; valuation-tail ranks use blue/amber
instead of cheap=green. Existing quality-rank colors keep their separate meaning.
The anchoring check asks whether prior multiples are still relevant if growth,
competition or capital needs changed. Reverse DCF links inspect conditional
operating requirements without converting this table into a price target.
