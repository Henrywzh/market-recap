// FLOWS scorecard: one row per participant, built from the artifact sections
// the FLOWS tab already loads. Pure: no DOM and no fmt.js, so the tests run
// under node. Every number is read from the build or derived from its own
// history; a missing input drops the row rather than inventing a figure.

const MINUS = '−';
const DASH = '—';
const DAY_MS = 86400000;
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const orNull = (v) => (present(v) ? v : null);

// Stale when the source's as-of date lags the page by more than this many days.
export const STALE_DAYS = { daily: 3, weekly: 10, quarterly: 140 };
// Fastest first: the order rows are shown in, before the percentile spread.
export const FREQUENCY_ORDER = ['daily', 'weekly', 'calendar', 'quarterly'];
// A percentile needs enough history to mean something; fewer points give none.
export const MIN_HISTORY = 8;
// Buyback quarters with less issuer coverage than this are left out of the history.
export const MIN_BUYBACK_COVERAGE = 60;

// The Z.1 holder groups that appear as scorecard rows, with the participant's name.
const Z1_ROWS = [
  ['households', 'Households'],
  ['mutual_funds', 'Mutual funds'],
  ['pensions', 'Pensions'],
  ['rest_of_world', 'Foreign investors'],
];
// Every holder group, for the last-quarter bar chart (the total and issuer lines are not holders).
export const HOLDER_KEYS = ['households', 'mutual_funds', 'etfs', 'pensions', 'insurers', 'rest_of_world', 'broker_dealers', 'other'];

// "91,234.5": grouped thousands at a fixed number of decimals, sign handled by the caller.
function grouped(value, digits) {
  const [whole, frac] = Math.abs(value).toFixed(digits).split('.');
  const body = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return frac ? `${body}.${frac}` : body;
}

// Signed dollars in billions with a true minus: "+$350.5bn", "−$11.2bn". Under a billion, millions.
export function bnText(value) {
  if (!present(value)) return DASH;
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  const a = Math.abs(value);
  if (a > 0 && a < 1) return `${sign}$${grouped(a * 1000, 0)}m`;
  return `${sign}$${grouped(a, 1)}bn`;
}

// Signed percentage with a true minus: "−21.2%". The unit is appended by the caller.
export function signedPct(value, digits = 1) {
  if (!present(value)) return DASH;
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  return `${sign}${grouped(value, digits)}%`;
}

// An exposure level, unsigned: a share of assets is not a flow, so it carries no plus: "37.6%".
export function levelPctText(value, digits = 1) {
  return present(value) ? `${grouped(value, digits)}%` : DASH;
}

// Ordinal percentile: "7th", "21st", "12th".
export function ordinalText(value) {
  if (!present(value)) return DASH;
  const n = Math.round(value);
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th';
  return `${n}${suffix}`;
}

// Buy when the flow is positive, sell when negative. Null when there is no reading.
export function directionOf(value) {
  if (!present(value)) return null;
  if (value > 0) return 'buy';
  if (value < 0) return 'sell';
  return 'flat';
}

// Where the latest value sits in its own history, 0 to 100, ties counted half.
// Null below MIN_HISTORY points: a rank of three observations says little.
export function percentileOf(value, history) {
  if (!present(value)) return null;
  const xs = (history || []).filter(present);
  if (xs.length < MIN_HISTORY) return null;
  const below = xs.filter((x) => x < value).length;
  const equal = xs.filter((x) => x === value).length;
  return Math.round(((below + equal / 2) / xs.length) * 100);
}

// Whole days between the page date and a source's as-of date (page minus source). Dates are YYYY-MM-DD, read as UTC.
export function daysBetween(pageAsOf, asOf) {
  const a = Date.parse(pageAsOf);
  const b = Date.parse(asOf);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((a - b) / DAY_MS);
}

// Stale: the source is older than its frequency allows. Unknown frequencies are never stale.
export function isStale(frequency, lagDays) {
  if (!present(lagDays) || STALE_DAYS[frequency] === undefined) return false;
  return lagDays > STALE_DAYS[frequency];
}

// The last `n` readings, nulls kept so the sparkline keeps its gaps. Null when nothing is numeric.
export function recentValues(values, n = 12) {
  if (!Array.isArray(values)) return null;
  const xs = values.map((v) => orNull(v));
  if (!xs.some(present)) return null;
  return xs.slice(-n);
}

// Fastest frequency first, then the rows furthest from their own median (|pctile - 50|), largest first.
// A row with no percentile sorts after the rows that have one.
export function sortRows(rows) {
  const rank = (f) => FREQUENCY_ORDER.indexOf(f);
  const spread = (r) => (present(r.percentile) ? Math.abs(r.percentile - 50) : -1);
  return [...rows].sort((a, b) => (rank(a.frequency) - rank(b.frequency)) || (spread(b) - spread(a)));
}

// Shared row shape: stamps the lag against the page date and the stale flag.
function makeRow(fields, pageAsOf) {
  const lagDays = daysBetween(pageAsOf, fields.asOf);
  return { ...fields, lagDays, stale: isStale(fields.frequency, lagDays) };
}

// Daily: the US equity ETF total's one-week flow (five sessions), in $bn. The percentile is the build's own rank of that week among three years.
function etfRow(etf, pageAsOf) {
  const agg = (etf?.aggregates || []).find((a) => a.name === 'US equity');
  const flow = agg?.latest?.flow_1w;
  if (!present(flow) || !agg.latest_date) return null;
  const bn = flow / 1e9;
  return makeRow({
    key: 'etf_us_equity',
    label: 'ETF flows (US equity)',
    latest: bn,
    unit: '$bn',
    text: `${bnText(bn)} 1W`,
    direction: directionOf(flow),
    percentile: orNull(agg.latest.pct_rank_1w),
    span: '3Y of weeks',
    spark: recentValues((agg.rolling_20 || []).map((v) => (present(v) ? v / 1e9 : null)), 60),
    asOf: agg.latest_date,
    frequency: 'daily',
    section: 'etf',
  }, pageAsOf);
}

