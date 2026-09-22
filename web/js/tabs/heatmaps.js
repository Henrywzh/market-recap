import { el, card, num, pct, money, aum, dirClass, periodSwitch, sectionTitle, DASH } from '../fmt.js';
import { drawTreemap, returnColor } from '../treemap.js';

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

function hideTooltip() {
  tooltip().style.display = 'none';
}

function returnsRows(returns, periods) {
  return periods.map((p) => {
    const v = returns[p];
    const cls = v === null || v === undefined ? 'flat' : v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    return `<tr><td>${p}</td><td class="${cls}">${v === null || v === undefined ? DASH : pct(v)}</td></tr>`;
  }).join('');
}

export default function renderHeatmaps(root, data) {
  const periods = data.periods;

  // --- S&P 500 by official weight ---------------------------------------
  root.append(sectionTitle('S&P 500 HEAT MAP', 'SIZED BY OFFICIAL SPY WEIGHT · COLOURED BY RETURN'));
  const stockNode = el('div', { class: 'treemap' });

  const drawStocks = (period) => {
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
    const groups = [...bySector.entries()].map(([group, items]) => ({ group, items }));
    drawTreemap(stockNode, groups, (row, event) => {
      showTooltip(
        `<div class="t-head">${row.ticker} <span class="${dirClass(row.returns[period])}">${pct(row.returns[period])}</span></div>
         <div class="t-meta">${row.name}<br>${row.sector} · ${row.sub_sector}<br>weight ${num(row.weight, 2)}% · $${num(row.price)}</div>
         <table>${returnsRows(row.returns, periods)}</table>`,
        event,
      );
    }, hideTooltip);
  };

  root.append(card(
    `S&P 500 CONSTITUENTS (${data.constituents.length} NAMES)`,
    periodSwitch(periods, '1D', drawStocks),
    stockNode,
  ));

  // --- US ETFs by AUM, coloured by estimated flow ------------------------
  root.append(sectionTitle('US ETF HEAT MAP', 'SIZED BY AUM · COLOURED BY ESTIMATED NET FLOW'));
  const etfNode = el('div', { class: 'treemap', style: 'height:420px' });

  const flows = data.etfs.map((e) => e.estimated_flow).filter((v) => v !== null && v !== undefined);
  const cap = flows.length ? Math.max(...flows.map(Math.abs)) : 1;
  const anyFlow = flows.length > 0;

  const drawEtfs = () => {
    const byGroup = new Map();
    data.etfs.forEach((row) => {
      if (!byGroup.has(row.group)) byGroup.set(row.group, []);
      byGroup.get(row.group).push({
        key: row.ticker,
        value: row.aum || 0,
        color: anyFlow ? returnColor(row.estimated_flow === null ? null : (row.estimated_flow / cap) * 3, 3) : '#2b2b2b',
        label: row.ticker,
        sublabel: row.estimated_flow === null ? DASH : money(row.estimated_flow),
        payload: row,
      });
    });
    const groups = [...byGroup.entries()].map(([group, items]) => ({ group, items }));
    drawTreemap(etfNode, groups, (row, event) => {
      showTooltip(
        `<div class="t-head">${row.ticker} ${row.estimated_flow === null ? '' : `<span class="${dirClass(row.estimated_flow)}">${money(row.estimated_flow)}</span>`}</div>
         <div class="t-meta">${row.name}<br>${row.group} · AUM ${aum(row.aum)} · $${num(row.price)}<br>flow: ${row.flow_status}</div>
         <table>${returnsRows(row.returns || {}, periods)}</table>`,
        event,
      );
    }, hideTooltip);
  };

  const body = [etfNode, el('div', { class: 'note-text', text: data.note })];
  if (!anyFlow) {
    // Never colour a map by a number that does not exist yet.
    body.unshift(el('div', { class: 'notice' }, [
      'No flow estimates yet: net flow is the day-over-day change in shares outstanding, so the first ',
      `build only records a baseline. Sampling started ${data.flow_sampling_started}; tiles are sized by AUM and left uncoloured until a second session is recorded.`,
    ]));
  }
  root.append(card('US ETFs — EST. NET FLOW ($M)', null, body));

  drawStocks('1D');
  drawEtfs();

  // Treemaps are laid out in pixels, so they need an explicit relayout.
  const relayout = () => { drawStocks(document.querySelector('.period-switch button[aria-pressed="true"]')?.textContent || '1D'); drawEtfs(); };
  window.addEventListener('resize', relayout, { once: false });
}
