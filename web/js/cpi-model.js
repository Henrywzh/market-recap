// Pure CPI display logic, kept independently testable from the DOM/charts.
export const finite = (v) => typeof v === 'number' && Number.isFinite(v);

export function surpriseState(value) {
  if (!finite(value)) return { label: 'NO CONSENSUS', tone: 'dim' };
  if (Math.abs(value) < 0.00001) return { label: 'IN LINE', tone: 'dim' };
  return value > 0 ? { label: 'ABOVE CONSENSUS', tone: 'warn' } : { label: 'BELOW CONSENSUS', tone: 'info' };
}

export function historyMonths(components, count) {
  const months = [...new Set(components.flatMap((r) => (r.history?.observations || []).map((x) => x.month)))].sort();
  return months.slice(-count);
}

export function heatCell(observation, mode) {
  const value = mode === 'percentile' ? observation?.percentile : observation?.mom;
  if (!finite(value)) return { value: null, strength: 0, warm: false };
  // Common scale across rows: raw monthly changes saturate at +/-1%;
  // percentiles use 0..100. Neither scale is an inflation risk score.
  const centered = mode === 'percentile' ? (value - 50) / 50 : value;
  return { value, strength: Math.min(1, Math.abs(centered)), warm: centered > 0 };
}

// The bridge closes the official effects to the headline. When the unrounded
// FRED index change is present, the last bar is that change and the bridge is
// aggregation; otherwise the bridge is rounding to the published headline rate.
export function contributionSteps(data) {
  const c = data?.contributions;
  if (!Array.isArray(data?.components)) return [];
  const indexed = finite(c?.headline_mom_index) && finite(c?.residual_index_pp);
  const headline = indexed ? c.headline_mom_index : c?.headline_mom;
  const bridge = indexed ? c.residual_index_pp : c?.residual_pp;
  if (!finite(headline) || !finite(bridge)) return [];
  const rows = (c.keys || []).map((key) => data.components.find((r) => r.key === key));
  if (rows.some((r) => !finite(r?.effect_pp))) return [];
  let total = 0;
  return [...rows.map((r) => ({ label: r.label, value: r.effect_pp, official: true })),
    { label: indexed ? 'Aggregation' : 'Rounding', value: bridge, official: false, bridge: indexed ? 'aggregation' : 'rounding' }].map((r) => {
    const before = total;
    total += r.value;
    return { ...r, before, after: total, base: Math.min(before, total), height: Math.abs(r.value) };
  }).concat([{ label: indexed ? 'Headline (index)' : 'Headline', value: headline, before: 0, after: headline,
    base: Math.min(0, headline), height: Math.abs(headline), total: true, indexed }]);
}

// PPI industry coverage. On the release day FRED usually posts these industry
// series a day after BLS, so pending series are expected, not failures.
export function aiCoverage(data) {
  const series = data?.ai_series || [];
  const updated = series.filter((r) => r.status === 'ok').length;
  if (data?.ai_pending_expected === true && series.some((r) => r.status === 'pending')) {
    return { text: `Release day: FRED usually posts these industry series a day after BLS · ${updated}/${series.length} updated`, expected: true };
  }
  return { text: `${updated}/${series.length} series updated through ${data?.month} · BLS via FRED · monthly NSA`, expected: false };
}
