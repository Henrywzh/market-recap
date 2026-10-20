// Historical context and conditional chart rows. No fitted company forecasts.
import { finite, scenarioValue, requiredMargin } from './reverse-dcf-math.js';

const day = (value) => Date.parse(`${value}T00:00:00Z`);
const ratio = (a, b) => finite(a) && finite(b) && b > 0 ? a / b * 100 : null;

export function summarize(values) {
  const sorted = values.filter(finite).sort((a, b) => a - b);
  const n = sorted.length;
  return { n, min: n ? sorted[0] : null, max: n ? sorted[n - 1] : null,
    median: n ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2 : null };
}

export function marginReferenceState(required, stats, minimumYears) {
  if (!finite(required) || !stats.n) return { tone: 'neutral', label: 'REFERENCE UNAVAILABLE' };
  if (stats.n < minimumYears) return { tone: 'neutral', label: 'LIMITED HISTORY' };
  // Compare at displayed 0.1 pp precision; avoid a warning on a rounded tie.
  const shown = (v) => Math.round(v * 10);
  if (shown(required) > shown(stats.max)) return { tone: 'above', label: 'ABOVE OWN HISTORY' };
  if (shown(required) < shown(stats.min)) return { tone: 'below', label: 'BELOW OWN HISTORY' };
  return { tone: 'neutral', label: 'WITHIN OWN HISTORY' };
}

export function industryComparators(rows, company, asOf, minimumPeers, maximumAgeDays = 400) {
  const seen = new Set();
  let candidates = 0;
  const members = [];
  const asOfDay = day(asOf);
  const marginInputs = new Set(['revenue', 'ebit', 'pretax_income', 'interest_expense']);
  if (company.sector && company.sub_sector) for (const row of rows) {
    if (row.ticker === company.ticker || (company.cik && String(row.cik) === String(company.cik))
        || row.sector !== company.sector || row.sub_sector !== company.sub_sector) continue;
    const identity = row.cik ? `cik:${row.cik}` : `ticker:${row.ticker}`;
    if (seen.has(identity)) continue;
    seen.add(identity); candidates += 1;
    const laggedMarginInput = row.lagged === true
      || (Array.isArray(row.lagged) && row.lagged.some((key) => marginInputs.has(key)));
    const periodDay = day(row.period_end);
    const filedDay = day(row.filed);
    const ageDays = (asOfDay - periodDay) / 86400000;
    if (!finite(row.operating_margin) || laggedMarginInput || !finite(periodDay) || !finite(filedDay)
        || periodDay > asOfDay || filedDay > asOfDay || ageDays > maximumAgeDays) continue;
    members.push(row);
  }
  members.sort((a, b) => a.ticker.localeCompare(b.ticker));
  const stats = summarize(members.map((r) => r.operating_margin));
  return { members, candidates, usable: stats.n, median: stats.n >= minimumPeers ? stats.median : null,
    thin: stats.n < minimumPeers, minimum: minimumPeers, maximumAgeDays };
}

export function historicalContext(annual, asOf, cfg) {
  const values = annual.values || {};
  const at = (key, i) => finite(values[key]?.[i]) ? values[key][i] : null;
  const rows = (annual.columns || []).map((column, i) => {
    const revenue = at('revenue', i);
    const gross = at('gross_profit', i);
    const cost = at('cost_of_revenue', i);
    return { ...column, revenue, operatingMargin: ratio(at('ebit', i), revenue),
      grossMargin: ratio(gross !== null ? gross : revenue !== null && cost !== null ? revenue - cost : null, revenue),
      capexShare: ratio(at('capex', i), revenue), growth: null };
  }).filter((r) => finite(day(r.period_end)) && r.period_end <= asOf && r.filed && r.filed <= asOf);
  rows.forEach((r, i) => {
    const previous = rows[i - 1];
    const elapsed = previous ? (day(r.period_end) - day(previous.period_end)) / 86400000 : null;
    // Do not bridge a missing annual revenue, skipped year or stub period.
    if (elapsed >= 330 && elapsed <= 400 && finite(r.revenue) && finite(previous.revenue) && previous.revenue > 0) r.growth = (r.revenue / previous.revenue - 1) * 100;
  });
  const recent = rows.slice(-cfg.reference_years);
  const cagr = cfg.history_cagr_years.map((years) => {
    const end = rows[rows.length - 1];
    const start = rows[rows.length - 1 - years];
    const elapsed = start && end ? (day(end.period_end) - day(start.period_end)) / 86400000 / 365.25 : null;
    const complete = start && rows.slice(-years - 1).every((r, i) => i === 0 || r.growth !== null);
    const value = complete && Math.abs(elapsed - years) < 0.15 && start.revenue > 0 && end.revenue > 0
      ? ((end.revenue / start.revenue) ** (1 / elapsed) - 1) * 100 : null;
    return { years, value, start: start?.period_end || null, end: end?.period_end || null };
  });
  return { rows, recent, cagr, margin: summarize(recent.map((r) => r.operatingMargin)),
    gross: summarize(recent.map((r) => r.grossMargin)), capex: summarize(recent.map((r) => r.capexShare)) };
}

