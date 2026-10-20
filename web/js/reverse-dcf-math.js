// Conditional enterprise-cash-flow scenarios. All rates are decimal fractions.
// No analyst consensus, cash-tax calibration, segment FCF or share targets.
export const finite = (v) => typeof v === 'number' && Number.isFinite(v);
export const parseInput = (text) => (text === null || text === undefined || typeof text === 'boolean' || String(text).trim() === '') ? null : (Number.isFinite(Number(text)) ? Number(text) : null);

export function prepareReverseInputs(row, annual, asOf, settings) {
  const issues = [];
  const warnings = [];
  if (!settings) return { issues: ['Reverse DCF settings are not in this build.'], warnings };
  if (!row) return { issues: ['This ticker has no valuation record in this build.'], warnings };
  if (settings.excluded_sectors.includes(row.sector) || settings.excluded_subindustries.includes(row.sub_sector)) {
    issues.push(`${row.sector} / ${row.sub_sector}: this business needs a specialised model; the operating template is disabled.`);
  }
  if (!row.sector || !row.sub_sector) issues.push('Business classification is missing; no template is selected.');
  if (!annual || annual.ticker !== row.ticker || !annual.columns?.length) {
    return { issues: [...issues, 'Matching annual statements are missing.'], warnings };
  }
  const index = annual.columns.length - 1;
  const column = annual.columns[index];
  const value = (key) => annual.values?.[key]?.[index];
  const revenue = value('revenue');
  const ebit = value('ebit');
  if (Object.values(annual.values || {}).some((values) => values.length !== annual.columns.length)) issues.push('Annual statement columns are misaligned.');
  const ends = annual.columns.map((c) => c.period_end);
  if (ends.some((d, i) => !d || (i > 0 && d <= ends[i - 1]))) issues.push('Annual statement periods are not unique and ordered.');
  const observed = Date.parse(`${asOf}T00:00:00Z`);
  const end = Date.parse(`${column.period_end}T00:00:00Z`);
  const age = (observed - end) / 86400000;
  if (!finite(age) || age < 0 || age > settings.annual_max_age_days) issues.push('Annual revenue is outside the permitted dated-input window.');
  const balanceEnd = Date.parse(`${row.period_end}T00:00:00Z`);
  if (!finite(balanceEnd) || balanceEnd > observed) issues.push('The valuation balance-period date is missing, invalid or later than the price date.');
  if (!finite(row.price) || row.price <= 0) issues.push('A positive observed stock price is required for a price-linked scenario.');
  if (!column.filed || column.filed > asOf || !row.filed || row.filed > asOf) issues.push('A required filing date is absent or later than the price date.');
  if (!finite(revenue) || revenue <= 0) issues.push('Positive reported annual revenue is missing.');
  if (!finite(ebit) || ebit <= 0 || (finite(revenue) && ebit > revenue)) issues.push('A positive, interpretable annual operating profit is required; missing EBIT is not replaced with net income.');
  if (finite(row.operating_margin) && row.operating_margin <= 0) issues.push('The valuation-period operating result is nonpositive; a funded profitability path is needed.');
  const margin = finite(ebit) && finite(revenue) && revenue > 0 ? ebit / revenue : null;
  const capexShare = finite(value('capex')) && revenue > 0 ? value('capex') / revenue : null;
  if (capexShare !== null && capexShare >= settings.capital_warning_share) warnings.push(`Cash capex was ${(capexShare * 100).toFixed(1)}% of annual revenue. The net-investment assumption below is NOT calibrated to that number or to leases.`);
  if (settings.cycle_warning_subindustries?.includes(row.sub_sector)) warnings.push('Manufacturing mix and cycle normalisation are not inferred from cash capex. Choose the sustainable margin and investment scenario explicitly.');
  warnings.push('The latest annual revenue is used as a run-rate proxy at the price date, not as NTM consensus. Model year 1 is the next hypothetical year, not a fiscal-year forecast.');
  warnings.push('Lease consistency, non-operating assets, minority/preferred claims and operating working capital are not independently reconciled. No standalone business-segment valuation is implied.');
  const debtKnown = row.debt_basis && row.debt_basis !== 'no debt tagged';
  const workingEv = debtKnown && finite(row.ev) && row.ev > 0 && finite(row.market_cap) && row.market_cap > 0 ? row.ev : null;
  return {
    issues, warnings, revenue, margin, capexShare, column,
    workingEv,
    evReason: workingEv === null ? 'Published EV is unavailable or its debt basis is unknown. Enter an independently reviewed EV to calculate; missing debt is not zero.' : null,
    netClaims: workingEv !== null ? row.ev - row.market_cap : null,
  };
}

