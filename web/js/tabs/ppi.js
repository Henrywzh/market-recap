import { el, card, table, num, periodSwitch, metaRow, DASH } from '../fmt.js';
import { finite, heatCell, historyMonths, aiCoverage } from '../cpi-model.js';
import { weightCell, releaseHistory, caveats } from '../inflation-ui.js';
import { timeLines } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { releaseStrip } from './cpi.js';

const rate = (v, digits = 2) => finite(v) ? `${num(v, digits)}%` : DASH;

function momentumCard(data) {
  const rows = data.momentum || [];
  const hasPending = rows.some((r) => r.status === 'pending');
  const tableRows = rows.map((r) => el('tr', {}, [
    el('td', {}, [el('a', { href: r.source_url, target: '_blank', rel: 'noopener', text: r.label }),
      el('span', { class: 'sub', text: r.status === 'ok' ? `SA index through ${r.latest_month}`
        : r.status === 'pending' ? `pending ${data.month} · last ${r.latest_month}` : 'SA index unavailable' })]),
    el('td', { text: rate(r.release_mom, 1) }),
    el('td', { text: rate(r.ann_3m) }), el('td', { text: rate(r.ann_6m) }),
    hasPending ? el('td', { text: r.status === 'pending'
      ? `${r.latest_month}: ${rate(r.latest_ann_3m)} / ${rate(r.latest_ann_6m)}` : DASH }) : null,
  ]));
  let selected = rows[0]?.key;
  const dates = historyMonths(rows, Infinity).map((m) => `${m}-01`);
  let range = initialRange(dates, '3Y');
  const chart = el('div', { class: 'chart ppi-momentum-chart', role: 'img', 'aria-label': 'PPI seasonally adjusted 3-month and 6-month annualized momentum' });
  const switches = el('span');
  const draw = () => {
    const row = rows.find((r) => r.key === selected);
    const obs = row?.history?.observations || [];
    const lines = [['ann_3m', '3M annualized'], ['ann_6m', '6M annualized']].map(([key, name]) => ({
      name, ...sliceRange(obs.map((o) => `${o.month}-01`), { values: obs.map((o) => o[key]) }, range),
    }));
    if (lines.some((r) => r.values.some(finite))) timeLines(chart, lines, { value: (v) => rate(v), markY: [{ y: 0 }] });
    else chart.replaceChildren(el('div', { class: 'gap', text: 'No complete SA index windows available. No annualized trend is inferred from NSA industry prices.' }));
    switches.replaceChildren(rangeSwitch(dates, range, (v) => { range = v; draw(); }));
  };
  const selector = el('select', { class: 'ppi-momentum-select', 'aria-label': 'PPI momentum category',
    onchange: (e) => { selected = e.target.value; draw(); } }, rows.map((r) => el('option', { value: r.key, text: r.label })));
  requestAnimationFrame(draw);
  return card('IS PRODUCER INFLATION PERSISTING?', switches, [
    tableRows.length ? table(['FINAL DEMAND GROUP', 'MoM SA · RELEASE', '3M ANN. %', '6M ANN. %', ...(hasPending ? ['OLDER 3M / 6M · IF PENDING'] : [])], tableRows,
      { class: hasPending ? 'ppi-momentum-table ppi-momentum-pending' : 'ppi-momentum-table' })
      : el('div', { class: 'gap', text: 'PPI momentum has not been built.' }),
    el('div', { class: 'cpi-controls' }, [el('label', {}, [el('span', { class: 'dim', text: 'TREND ' }), selector])]),
    chart,
    ...caveats('Groups overlap; not a score, policy target or proof of pass-through.',
      '3M / 6M: compounded annualized SA index changes; every month required. Current vintage, not first prints. MoM: official rounded BLS release. Pending histories stay blank, with older readings separately dated.'),
  ]);
}

function aiHeatmap(data) {
  let count = 12;
  let mode = 'yoy';
  const host = el('div', { class: 'ppi-heat-host' });
  const draw = () => {
    const months = historyMonths(data.ai_series, count);
    const rows = data.ai_series.map((r) => {
      const map = new Map(r.history.observations.map((o) => [o.month, o]));
      return el('tr', {}, [el('td', { title: r.detail }, [
        el('a', { href: r.source_url, target: '_blank', rel: 'noopener', text: r.label }),
        el('span', { class: 'sub', text: r.status === 'ok' ? `updated ${r.latest_month}` : r.status === 'pending' ? `pending ${data.month} · last ${r.latest_month}` : 'series unavailable' }),
      ]), ...months.map((m) => {
        const o = map.get(m);
        const raw = mode === 'yoy' ? o?.yoy : mode === 'mom' ? o?.mom : o?.percentile;
        // YoY has its own explicit +/-10% scale; monthly uses +/-1%.
        const cell = heatCell(mode === 'yoy' ? { mom: finite(raw) ? raw / 10 : null } : o, mode === 'percentile' ? mode : 'mom');
        return el('td', { text: finite(raw) ? num(raw, mode === 'percentile' ? 0 : 2) : DASH,
          style: finite(raw) ? `background:rgba(${cell.warm ? '166,83,65' : '48,102,145'},${.08 + .55 * cell.strength})` : '',
          title: `${r.label} · ${m} · ${mode === 'percentile' ? 'MoM prior-only percentile (not seasonally neutral)' : `${mode.toUpperCase()} % · NSA`}` });
      })]);
    });
    host.replaceChildren(table(['INDUSTRY · NSA', ...months.map((m) => `${m.slice(2, 4)}/${m.slice(5)}`)], rows));
  };
  const controls = el('div', { class: 'cpi-controls' }, [
    periodSwitch(['YoY %', 'MoM %', 'MoM percentile'], 'YoY %', (v) => { mode = { 'YoY %': 'yoy', 'MoM %': 'mom', 'MoM percentile': 'percentile' }[v]; draw(); }),
    periodSwitch(['6M', '1Y', '2Y'], '1Y', (v) => { count = { '6M': 6, '1Y': 12, '2Y': 24 }[v]; draw(); }),
  ]);
  draw();
  const coverage = aiCoverage(data);
  return card('AI INFRASTRUCTURE · INDUSTRY PRICES', controls, [
    el('div', { class: coverage.expected ? 'ppi-coverage dim' : 'ppi-coverage', text: coverage.text }),
    host,
    ...caveats('Broad US producer selling prices, not AI-only prices, input costs, demand volume or revenue.',
      'Same five industry series as alternative-data, shown separately; not a synthetic “AI PPI”. The same price rise is a supplier’s selling-price change and a potential buyer-cost pressure—not a measured change in either side’s profit margin. Industry weights in headline final demand are not supplied here. YoY is the default; NSA monthly changes can be seasonal. MoM colors saturate at ±1%, YoY at ±10%; percentile compares prior monthly moves without removing seasonality.'),
  ]);
}

