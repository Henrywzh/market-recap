import { el, card, table, num, tag, periodSwitch, metaRow, DASH } from '../fmt.js';
import { render, timeLines } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { finite, surpriseState, heatCell, historyMonths, contributionSteps } from '../cpi-model.js';
import { weightCell, releaseHistory, caveats } from '../inflation-ui.js';

const rate = (v, digits = 1) => finite(v) ? `${num(v, digits)}%` : DASH;
const signed = (v, digits = 2) => finite(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}` : DASH;
const monthName = (m) => m ? new Date(`${m}-01T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : DASH;

export function releaseStrip(data, kind = 'CPI') {
  const published = new Date(data.published_at).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  const tiles = (data.comparisons || []).map((r) => {
    const state = surpriseState(r.surprise_pp);
    return el('div', { class: 'cpi-print', [`data-${kind.toLowerCase()}-metric`]: r.key }, [
      el('div', { class: 'cpi-print-label', text: `${r.label} · ${r.basis}` }),
      el('div', { class: 'cpi-print-value', text: rate(r.actual) }),
      el('div', { class: 'cpi-print-compare' }, [
        el('span', { text: `consensus ${rate(r.consensus)}` }),
        tag(state.label, state.tone),
      ]),
      el('div', { class: 'cpi-print-detail', text: `${signed(r.surprise_pp)} pp surprise · previous ${rate(r.previous)}` }),
    ]);
  });
  return card(`${kind} RELEASE · ${monthName(data.month).toUpperCase()}`, el('a', { href: data.source_url, target: '_blank', rel: 'noopener', class: 'dim', text: 'BLS release ↗' }), [
    el('div', { class: 'cpi-release-date', text: `Published ${published} New York · reference month ${data.month}` }),
    el('div', { class: 'cpi-prints' }, tiles),
    ...caveats('Consensus is a retrospective TradingView calendar figure, not a frozen pre-release survey.',
      'Actual: official BLS. Consensus / previous: TradingView calendar, recovered retrospectively. Surprise = actual − consensus, in percentage points. Previous may include revisions.'),
  ]);
}

