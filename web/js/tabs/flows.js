// Investor transactions, buybacks and positioning retain their own dates and scope.
// The scorecard leads: one row per participant, fastest first, each with its own
// as-of date. Row clicks and the sub-tab row open the same detail views.
import { el, card, metaRow, gap, tag, table, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { spark } from '../spark.js';
import { scorecardRows, holderBars, ordinalText, bnText } from '../flows-scorecard.js';
import { demandPipelineSection } from '../equity-demand.js';
import { investorDemandView } from '../investor-demand.js';
import { section as etfSection } from '../flows-etf.js';
import { section as cotSection } from '../flows-cot.js';
import { section as z1Section } from '../flows-z1.js';
import { section as leverageSection } from '../flows-hf-leverage.js';
import { section as crowdingSection } from '../flows-hf-13f.js';

const DETAIL_KEY = 'flows.detail';
const TABS = [['demand', 'INVESTOR DEMAND'], ['buybacks', 'BUYBACKS'], ['hedge', 'HEDGE FUNDS'], ['futures', 'FUTURES'], ['etf', 'ETF MECHANICS']];
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

// The chosen detail survives a reload. Storage can be blocked, so every access is guarded.
function savedDetail() {
  try {
    const key = localStorage.getItem(DETAIL_KEY);
    return TABS.some(([k]) => k === key) ? key : null;
  } catch { return null; }
}
function saveDetail(key) {
  try { localStorage.setItem(DETAIL_KEY, key); } catch { /* blocked: the choice lasts this page view only */ }
}

// Buying is green and selling red, the dashboard's up and down; flat and unknown stay grey.
const DIRECTION = {
  buy: { cls: 'up', text: 'BUY' },
  sell: { cls: 'down', text: 'SELL' },
  flat: { cls: 'dim', text: 'FLAT' },
};
// A row that is a level of exposure (Form PF) moves up or down; it is not a purchase.
const EXPOSURE = {
  buy: { cls: 'up', text: 'EXPOSURE ↑' },
  sell: { cls: 'down', text: 'EXPOSURE ↓' },
  flat: { cls: 'dim', text: 'FLAT' },
};

function scoreRow(row) {
  const trend = row.spark
    ? spark(row.spark, { width: 80, height: 20 })
    : el('span', { class: 'dim', text: DASH });
  const cells = [
    el('td', { class: 'flows-score-name' }, [
      el('span', { text: row.label }),
      row.stale ? tag('stale', 'warn', `${row.asOf} · ${row.lagDays} days behind this page`) : null,
    ]),
    el('td', { class: 'flows-score-latest', text: row.text }),
    el('td', { class: 'flows-score-dir' }, [el('span', (row.exposure ? EXPOSURE : DIRECTION)[row.direction]
      ? { class: (row.exposure ? EXPOSURE : DIRECTION)[row.direction].cls, text: (row.exposure ? EXPOSURE : DIRECTION)[row.direction].text }
      : { class: 'dim', text: DASH })]),
    el('td', { class: 'flows-score-pct', text: row.percentile == null ? ordinalText(row.percentile) : `${ordinalText(row.percentile)}${row.span ? ` · ${row.span}` : ''}` }),
    el('td', { class: 'flows-score-trend', 'data-dir': row.direction || '' }, [trend]),
    el('td', { class: 'dim', text: row.asOf }),
    el('td', {}, [tag(row.frequency, 'dim')]),
  ];
  return el('tr', {
    class: `flows-score-row${row.stale ? ' is-stale' : ''}`,
    tabindex: '0',
    'data-section': row.section,
    'aria-label': `${row.label}: open detail`,
    onclick: () => row.onPick(),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.onPick(); } },
  }, cells);
}

// The last-quarter bars: holder groups as net purchases in $bn, buyers up, sellers down.
function holderChart(node, bars) {
  render(node, (option, p) => ({
    ...option,
    grid: { left: 8, right: 64, top: 8, bottom: 24, containLabel: true },
    xAxis: {
      type: 'value', axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => bnText(v) },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    yAxis: {
      type: 'category', inverse: true, data: bars.map((b) => b.label),
      axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10 },
    },
    tooltip: { ...option.tooltip, trigger: 'item', valueFormatter: (x) => bnText(x) },
    series: [{
      type: 'bar', barMaxWidth: 14,
      data: bars.map((b) => b.value),
      itemStyle: { color: (q) => (q.value >= 0 ? p.up : p.down) },
      label: { show: true, position: 'right', color: p.dim, fontSize: 10, formatter: (q) => bnText(q.value) },
    }],
  }));
}