export function scenarioCharts(s, targetEv, cfg, window = null) {
  const bounds = cfg.margin_bounds_pct.map((v) => v / 100);
  const grid = cfg.growth_grid_pct;
  const [lo, hi] = window || [Math.min(...grid), Math.max(...grid)];
  const growths = [];
  // A company window is narrower, so it is drawn at half the step.
  const step = window ? cfg.chart_growth_step_pct / 2 : cfg.chart_growth_step_pct;
  if (finite(step) && step > 0) {
    for (let x = lo; x <= hi + 1e-8 && growths.length < 1001; x += step) growths.push(Number(x.toFixed(6)));
  }
  if (finite(s.growth) && !growths.includes(s.growth * 100)) growths.push(s.growth * 100);
  growths.sort((a, b) => a - b);
  const frontier = cfg.sensitivity_wacc_shifts_pp.map((shift) => {
    const wacc = s.wacc + shift / 100;
    return { shift, wacc, points: growths.map((growth) => {
      const result = requiredMargin({ ...s, growth: growth / 100, wacc }, targetEv, bounds);
      return [growth, result.status === 'solved' ? result.value * 100 : null];
    }) };
  });
  const sensitivity = cfg.sensitivity_investment_shifts_pp.flatMap((investmentShift) => cfg.sensitivity_wacc_shifts_pp.map((waccShift) => {
    const wacc = s.wacc + waccShift / 100;
    const netInvestment = s.netInvestment + investmentShift / 100;
    const value = scenarioValue({ ...s, wacc, netInvestment });
    return { wacc, netInvestment, ev: value.ev,
      gap: !value.error && finite(targetEv) && targetEv > 0 ? (value.ev / targetEv - 1) * 100 : null,
      terminalShare: !value.error && value.ev > 0 ? value.terminalPv / value.ev * 100 : null,
      error: value.error };
  }));
  return { frontier, sensitivity };
}

const round1 = (v) => Math.round(v * 10) / 10;

// Where the scenario opens on growth: the company's own expectations before a
// shared default. Analysts' later fiscal year first (it is past the current
// year's known quarters), then the nearer one, then the longest reported CAGR.
export function openingGrowth(consensus, history, fallback) {
  const periods = (consensus?.periods || []).filter((p) => finite(p.growth_pct));
  if (periods.length) {
    const p = periods.at(-1);
    return { value: round1(p.growth_pct), origin: 'ANALYST FY REVENUE GROWTH', source: 'consensus', note: `Yahoo consensus for the fiscal year ending ${p.end}` };
  }
  const cagr = [...(history?.cagr || [])].reverse().find((c) => finite(c.value));
  if (cagr) return { value: round1(cagr.value), origin: `COMPANY ${cagr.years}Y REVENUE CAGR`, source: 'history', note: `${cagr.start} → ${cagr.end}` };
  return { value: fallback, origin: 'SHARED ILLUSTRATIVE DEFAULT', source: 'default', note: null };
}

// The box of outcomes the company's own evidence spans: analysts' revenue
// growth low-high (else the reported CAGRs) across its reported operating
// margin range. Not a probability region; a place to look on the chart.
export function plausibleBox(consensus, history) {
  const lows = (consensus?.periods || []).map((p) => p.growth_low_pct).filter(finite);
  const highs = (consensus?.periods || []).map((p) => p.growth_high_pct).filter(finite);
  const means = (consensus?.periods || []).map((p) => p.growth_pct).filter(finite);
  let growth = null;
  let growthSource = null;
  if (lows.length && highs.length) { growth = [Math.min(...lows), Math.max(...highs)]; growthSource = 'analyst low–high'; }
  else if (means.length) { growth = [Math.min(...means), Math.max(...means)]; growthSource = 'analyst means'; }
  else {
    const cagrs = (history?.cagr || []).map((c) => c.value).filter(finite);
    if (cagrs.length) { growth = [Math.min(...cagrs), Math.max(...cagrs)]; growthSource = 'reported CAGRs'; }
  }
  if (growth && growth[1] - growth[0] < 1) growth = [growth[0] - 0.5, growth[1] + 0.5];
  const margin = history?.margin?.n ? [history.margin.min, history.margin.max] : null;
  return growth && margin ? { growth, margin, growthSource } : null;
}

// The chart's growth axis around this company rather than one fixed span for
// every name: the box and the scenario with room either side.
export function growthWindow(box, growthPct) {
  const xs = [growthPct, ...(box?.growth || [])].filter(finite);
  if (!xs.length) return null;
  const lo = Math.max(-20, Math.floor(Math.min(0, ...xs) - 3));
  const hi = Math.min(40, Math.ceil(Math.max(...xs) + 5));
  return [lo, hi];
}

// Upper end of the margin bar: the largest value shown plus headroom, in tens.
export function marginScale(values) {
  const top = Math.max(...values.filter(finite), 10);
  return Math.min(100, Math.max(30, Math.ceil((top * 1.15) / 10) * 10));
}