function contributionCard(data) {
  const steps = contributionSteps(data);
  if (!steps.length) return card('WHAT DROVE THE PRINT', null, el('div', { class: 'gap', text: 'Official contribution partition is incomplete; no total is inferred.' }));
  const chart = el('div', { class: 'chart cpi-waterfall', role: 'img', 'aria-label': 'Food, energy and core official effects, bridge and headline monthly CPI' });
  requestAnimationFrame(() => render(chart, (option, p) => ({
    ...option,
    grid: { left: 56, right: 18, top: 24, bottom: 45 },
    xAxis: { ...option.xAxis, type: 'category', data: steps.map((s) => s.label), boundaryGap: true,
      axisLabel: { ...option.xAxis.axisLabel, interval: 0, fontSize: 10,
        formatter: (v) => chart.clientWidth < 500 && v === 'Headline (index)' ? 'Headline\n(index)' : v } },
    yAxis: { ...option.yAxis, scale: false, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 2)}` } },
    tooltip: { ...option.tooltip, formatter: (items) => {
      const s = steps[items[0].dataIndex];
      const component = data.components.find((r) => r.label === s.label);
      const meaning = s.total ? (s.indexed ? 'Unrounded FRED headline index change; BLS publishes the rounded rate' : 'Published headline MoM')
        : s.official ? `Official BLS effect on all-items CPI<br>Weight ${rate(component?.weight_pct, 2)} · ${data.weight_month}`
          : s.bridge === 'aggregation' ? 'Unrounded headline index change minus the sum of effects; not another category'
            : 'Published headline minus the sum of effects; not another category';
      return `${s.label}: <b>${signed(s.value, 3)} pp</b><br>${meaning}`;
    } },
    series: [
      { type: 'bar', stack: 'effect', stackStrategy: 'all', silent: true, itemStyle: { color: 'transparent' }, data: steps.map((s) => s.base) },
      { type: 'bar', stack: 'effect', stackStrategy: 'all', barMaxWidth: 58,
        label: { show: true, position: 'top', color: p.text, fontSize: 11, formatter: (r) => signed(steps[r.dataIndex].value, 3) },
        data: steps.map((s) => ({ value: s.height, itemStyle: { color: s.total ? p.accent : !s.official ? p.faint : s.value >= 0 ? '#d88b78' : '#72a8cf' } })) },
    ],
  })));
  const c = data.contributions;
  const indexed = steps.at(-1).indexed;
  const bridge = steps.at(-2);
  const published = finite(c.headline_mom) ? `BLS publishes ${rate(c.headline_mom)} (rounded)` : 'The rounded BLS headline is not supplied';
  return card('WHAT DROVE THE PRINT', el('span', { class: 'dim', text: 'effect on headline · pp' }), [
    chart,
    ...caveats(`${published}${indexed ? '; the last bar is the unrounded index change' : ''}.`,
      `Food + energy + core are non-overlapping. Official effects sum to ${signed(c.sum_pp, 3)} pp; ${indexed ? 'aggregation' : 'rounding'} ${signed(bridge.value, 3)} pp bridges them to the ${indexed ? 'unrounded FRED index change' : 'published headline'}. Seasonal aggregation and published rounding need not add exactly. These are inflation contributions, not surprise contributions.`),
  ]);
}

function componentTable(data) {
  const rows = data.components.map((r) => {
    const o = r.history?.observations?.find((x) => x.month === data.month);
    return el('tr', {}, [
      el('td', {}, [el('span', { text: r.label }), r.key === 'headline' || r.key === 'core' ? el('span', { class: 'sub', text: 'aggregate · overlaps rows below' }) : null]),
      weightCell(r.weight_pct, data.weight_month),
      el('td', { text: rate(r.mom) }),
      el('td', { text: rate(r.yoy) }),
      el('td', { text: signed(r.effect_pp, 3) }),
      el('td', { title: `Current-vintage FRED MoM ${rate(o?.mom, 3)} · ${o?.prior_n || 0} earlier monthly observations`, text: finite(o?.percentile) ? `P${num(o.percentile, 0)}` : DASH }),
      el('td', { text: finite(o?.p10) && finite(o?.p90) ? `${num(o.p10, 2)} to ${num(o.p90, 2)}%` : DASH }),
    ]);
  });
  return el('details', { class: 'sx-fold cpi-detail' }, [
    el('summary', { text: 'COMPONENT DETAIL · WEIGHT, CHANGE & CONTRIBUTION' }),
    table(['CATEGORY', `WEIGHT · ${data.weight_month}`, 'MoM SA', 'YoY NSA', 'EFFECT · pp', 'MoM PCTL', 'PRIOR 10–90% BAND'], rows),
    ...caveats('Parents and children overlap: do not sum this table.',
      'Weights and effects: BLS Table 6; YoY: Table 1. Percentile and 10–90% band: each component’s current-vintage FRED monthly moves against its own prior ten years (at least 60 earlier months); not consensus errors, sampling intervals or “acceptable” inflation. No component consensus is available, so component surprise is not estimated.'),
  ]);
}

function heatmapCard(data) {
  let mode = 'mom';
  let count = 12;
  const host = el('div', { class: 'cpi-heat-host' });
  const draw = () => {
    const months = historyMonths(data.components, count);
    const rows = data.components.map((r) => {
      const byMonth = new Map((r.history?.observations || []).map((o) => [o.month, o]));
      return el('tr', {}, [el('td', { text: r.label }), weightCell(r.weight_pct, data.weight_month), ...months.map((m) => {
        const o = byMonth.get(m);
        const c = heatCell(o, mode);
        const rgb = c.warm ? '166,83,65' : '48,102,145';
        return el('td', { text: finite(c.value) ? num(c.value, mode === 'mom' ? 2 : 0) : DASH,
          style: finite(c.value) ? `background:rgba(${rgb},${0.08 + .55 * c.strength})` : '',
          title: `${r.label} · ${m} · ${mode === 'mom' ? 'SA MoM % (current vintage)' : `prior-only percentile · ${o?.prior_n || 0} earlier months`}` });
      })]);
    });
    host.replaceChildren(table(['CATEGORY', 'WEIGHT', ...months.map((m) => `${m.slice(2, 4)}/${m.slice(5)}`)], rows));
  };
  const controls = el('div', { class: 'cpi-controls' }, [
    periodSwitch(['MoM %', 'Percentile'], 'MoM %', (v) => { mode = v === 'MoM %' ? 'mom' : 'percentile'; draw(); }),
    periodSwitch(['6M', '1Y', '2Y'], '1Y', (v) => { count = { '6M': 6, '1Y': 12, '2Y': 24 }[v]; draw(); }),
  ]);
  draw();
  return card('WHERE PRESSURE IS BUILDING', controls, [host,
    ...caveats(`Blue bars: basket weight on a common 0–100% scale, from the latest release (BLS ${data.weight_month}), not each month's weight.`,
      'Monthly component history: unrounded index-implied changes, current FRED vintage; release cards use BLS published rounded rates. MoM colors share a zero-centered scale, saturated at ±1%; percentile colors center on 50. A high percentile means unusual for that category, not necessarily a large headline effect. Missing months stay blank; this is not weighted inflation breadth. Blue does not mean good/bad.'),
  ]);
}

