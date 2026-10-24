// Descriptive comparisons of published rows, not a fair-multiple model.
export const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const num1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
const positive = (v) => finite(v) && v > 0;
const isoDate = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
// Fiscal calendars rarely share a day (52/53-week years end on a weekday):
// period ends within this many days are the same quarter or year, with the gap stated.
export const PERIOD_TOLERANCE_DAYS = 45;
const DAY_MS = 86400000;
export const daysApart = (x, y) => (isoDate(x) && isoDate(y) ? Math.abs(Date.parse(x) - Date.parse(y)) / DAY_MS : null);
// Null when aligned; otherwise why not. `gapNote` states a tolerated difference.
function alignment(x, y, what) {
  const days = daysApart(x, y);
  if (days === null) return { issue: `${what} unavailable`, gapNote: '' };
  if (days > PERIOD_TOLERANCE_DAYS) return { issue: `${what} ${days} days apart; windows are not aligned`, gapNote: '' };
  return { issue: null, gapNote: days ? ` ${what} ${days} days apart.` : '' };
}

export const COMPARISON_BASES = [
  ['pe_forward', 'Forward P/E · next 12 months'],
  ['pe_operating', 'Operating / adjusted P/E · TTM'], ['pe', 'Reported P/E · TTM'],
  ['pb', 'P / book'], ['ptbv', 'P / tangible book'],
];

export function comparisonBasisNote(basis, a, b) {
  if (basis === 'pe_forward') return 'Default view: price / analysts’ next-12-month EPS. Forecast earnings, not reported or operating earnings.';
  if (basis === 'pe_operating') {
    const label = (row) => row?.pe_basis === 'operating' ? 'operating-adjusted EPS'
      : row?.pe_basis === 'ex_gains' ? 'EPS excluding equity-security gains / losses after tax' : 'adjusted basis unavailable';
    return `${a.ticker}: ${label(a)}. ${b.ticker}: ${label(b)}. Dashboard-adjusted trailing earnings; not price / EBIT or analyst-adjusted forward earnings. Different adjustment bases withhold directional evidence.`;
  }
  if (basis === 'pe') return 'Price / reported trailing-12-month earnings. One-off gains and charges can affect this multiple.';
  return basis === 'ptbv' ? 'Price / tangible book equity. Read alongside ROTCE and asset quality for banks; not an earnings multiple.'
    : 'Price / book equity. Read alongside ROE and balance-sheet quality; not an earnings multiple.';
}

export function sameIssuer(a, b) {
  const cik = (row) => row?.cik != null && String(row.cik).trim() !== '' ? String(row.cik).trim().replace(/^0+/, '') : null;
  return Boolean(a && b && (a.ticker === b.ticker || (cik(a) && cik(a) === cik(b))));
}

export function suggestPeer(rows, selected) {
  if (!selected) return null;
  const peers = rows.filter((r) => !sameIssuer(r, selected) && r.sector && r.sector === selected.sector);
  const closeness = (r) => positive(r.market_cap) && positive(selected.market_cap)
    ? Math.abs(Math.log(r.market_cap / selected.market_cap)) : Infinity;
  peers.sort((a, b) => Number(b.sub_sector === selected.sub_sector && Boolean(selected.sub_sector))
    - Number(a.sub_sector === selected.sub_sector && Boolean(selected.sub_sector))
    || closeness(a) - closeness(b) || a.ticker.localeCompare(b.ticker));
  return peers[0] || null;
}

export function cashConversion(row) {
  // Both yields share market cap, so the price cancels. This is OCF minus
  // cash CapEx / reported NI, not FCFE and not an SBC-adjusted cash measure.
  return positive(row?.earnings_yield) && finite(row?.fcf_yield)
    ? row.fcf_yield / row.earnings_yield * 100 : null;
}

export function revenueForecast(row) {
  const context = row?.revenue_consensus;
  const periods = context?.periods || [];
  const period = periods.find((p) => p.period === '+1y') || null;
  return period && finite(period.growth_pct) && isoDate(period.end)
    ? { value: period.growth_pct, end: period.end, observed: context.observed_market_date } : null;
}

function recordIssue(row, asOf) {
  if (!isoDate(asOf) || !isoDate(row?.period_end) || !isoDate(row?.filed)) return 'Statement dates unavailable';
  if (row.period_end > asOf || row.filed > asOf) return 'Statement dated after the price session';
  return null;
}

function lagged(row, keys) {
  return (row?.lagged || []).some((key) => keys.includes(key));
}

