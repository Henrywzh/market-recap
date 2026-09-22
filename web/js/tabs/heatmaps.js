import { el, card, num, pct, money, aum, dirClass, periodSwitch, sectionTitle, notice, DASH } from '../fmt.js';
import { drawTreemap, returnColor } from '../treemap.js';
import { render, multiLine } from '../charts.js';

const ETF_BASE = '../artifacts/etfs';
const tooltip = () => document.getElementById('tooltip');

function showTooltip(html, event) {
  const node = tooltip();
  node.innerHTML = html;
  node.style.display = 'block';
  const pad = 14;
  const rect = node.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + rect.width > window.innerWidth) x = event.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight) y = event.clientY - rect.height - pad;
  node.style.left = `${Math.max(4, x)}px`;
  node.style.top = `${Math.max(4, y)}px`;
}
const hideTooltip = () => { tooltip().style.display = 'none'; };

function rowsHtml(values, periods, fmt) {
  return periods.map((p) => {
    const v = values[p];
    const cls = v === null || v === undefined ? 'flat' : v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    return `<tr><td>${p}</td><td class="${cls}">${v === null || v === undefined ? DASH : fmt(v)}</td></tr>`;
  }).join('');
}

export default function renderHeatmaps(root, data) {
  const periods = data.periods;

  // ---------------- S&P 500 by official weight --------------------------
  root.append(sectionTitle('S&P 500 HEAT MAP', 'SIZED BY OFFICIAL SPY WEIGHT · COLOURED BY RETURN'));
  const stockNode = el('div', { class: 'treemap' });
  let stockPeriod = '1D';

  const drawStocks = (period) => {
    stockPeriod = period;
    const bySector = new Map();
    data.constituents.forEach((row) => {
      const ret = row.returns[period];
      if (!bySector.has(row.sector)) bySector.set(row.sector, []);
      bySector.get(row.sector).push({
        key: row.ticker,
        value: row.weight || 0,
        color: returnColor(ret, period === '1D' ? 3 : 12),
        label: row.ticker,
        sublabel: ret === null || ret === undefined ? DASH : pct(ret),
        payload: row,
      });
    });
    drawTreemap(stockNode, [...bySector.entries()].map(([group, items]) => ({ group, items })),
      (row, event) => showTooltip(
        `<div class="t-head">${row.ticker} <span class="${dirClass(row.returns[period])}">${pct(row.returns[period])}</span></div>
         <div class="t-meta">${row.name}<br>${row.sector} · ${row.sub_sector}<br>weight ${num(row.weight, 2)}% · $${num(row.price)}</div>
         <table>${rowsHtml(row.returns, periods, (v) => pct(v))}</table>`, event),
      hideTooltip);
  };

  root.append(card(`S&P 500 CONSTITUENTS (${data.constituents.length} NAMES)`,
    periodSwitch(periods, '1D', drawStocks), stockNode));

  // ---------------- US ETFs by published net flow -----------------------
  root.append(sectionTitle('US ETF HEAT MAP', 'SIZED BY AUM · COLOURED BY PUBLISHED NET FLOW'));
  const etfNode = el('div', { class: 'treemap', style: 'height:440px' });
  const withFlow = data.etfs.filter((e) => e.flow_status === 'published');
  let etfPeriod = '1D';

  const drawEtfs = (period) => {
    etfPeriod = period;
    const magnitudes = withFlow
      .map((e) => Math.abs(e.flows[period] ?? 0))
      .filter(Boolean)
      .sort((a, b) => a - b);
    // Scale colour to the 80th percentile rather than the maximum. SPY moves
    // billions on a day when a sector fund moves tens of millions, so scaling
    // to SPY would leave every other tile the same neutral grey.
    const cap = magnitudes.length
      ? magnitudes[Math.floor(magnitudes.length * 0.8)] || magnitudes[magnitudes.length - 1]
      : 1;

    const byGroup = new Map();
    data.etfs.forEach((row) => {
      if (!byGroup.has(row.group)) byGroup.set(row.group, []);
      const flow = row.flow_status === 'published' ? row.flows[period] : null;
      byGroup.get(row.group).push({
        key: row.ticker,
        value: row.aum || 0,
        color: flow === null || flow === undefined ? '#2b2b2b' : returnColor((flow / cap) * 3, 3),
        label: row.ticker,
        sublabel: flow === null || flow === undefined ? DASH : money(flow),
        payload: row,
      });
    });

    drawTreemap(etfNode, [...byGroup.entries()].map(([group, items]) => ({ group, items })),
      (row, event) => {
        const flow = row.flow_status === 'published' ? row.flows[period] : null;
        const head = flow === null || flow === undefined
          ? `<div class="t-head">${row.ticker}</div>`
          : `<div class="t-head">${row.ticker} <span class="${dirClass(flow)}">${money(flow)}</span></div>`;
        const meta = row.flow_status === 'published'
          ? `AUM ${aum(row.aum)} · NAV ${num(row.nav)} · premium ${num(row.premium_pct, 4)}%<br>published since ${row.history_start}`
          : 'issuer publishes no NAV history for this fund';
        showTooltip(
          `${head}<div class="t-meta">${row.group}<br>${meta}</div>`
          + (row.flow_status === 'published'
            ? `<table>${rowsHtml(row.flows, periods, (v) => money(v))}</table>`
            : ''),
          event);
      }, hideTooltip);
  };

  const coverage = data.flow_coverage;
  const etfBody = [etfNode, el('div', { class: 'note-text', text: data.note })];
  if (coverage.unpublished.length) {
    const bySource = Object.entries(data.flow_sources || {})
      .map(([id, list]) => `${list.length} from ${id.replace('_nav_history', '')}`)
      .join(', ');
    etfBody.unshift(notice(
      `${coverage.published.length} funds carry a published net-flow series (${bySource}). `
      + `${coverage.unpublished.length} have no issuer NAV history located, so they are sized by reported `
      + 'total assets and left uncoloured rather than filled with an estimate: '
      + `${coverage.unpublished.join(', ')}.`,
    ));
  }
  root.append(card('US ETFs — PUBLISHED NET FLOW',
    periodSwitch(periods, '1D', drawEtfs), etfBody));

  // ---------------- Single ETF: price, flow and premium -----------------
  root.append(sectionTitle('ETF PRICE & PUBLISHED FLOWS'));
  const status = el('span', { class: 'field-note', text: '' });
  const priceNode = el('div', { class: 'chart' });
  const flowNode = el('div', { class: 'chart short' });
  const premiumNode = el('div', { class: 'chart short' });
  const select = el('select', { id: 'etf-pick' }, coverage.published.map((t) => el('option', { value: t, text: t })));

  async function loadEtf() {
    const ticker = select.value;
    status.textContent = `Loading ${ticker}…`;
    try {
      const response = await fetch(`${ETF_BASE}/${ticker}.json`, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`${ticker} has no flow artifact in this build`);
      const payload = await response.json();

      const series = { [`${ticker} Close`]: payload.close };
      Object.entries(payload.moving_averages || {}).forEach(([w, values]) => {
        series[`${w}-day SMA`] = values;
      });
      multiLine(priceNode, payload.dates, series);

      render(flowNode, (option, p) => ({
        ...option,
        grid: { ...option.grid, top: 10, bottom: 24 },
        xAxis: { ...option.xAxis, data: payload.dates, boundaryGap: true },
        tooltip: { ...option.tooltip, valueFormatter: (v) => (v === null ? DASH : `$${num(v / 1e6, 0)}M`) },
        yAxis: {
          ...option.yAxis,
          axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${(v / 1e9).toFixed(1)}B` },
        },
        series: [{
          type: 'bar',
          barMaxWidth: 4,
          data: payload.flow.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? p.up : p.down } })),
        }],
      }));

      if ((payload.premium_pct || []).some((v) => v !== null)) {
        render(premiumNode, (option, p) => ({
          ...option,
          grid: { ...option.grid, top: 10, bottom: 24 },
          xAxis: { ...option.xAxis, data: payload.dates },
          yAxis: {
            ...option.yAxis,
            axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v.toFixed(2)}%` },
          },
          series: [{
            type: 'line',
            data: payload.premium_pct,
            showSymbol: false,
            lineStyle: { width: 1, color: p.accent },
            markLine: {
              silent: true, symbol: 'none', data: [{ yAxis: 0 }],
              lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false },
            },
          }],
        }));
      } else {
        // An empty chart frame reads as "premium is zero". Say why it is absent.
        premiumNode.innerHTML = '';
        premiumNode.append(el('div', { class: 'note-text' }, [
          `${payload.source} does not publish a premium/discount series for this fund, `,
          'so there is nothing to plot here. State Street funds carry one.',
        ]));
      }

      status.textContent = `${ticker}: ${payload.sessions} published sessions since ${payload.history_start}.`;
    } catch (error) {
      status.textContent = error.message;
    }
  }
  select.addEventListener('change', loadEtf);

  root.append(card('PRICE / MOVING AVERAGES + DAILY NET FLOW — SHARED TIMELINE', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'US ETF' }), select]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadEtf }),
      status,
    ]),
    el('div', { class: 'card-title', text: 'PRICE & 20/50/200-DAY MOVING AVERAGES' }),
    priceNode,
    el('div', { class: 'card-title', text: 'DAILY NET FLOW — GREEN INFLOW / RED OUTFLOW' }),
    flowNode,
    el('div', { class: 'card-title', text: 'PREMIUM / DISCOUNT TO NAV (%)' }),
    premiumNode,
    el('div', { class: 'note-text' }, [
      'Net flow is the day-over-day change in the fund’s published shares outstanding valued at that ',
      'day’s NAV. Creations and redemptions settle in units, so this is a measured series from the ',
      'issuer’s own file rather than a market-cap estimate — a fund whose price fell has not had an outflow.',
    ]),
  ]));

  drawStocks('1D');
  drawEtfs('1D');
  loadEtf();

  // Treemaps are laid out in pixels, so they need an explicit relayout when
  // the pane is resized or first becomes visible with a non-zero width.
  const relayout = () => { drawStocks(stockPeriod); drawEtfs(etfPeriod); };
  window.addEventListener('resize', relayout);
}