function persistenceCard(data) {
  const rows = data.persistence || [];
  let group = 'Core momentum';
  const dates = [...new Set(rows.flatMap((r) => r.history?.dates || []))].sort();
  let range = initialRange(dates, '3Y');
  const node = el('div', { class: 'chart', 'aria-label': 'Inflation persistence history, grouped by comparable measurement basis' });
  const switchHost = el('span');
  const groups = { 'Core momentum': ['core_3m', 'core_6m'], 'Sticky · YoY': ['sticky', 'core_sticky'], 'Robust · 1M annualized': ['median', 'trimmed'] };
  const draw = () => {
    const selected = rows.filter((r) => groups[group].includes(r.key) && r.history?.dates?.length);
    const lines = selected.map((r) => ({ name: r.label, ...sliceRange(r.history.dates, { values: r.history.values }, range) }));
    if (lines.some((r) => r.values.some(finite))) timeLines(node, lines, { value: (v) => rate(v, 2) });
    else node.replaceChildren(el('div', { class: 'gap', text: 'This measure has not been published for the selected window.' }));
    switchHost.replaceChildren(rangeSwitch(dates, range, (v) => { range = v; draw(); }));
  };
  const stats = el('div', { class: 'cpi-persistence-stats' }, rows.map((r) => el('div', { class: 'cpi-persistence-reading' }, [
    el('div', { class: 'stat-label', text: r.label }),
    el('div', { class: 'cpi-persistence-value', text: rate(r.value, 2) }),
    el('div', { class: 'stat-note', text: `${r.unit} · ${r.status === 'pending' ? `pending ${data.month}` : r.latest_month}` }),
    r.status === 'pending' && finite(r.latest_value) ? el('div', { class: 'stat-note', text: `last ${rate(r.latest_value, 2)} · ${r.latest_month}` }) : null,
  ])));
  requestAnimationFrame(draw);
  return card('IS IT PERSISTING?', switchHost, [stats,
    periodSwitch(Object.keys(groups), group, (v) => { group = v; draw(); }), node,
    ...caveats('Different measurement bases are charted separately; the Fed’s 2% target is PCE, not CPI.',
      'Core 3M/6M: compound annualized index change, requiring every month in the window. Sticky/core sticky: Atlanta Fed YoY; median/trimmed mean: Cleveland Fed 1M annualized. Sticky means infrequent price adjustment—not proof an energy shock has spread.'),
  ]);
}

export default function renderCpi(root, data) {
  const host = el('section', { class: 'cpi-section', 'aria-label': 'CPI release analysis' });
  root.append(host);
  if (!data || data.status === 'unavailable') {
    host.append(card('CPI RELEASE', null, el('div', { class: 'gap', text: data?.reason || 'CPI analysis has not been built. Existing PCE and commodity data remain below.' })));
    return;
  }
  host.append(releaseStrip(data));
  host.append(el('div', { class: 'cpi-analysis-grid' }, [contributionCard(data), persistenceCard(data)]));
  host.append(heatmapCard(data), componentTable(data), releaseHistory(data));
  const failures = Object.keys(data.failed_sources || {});
  host.append(metaRow(`BLS reference ${data.month} · weights ${data.weight_month} · ${data.refresh_note}`, [
    data.note,
    `BLS read ${data.retrieved_at}. Calendar file fetched ${data.consensus_retrieved_at || 'unknown'} (not a verified pre-release timestamp).`,
    data.consensus_note ? `Consensus source gap: ${data.consensus_note}` : null,
    failures.length ? `Missing sources: ${failures.join(', ')}` : null,
    'This view does not estimate a component’s expected move, a priced-in share, energy-to-service pass-through or an intraday market response. Those require additional evidence.',
  ]));
}