export default function renderFlows(root, data) {
  if (!data || data.unavailable) throw new Error(data?.unavailable || 'flows artifact missing');
  root.append(metaRow(`FLOWS · EQUITY DEMAND & POSITIONING · AS OF ${data.as_of}`, [
    'Sources have different reporting dates and scopes. Company repurchases, sector transactions and fund exposure snapshots should not be summed.',
  ]));

  const dp = data.demand_pipeline && !data.demand_pipeline.unavailable ? data.demand_pipeline : null;
  const rows = scorecardRows({
    asOf: data.as_of,
    etf: data.etf,
    cot: data.cot,
    z1: data.z1,
    buybacks: dp?.buybacks,
    hfLeverage: data.hf_leverage,
  });

  let active = savedDetail() || 'demand';
  const scoreRows = rows.map((row) => scoreRow({ ...row, onPick: () => choose(row.section) }));
  const scorecard = scoreRows.length
    ? table(['PARTICIPANT', 'LATEST', 'BUY/SELL', 'VS OWN HISTORY', 'TREND', 'AS OF', 'FREQUENCY'], scoreRows, { class: 'flows-score' })
    : gap('No participant data in this build.');
  root.append(card('WHO\'S BUYING STOCKS', null, [
    el('div', { class: 'field-note', text: 'Latest reading for each participant, fastest-moving first. Each row keeps its own as-of date: daily ETF flows, weekly futures, quarterly Z.1 and filings. Click a row to open its detail below.' }),
    el('div', { class: 'flows-score-wrap' }, [scorecard]),
  ]));

  const bars = holderBars(data.z1);
  if (bars) {
    const node = el('div', { class: 'chart flows-holder-chart', 'aria-label': `Net purchases of US corporate equities by holder, ${bars.quarter}` });
    requestAnimationFrame(() => holderChart(node, bars.bars));
    root.append(card(`LAST QUARTER · WHO BOUGHT, WHO SOLD · ${bars.quarter}`, null, [
      el('div', { class: 'field-note', text: 'Z.1 net purchases of US corporate equities by holder, $bn in the quarter. Buyers above zero, sellers below.' }),
      node,
    ]));
  }

  const switcher = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Flows sections' });
  const content = el('div', {});
  function addSection(part, build) {
    if (!part || part.unavailable) { content.append(gap('Not available' + (part?.unavailable ? ': ' + part.unavailable : '.'))); return; }
    for (const node of build(part)) if (node) content.append(node);
  }
  function draw() {
    for (const button of switcher.children) button.setAttribute('aria-pressed', String(button.dataset.tab === active));
    for (const tr of scoreRows) tr.classList.toggle('is-selected', tr.dataset.section === active);
    content.replaceChildren();
    if (active === 'demand') {
      const views = investorDemandView(dp);
      if (views.length) content.append(...views);
      else addSection(data.z1, z1Section);
    } else if (active === 'buybacks') {
      const node = dp && demandPipelineSection(dp, {tab: 'buybacks', only: 'buybacks'});
      content.append(node || gap('Buyback history has not been built for this session.'));
    } else if (active === 'hedge') {
      addSection(data.hf_leverage, leverageSection);
      const node = dp && demandPipelineSection(dp, {tab: 'hf', only: 'hf'});
      if (node) content.append(node);
      addSection(data.hf_13f, crowdingSection);
    } else if (active === 'futures') addSection(data.cot, cotSection);
    else addSection(data.etf, etfSection);
  }
  function choose(key) {
    active = key;
    saveDetail(key);
    draw();
  }
  for (const [key, title] of TABS) {
    const button = el('button', {type: 'button', text: title, onclick: () => choose(key)});
    button.dataset.tab = key;
    switcher.append(button);
  }
  root.append(
    el('div', { class: 'flows-detail-nav' }, [el('span', { class: 'flows-detail-label', text: 'DETAIL' }), switcher]),
    content,
  );
  draw();
}