export function scenarioError(s) {
  const keys = ['revenue', 'baseMargin', 'growth', 'margin', 'wacc', 'tax', 'netInvestment', 'terminalGrowth', 'terminalRoic', 'years', 'transitionYears'];
  if (keys.some((key) => !finite(s[key]))) return 'Complete every scenario input with a finite number.';
  if (s.revenue <= 0 || s.baseMargin <= 0 || s.baseMargin > 1) return 'Positive revenue and an interpretable starting operating margin are required.';
  if (s.growth <= -1 || s.growth > 1 || s.margin < 0 || s.margin > 1) return 'Growth must be greater than −100% and at most 100%; sustainable margin must be 0–100%.';
  if (s.wacc <= 0 || s.wacc > 0.5 || s.terminalGrowth < 0 || s.terminalGrowth >= s.wacc) return 'Use 0 < WACC ≤ 50% and 0 ≤ terminal growth < WACC.';
  if (s.terminalRoic <= s.terminalGrowth || s.terminalRoic > 1) return 'Terminal ROIC must exceed terminal growth and be at most 100%.';
  if (s.tax < 0 || s.tax >= 1 || s.netInvestment < 0 || s.netInvestment > 1) return 'Tax must be 0–<100%; net investment must be 0–100% of revenue.';
  if (!Number.isInteger(s.years) || s.years < 1 || s.years > 30 || !Number.isInteger(s.transitionYears) || s.transitionYears < 1 || s.transitionYears > s.years) return 'Use 1–30 whole forecast years and a margin transition within that horizon.';
  return null;
}

export function scenarioValue(s) {
  const error = scenarioError(s);
  if (error) return { error, ev: null };
  let revenue = s.revenue;
  let explicitPv = 0;
  const path = [];
  for (let year = 1; year <= s.years; year += 1) {
    revenue *= 1 + s.growth;
    const margin = s.baseMargin + (s.margin - s.baseMargin) * Math.min(1, year / s.transitionYears);
    const nopat = revenue * margin * (1 - s.tax);
    const reinvestment = revenue * s.netInvestment;
    const fcf = nopat - reinvestment;
    const pv = fcf / (1 + s.wacc) ** year;
    explicitPv += pv;
    path.push({ year, revenue, margin, nopat, reinvestment, fcf, pv });
  }
  const terminalRevenue = revenue * (1 + s.terminalGrowth);
  const terminalNopat = terminalRevenue * s.margin * (1 - s.tax);
  const terminalReinvestment = terminalNopat * s.terminalGrowth / s.terminalRoic;
  const terminalFcf = terminalNopat - terminalReinvestment;
  const terminalPv = terminalFcf / (s.wacc - s.terminalGrowth) / (1 + s.wacc) ** s.years;
  const ev = explicitPv + terminalPv;
  if (!finite(ev)) return { error: 'Scenario overflow; reduce the growth or horizon.', ev: null };
  return { error: null, ev, explicitPv, terminalPv, terminalFcf, terminalReinvestment, path };
}

export function requiredMargin(s, targetEv, bounds = [0, 1]) {
  if (!finite(targetEv) || targetEv <= 0 || !bounds.every(finite) || bounds[0] < 0 || bounds[1] > 1 || bounds[0] >= bounds[1]) return { status: 'invalid', value: null };
  const low = scenarioValue({ ...s, margin: bounds[0] });
  const high = scenarioValue({ ...s, margin: bounds[1] });
  if (low.error || high.error) return { status: 'invalid', value: null, error: low.error || high.error };
  if (targetEv < low.ev || targetEv > high.ev) return { status: 'outside-bounds', value: null };
  // With growth, reinvestment and discount fixed, EV is affine in target
  // margin (including the terminal growth/ROIC reinvestment rule).
  const value = bounds[0] + (targetEv - low.ev) / (high.ev - low.ev) * (bounds[1] - bounds[0]);
  if (!finite(value)) return { status: 'invalid', value: null };
  return { status: 'solved', value };
}

// The discount rate at which the scenario's model EV equals the working EV:
// the reverse question with growth and margin held. Model EV falls as the
// rate rises, so bisection between just above terminal growth and 50% finds
// it; a target outside that span is reported, never clamped.
export function impliedDiscountRate(s, targetEv, { tolerance = 1e-6 } = {}) {
  if (!finite(targetEv) || targetEv <= 0) return { status: 'invalid', value: null };
  let low = s.terminalGrowth + 0.0005;
  let high = 0.5;
  const at = (wacc) => scenarioValue({ ...s, wacc });
  const lowValue = at(low);
  const highValue = at(high);
  if (lowValue.error || highValue.error) return { status: 'invalid', value: null, error: lowValue.error || highValue.error };
  if (targetEv > lowValue.ev) return { status: 'below-range', value: null };
  if (targetEv < highValue.ev) return { status: 'above-range', value: null };
  for (let i = 0; i < 100 && high - low > tolerance; i += 1) {
    const mid = (low + high) / 2;
    if (at(mid).ev > targetEv) low = mid; else high = mid;
  }
  return { status: 'solved', value: (low + high) / 2 };
}