// Weekly: leveraged money's net position in the E-mini as % of open interest. Direction is the week's change in contracts.
function futuresRow(cot, pageAsOf) {
  const es = (cot?.contracts || []).find((c) => c.key === 'es');
  const lev = (es?.categories || []).find((c) => c.key === 'lev_money');
  if (!present(lev?.net_pct_oi) || !cot.report_date) return null;
  return makeRow({
    key: 'futures_lev_money_es',
    label: 'Leveraged funds · ES futures',
    latest: lev.net_pct_oi,
    unit: '% OI',
    text: `${signedPct(lev.net_pct_oi)} OI`,
    direction: directionOf(lev.change_1w),
    percentile: orNull(lev.pctile_3y),
    span: '3Y',
    spark: recentValues(es.history?.categories?.lev_money, 52),
    asOf: cot.report_date,
    frequency: 'weekly',
    section: 'futures',
  }, pageAsOf);
}

// Quarterly: a holder group's net purchases in the latest Z.1 quarter, percentile against its own quarters on record.
function z1Row(z1, key, label, pageAsOf) {
  const latest = (z1?.latest || []).find((r) => r.key === key);
  if (!present(latest?.q_bn) || !z1.latest_quarter_end) return null;
  const history = z1.history?.groups?.[key];
  return makeRow({
    key: `z1_${key}`,
    label,
    latest: latest.q_bn,
    unit: '$bn',
    text: `${bnText(latest.q_bn)} · ${z1.latest_quarter}`,
    direction: directionOf(latest.q_bn),
    percentile: percentileOf(latest.q_bn, history),
    // One quarter against its own quarters here; the Z.1 detail ranks the four-quarter sum since 1990.
    span: `${(history || []).filter(present).length} quarters`,
    spark: recentValues(history, 12),
    asOf: z1.latest_quarter_end,
    frequency: 'quarterly',
    section: 'demand',
  }, pageAsOf);
}

// Quarterly: S&P 500 cash buybacks in the last completed quarter that the issuer coverage supports.
function buybackRow(buybacks, pageAsOf) {
  const quarters = (buybacks?.indices?.SPX?.history?.quarterly || []).filter((r) => (
    r.period_ended && present(r.covered_sum_bn) && present(r.coverage_pct) && r.coverage_pct >= MIN_BUYBACK_COVERAGE
  ));
  const last = quarters[quarters.length - 1];
  if (!last) return null;
  const values = quarters.map((r) => r.covered_sum_bn);
  return makeRow({
    key: 'companies_spx_buybacks',
    label: 'Companies (S&P 500 buybacks)',
    latest: last.covered_sum_bn,
    unit: '$bn',
    text: `${bnText(last.covered_sum_bn)} · ${last.period}`,
    direction: directionOf(last.covered_sum_bn),
    percentile: percentileOf(last.covered_sum_bn, values),
    span: `${values.length} quarters`,
    spark: recentValues(values, 12),
    asOf: last.date,
    frequency: 'quarterly',
    section: 'buybacks',
  }, pageAsOf);
}

// Quarterly: hedge funds' net equity exposure as % of net assets (Form PF). Direction is the quarter's change.
function hedgeRow(hf, pageAsOf) {
  const latest = (hf?.latest || []).find((r) => r.id === 'equity_net_pct_nav');
  if (!present(latest?.value) || !latest.period) return null;
  const series = (hf.series || []).find((s) => s.id === 'equity_net_pct_nav');
  return makeRow({
    key: 'hedge_net_equity_form_pf',
    label: 'Hedge funds (Form PF) · net equity',
    latest: latest.value,
    unit: '% NAV',
    text: `${levelPctText(latest.value)} of NAV`,
    direction: directionOf(latest.q_change),
    // A level of exposure, not a flow: its change is read as exposure up or down, not buying.
    exposure: true,
    percentile: orNull(latest.percentile),
    span: 'own history',
    spark: recentValues(series?.values, 12),
    asOf: latest.period,
    frequency: 'quarterly',
    section: 'hedge',
  }, pageAsOf);
}

// Rows for every participant whose data is in the build, ordered for reading.
// `asOf` is the page's own date; the lag of each source is measured from it.
export function scorecardRows({ asOf = null, etf, cot, z1, buybacks, hfLeverage } = {}) {
  const rows = [
    etfRow(etf, asOf),
    futuresRow(cot, asOf),
    ...Z1_ROWS.map(([key, label]) => z1Row(z1, key, label, asOf)),
    buybackRow(buybacks, asOf),
    hedgeRow(hfLeverage, asOf),
  ].filter(Boolean);
  return sortRows(rows);
}

// The last-quarter bars: every holder group's net purchases, largest buyer first, largest seller last.
export function holderBars(z1) {
  const bars = (z1?.latest || [])
    .filter((r) => HOLDER_KEYS.includes(r.key) && present(r.q_bn))
    .map((r) => ({ key: r.key, label: r.label, value: r.q_bn }))
    .sort((a, b) => b.value - a.value);
  if (!bars.length || !z1.latest_quarter) return null;
  return { quarter: z1.latest_quarter, bars };
}