function aiTrend(data) {
  let mode = 'yoy';
  const dates = historyMonths(data.ai_series, Infinity).map((m) => `${m}-01`);
  let range = initialRange(dates, '3Y');
  const host = el('div', { class: 'chart ppi-trend', role: 'img', 'aria-label': 'AI-related industry producer price growth, not seasonally adjusted' });
  const switchHost = el('span');
  const draw = () => {
    const lines = data.ai_series.map((r) => {
      const obs = r.history.observations;
      return { name: r.label, ...sliceRange(obs.map((o) => `${o.month}-01`), { values: obs.map((o) => o[mode]) }, range) };
    });
    if (lines.some((r) => r.values.some(finite))) timeLines(host, lines, { value: (v) => rate(v), markY: [{ y: 0 }] });
    else host.replaceChildren(el('div', { class: 'gap', text: 'No published industry observations in this window.' }));
    switchHost.replaceChildren(rangeSwitch(dates, range, (v) => { range = v; draw(); }));
  };
  requestAnimationFrame(draw);
  return card('AI-RELATED PPI · PRICE GROWTH', switchHost, [
    periodSwitch(['YoY % · NSA', 'MoM % · NSA'], 'YoY % · NSA', (v) => { mode = v.startsWith('YoY') ? 'yoy' : 'mom'; draw(); }),
    host,
    ...caveats('Comparable percent changes; missing months are not filled or connected.',
      'Not raw index levels with different base years. Select a legend to isolate an industry. Price increases alone do not identify AI demand, supplier margins or CPI pass-through.'),
  ]);
}

function macroBreakdown(data) {
  const rows = data.components.map((r) => el('tr', {}, [
    el('td', {}, [el('span', { text: r.label }), el('span', { class: 'sub', text: r.code })]),
    weightCell(r.weight_pct, data.weight_month),
    el('td', { text: rate(r.mom, 1) }), el('td', { text: rate(r.previous_mom, 1) }), el('td', { text: rate(r.yoy, 1) }),
  ]));
  return card('FINAL DEMAND · WEIGHTS & RELEASE DETAIL', el('span', { class: 'dim', text: `relative importance ${data.weight_month}` }), [
    table(['GROUP', 'WEIGHT', 'MoM SA', 'PREV. MoM SA', 'YoY NSA'], rows),
    ...caveats('Goods, services and construction partition final demand; the other rows overlap them.',
      'Official BLS Table 1. Blue bars share a 0–100% scale and represent published relative importance, not monthly contribution. These are the table’s annual weight reference figures, not CPI’s prior-month weights. No weight × change approximation is presented as an official effect. Trade-services PPI measures margins. Preliminary rates and prior months can be revised.'),
  ]);
}

export default function renderPpi(root, data) {
  const host = el('section', { class: 'cpi-section ppi-section', 'aria-label': 'PPI and AI-related industry prices' });
  root.append(host);
  if (!data || data.status === 'unavailable') {
    host.append(card('PPI RELEASE', null, el('div', { class: 'gap', text: data?.reason || 'PPI analysis has not been built for this session.' })));
    return;
  }
  host.append(releaseStrip(data, 'PPI'), momentumCard(data), aiHeatmap(data), aiTrend(data), macroBreakdown(data), releaseHistory(data));
  host.append(metaRow(`PPI ${data.month} · weights ${data.weight_month} · ${data.refresh_note}`, [
    data.note,
    `BLS read ${data.retrieved_at}. Consensus calendar read ${data.consensus_retrieved_at || 'unknown'}; not a verified pre-release snapshot.`,
    ...data.ai_series.map((r) => `${r.label}: ${r.series_id}, last ${r.latest_month || 'unavailable'}, file read ${r.retrieved_at || 'unknown'}. ${r.detail}`),
    data.consensus_note ? `Consensus source gap: ${data.consensus_note}` : null,
    Object.keys(data.failed_sources || {}).length ? `Pending / missing: ${Object.entries(data.failed_sources).map(([k, v]) => `${k}: ${v}`).join('; ')}` : null,
  ]));
}