export function comparisonEvidence(a, b, { basis = 'pe_forward', asOf, financialsSector } = {}) {
  const primaryA = positive(a?.[basis]) ? a[basis] : null;
  const primaryB = positive(b?.[basis]) ? b[basis] : null;
  const premium = primaryA !== null && primaryB !== null ? (primaryA / primaryB - 1) * 100 : null;
  const distinct = a && b && !sameIssuer(a, b);
  const sameBusinessGroup = Boolean(distinct && a.sector && a.sector === b.sector
    && a.sub_sector && a.sub_sector === b.sub_sector);
  const financial = Boolean(financialsSector && a?.sector === financialsSector && b?.sector === financialsSector);
  const adjustedIssue = basis === 'pe_operating'
    && (!['operating', 'ex_gains'].includes(a?.pe_basis) || a.pe_basis !== b?.pe_basis)
    ? 'Adjusted earnings bases differ or are unavailable; operating and ex-gains are not interchangeable' : null;
  const issue = !distinct ? 'Choose two different issuers'
    : !sameBusinessGroup ? 'Different or missing sub-industries; no directional comparison'
      : recordIssue(a, asOf) || recordIssue(b, asOf) || adjustedIssue
        || (['pb', 'ptbv'].includes(basis) && !financial ? 'Book-based business comparability not established' : null);
  // A sub-0.05% gap rounds to 0.0%; do not call either name more expensive.
  const leader = premium !== null && Math.round(Math.abs(premium) * 10) > 0
    ? (premium > 0 ? a : b) : null;
  const direction = leader === a ? 1 : -1;
  const rows = [];
  const add = ({ key, label, av, bv, unit = '%', higher = true, note, contextOnly = false, blocked = null }) => {
    let state = 'unknown';
    let reason = issue || blocked;
    if (!finite(av) || !finite(bv)) reason = 'Missing input; no replacement or zero assumed';
    else if (!reason && primaryA !== null && primaryB !== null && leader) {
      if (contextOnly) { state = 'context'; reason = note; }
      else {
        // Compare only distinctions visible at the displayed precision.
        const difference = Math.round(av * 10) - Math.round(bv * 10);
        state = difference === 0 ? 'similar' : difference * direction * (higher ? 1 : -1) > 0 ? 'supports' : 'counterpoint';
        reason = note;
      }
    } else if (!reason) reason = leader ? 'Selected multiple unavailable' : 'No visible relative premium to explain';
    rows.push({ key, label, a: finite(av) ? av : null, b: finite(bv) ? bv : null, unit, state, reason, note });
  };
  const af = revenueForecast(a), bf = revenueForecast(b);
  const forecastIssue = !af || !bf ? 'Dated next-FY revenue estimates unavailable'
    : !isoDate(af.observed) || !isoDate(bf.observed) ? 'Estimate observation dates unavailable'
      : af.observed > asOf || bf.observed > asOf ? 'Estimate observed after the price session'
        : null;
  const fiscal = af && bf ? alignment(af.end, bf.end, 'Forecast fiscal year-ends') : { issue: null, gapNote: '' };
  add({ key: 'growth', label: 'Revenue growth · next FY', av: af?.value, bv: bf?.value, blocked: forecastIssue || fiscal.issue,
    note: `Near-term analyst estimates, not a long-term growth forecast.${fiscal.gapNote}` });
  // What the price needs against what analysts expect: the reverse DCF's growth at
  // today's margin less the +1y revenue consensus (panels/valuation._expectation_gap).
  const expectation = (row) => finite(row?.implied_growth) && finite(row?.consensus_growth)
    ? row.implied_growth - row.consensus_growth : null;
  const pair = (row) => `${row?.ticker} ${finite(row?.implied_growth) ? `${num1(row.implied_growth)}%` : '—'} implied / ${finite(row?.consensus_growth) ? `${num1(row.consensus_growth)}%` : '—'} consensus`;
  add({ key: 'expectations', label: 'Price-implied growth over consensus', av: expectation(a), bv: expectation(b),
    unit: 'pp', higher: false,
    note: `${pair(a)}; ${pair(b)}. Reverse-DCF growth at today's margin and the shared WACC, less next-FY revenue consensus. A smaller excess asks less of the business beyond what analysts expect; a scenario, not a forecast.` });
  const returnKey = basis === 'ptbv' && financial ? 'rotce' : financial || basis === 'pb' ? 'roe' : 'roic';
  const periods = alignment(a?.period_end, b?.period_end, 'Statement period ends');
  const timing = periods.issue;
  add({ key: 'capital_return', label: returnKey === 'rotce' ? 'ROTCE · TTM' : returnKey === 'roe' ? 'ROE · TTM' : 'ROIC · TTM',
    av: a?.[returnKey], bv: b?.[returnKey], blocked: timing || (lagged(a, ['equity', 'revenue', 'ebit', 'net_income'])
      || lagged(b, ['equity', 'revenue', 'ebit', 'net_income']) ? 'Return inputs include a carried line' : null),
    note: `Reported accounting return, not a measured moat or incremental future return.${periods.gapNote}` });
  if (financial) {
    add({ key: 'asset_quality', label: 'Asset quality & capital buffers', av: null, bv: null,
      note: 'Comparable credit losses, capital requirements and reserve quality are not in this comparison.' });
  } else {
    add({ key: 'cash_conversion', label: 'Cash conversion · TTM', av: cashConversion(a), bv: cashConversion(b),
      contextOnly: true, blocked: timing,
      note: `(OCF − cash CapEx) / reported earnings. Working capital and SBC can distort one period; not distributable cash.${periods.gapNote}` });
    add({ key: 'margin_stability', label: 'Operating-margin volatility', av: a?.margin_stability, bv: b?.margin_stability,
      unit: 'pp', higher: false, contextOnly: true,
      note: 'Annual reported-margin standard deviation; history coverage may differ. Lower is steadier, not necessarily better value.' });
    const debtIssue = !a?.debt_basis || !b?.debt_basis || a.debt_basis === 'no debt tagged' || b.debt_basis === 'no debt tagged'
      ? 'Debt basis unknown; missing debt is not zero' : null;
    add({ key: 'leverage', label: 'Net debt / EBITDA · TTM', av: a?.net_debt_ebitda, bv: b?.net_debt_ebitda,
      unit: 'x', higher: false, blocked: timing || debtIssue,
      note: `One balance-sheet risk dimension; no conclusion about all business risks.${periods.gapNote}` });
  }
  return { basis, primaryA, primaryB, premium, leader: leader?.ticker || null, sameBusinessGroup, financial, issue, rows };
}

// Color describes direction of a measured valuation, not good/bad investment.
export function valuationRankClass(rank, group) {
  if (!finite(rank)) return '';
  if (group === 'valuation') return rank >= .8 ? 'valuation-lower' : rank <= .2 ? 'valuation-higher' : '';
  return rank >= .8 ? 'up' : rank <= .2 ? 'down' : '';
}
