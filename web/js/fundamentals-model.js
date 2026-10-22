// The numbers behind FUNDAMENTAL TRENDS (tabs/financials.js), kept pure so
// node tests can check them. Money is in $B; margins, growth and returns stay
// in percent points, as the artifact stores them. A figure the artifact lacks
// is null, never zero.

const BILLION = 1e9;
const ONE_OFF_GAP_POINTS = 10;
export const MODES = ['annual', 'quarterly', 'ttm'];

const finite = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const at = (list, i) => finite(list?.[i]);
const billions = (value) => (value === null ? null : value / BILLION);

export function hasQuarters(company) {
  return Array.isArray(company?.quarters?.columns) && company.quarters.columns.length > 0;
}

// The default view: quarters when the artifact has them, else fiscal years.
export function defaultMode(company) {
  return hasQuarters(company) ? 'quarterly' : 'annual';
}

const annualLabel = (column) => `FY${String(column.fiscal_year).slice(-2)}`;
const quarterLabel = (column) => `${column.fiscal_year}Q${column.quarter}`;

// Sum of one flow over a window of quarters; null when any quarter lacks it.
function windowSum(values, key, from, to) {
  let total = 0;
  for (let j = from; j <= to; j += 1) {
    const value = at(values[key], j);
    if (value === null) return null;
    total += value;
  }
  return total;
}

// Quarters folded into rolling four-quarter periods. Flows are sums, margins
// are recomputed from those sums, balance items are the quarter's own. The
// series starts at the first quarter with four behind it.
function ttmPeriods(quarters) {
  const n = quarters.columns.length;
  const values = quarters.values || {};
  const ratios = quarters.ratios || {};
  const flowKeys = ['revenue', 'gross_profit', 'ebit', 'net_income', 'eps_diluted', 'operating_cash_flow', 'capex'];
  const sums = {};
  flowKeys.forEach((key) => {
    sums[key] = quarters.columns.map((_, i) => (i >= 3 ? windowSum(values, key, i - 3, i) : null));
  });
  const fcf = sums.operating_cash_flow.map((ocf, i) => (ocf === null || sums.capex[i] === null ? null : ocf - sums.capex[i]));
  const margin = (part) => sums.revenue.map((rev, i) => (part[i] === null || !rev ? null : (part[i] / rev) * 100));
  const growth = sums.revenue.map((rev, i) => {
    const prior = i >= 4 ? sums.revenue[i - 4] : null;
    return rev === null || !prior ? null : (rev / prior - 1) * 100;
  });
  const quarterKeys = Object.keys(quarters.derived || {});
  const labels = [];
  const out = { labels, values: {}, ratios: {}, derived: [] };
  for (let i = 3; i < n; i += 1) {
    labels.push(quarterLabel(quarters.columns[i]));
    out.derived.push(Array.from({ length: 4 }, (_, k) => i - k).some((j) => quarterKeys.some((key) => quarters.derived[key]?.[j] === true)));
  }
  const keep = (list) => list.slice(3);
  out.values = {
    revenue: keep(sums.revenue),
    net_income: keep(sums.net_income),
    eps_diluted: keep(sums.eps_diluted),
    operating_cash_flow: keep(sums.operating_cash_flow),
    capex: keep(sums.capex),
    gross_profit: keep(sums.gross_profit),
    cash: keep(quarters.values?.cash || []),
    short_term_investments: keep(quarters.values?.short_term_investments || []),
    total_debt: keep(quarters.values?.total_debt || []),
    debt_current: keep(quarters.values?.debt_current || []),
  };
  out.ratios = {
    revenue_growth: keep(growth),
    gross_margin: keep(margin(sums.gross_profit)),
    operating_margin: keep(margin(sums.ebit)),
    net_margin: keep(margin(sums.net_income)),
    free_cash_flow: keep(fcf),
    fcf_margin: keep(margin(fcf)),
    roe: keep(ratios.roe || []),
    roic: keep(ratios.roic || []),
    net_debt: keep(ratios.net_debt || []),
  };
  return out;
}

// The periods a mode plots, with the values and ratios each carries.
function periodsFor(company, mode) {
  if (mode === 'annual') {
    const columns = company.columns || [];
    return {
      labels: columns.map(annualLabel),
      values: company.values || {},
      ratios: company.ratios || {},
      derived: columns.map(() => false),
    };
  }
  if (!hasQuarters(company)) return { labels: [], values: {}, ratios: {}, derived: [] };
  const quarters = company.quarters;
  if (mode === 'quarterly') {
    const derivedMap = quarters.derived || {};
    return {
      labels: quarters.columns.map(quarterLabel),
      values: quarters.values || {},
      ratios: quarters.ratios || {},
      derived: quarters.columns.map((_, i) => Object.keys(derivedMap).some((key) => derivedMap[key]?.[i] === true)),
    };
  }
  return ttmPeriods(quarters);
}

// One company's series in a mode: { mode, labels, revenue, growth, gross, operating, net, netIncome,
// eps, fcf, fcfMargin, roe, roic, cash, debt, netDebt, derived, oneOff }. Arrays
// run in period order, one entry per label. `derived[i]`: a figure of that
// period was not filed as a three-month number. `oneOff[i]`: net and operating
// margins are more than ten points apart.
export function seriesFor(company, mode = 'annual') {
  if (!MODES.includes(mode)) throw new Error(`unknown fundamentals mode: ${mode}`);
  const { labels, values, ratios, derived } = periodsFor(company || {}, mode);
  const net = labels.map((_, i) => at(ratios.net_margin, i));
  const operating = labels.map((_, i) => at(ratios.operating_margin, i));
  const pick = (list) => labels.map((_, i) => at(list, i));
  const withOptional = (base, extra) => (base === null ? null : base + (extra ?? 0));
  const cash = labels.map((_, i) => {
    const value = at(values.cash, i);
    return value === null ? null : billions(withOptional(value, at(values.short_term_investments, i)));
  });
  const debt = labels.map((_, i) => {
    const total = at(values.total_debt, i);
    return total === null ? null : billions(withOptional(total, at(values.debt_current, i)));
  });
  return {
    mode,
    labels,
    revenue: labels.map((_, i) => billions(at(values.revenue, i))),
    growth: pick(ratios.revenue_growth),
    gross: pick(ratios.gross_margin),
    operating,
    net,
    netIncome: labels.map((_, i) => billions(at(values.net_income, i))),
    eps: pick(values.eps_diluted),
    fcf: labels.map((_, i) => billions(at(ratios.free_cash_flow, i))),
    fcfMargin: pick(ratios.fcf_margin),
    roe: pick(ratios.roe),
    roic: pick(ratios.roic),
    cash,
    debt,
    // The line is the bars' difference, so the chart reconciles with itself.
    netDebt: labels.map((_, i) => (debt[i] === null || cash[i] === null ? null : debt[i] - cash[i])),
    derived,
    oneOff: labels.map((_, i) => net[i] !== null && operating[i] !== null
      && Math.abs(net[i] - operating[i]) > ONE_OFF_GAP_POINTS),
  };
}

// Tooltip notes for each period, in order: derived figures and one-off margins.
export function pointNotes(series) {
  return series.labels.map((label, i) => {
    const notes = [];
    if (series.derived[i]) {
      if (series.mode === 'ttm') notes.push('derived: includes a derived quarter');
      else notes.push(label.endsWith('Q4') ? 'derived: year less nine months' : 'derived: year-to-date less prior');
    }
    if (series.oneOff[i]) notes.push('net income includes large non-operating or tax items');
    return notes;
  });
}
