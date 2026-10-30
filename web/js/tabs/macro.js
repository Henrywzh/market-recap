import { el, card, table, num, pct, dirClass, sectionTitle, DASH } from '../fmt.js';
import { timeLines } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { createManualFeed } from '../live-feed.js';
import renderCpi from './cpi.js';
import { macroRegimeCard, macroSnapshot, upcomingMacro } from '../macro-regime.js';

const HEAT_WARM = [185, 28, 28];
const HEAT_COOL = [30, 64, 175];
// Never fully transparent (a real reading must be visibly a reading) and never
// fully opaque (the text on top has to stay readable).
const HEAT_MIN_ALPHA = 0.15;
const HEAT_ALPHA_RANGE = 0.6;

const MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

// The inflation grid is a heat table: colour encodes each metric's own range
// so a 4% headline print and a 0.5% MoM spending print are each shaded against
// their own history rather than against one another.
function heatColor(value, low, high) {
  if (value === null || value === undefined) return 'transparent';
  if (high === low) return 'transparent';
  const t = (value - low) / (high - low);
  const strength = Math.abs(t - 0.5) * 2;
  const warm = t >= 0.5;
  const base = warm ? HEAT_WARM : HEAT_COOL;
  return `rgba(${base.join(',')},${(HEAT_MIN_ALPHA + strength * HEAT_ALPHA_RANGE).toFixed(2)})`;
}

// A table whose rows pick what one chart beside it shows, with its own range
// switch. `rows` carry { label, history: {dates, values} }; `line` turns the
// picked row into the chart's line and marks.
function pickedChart(rows, { title, preferred = '1Y', line, marks = () => [], value }) {
  const node = el('div', { class: 'chart' });
  const head = el('span', { class: 'dim' });
  const switchHost = el('span');
  let picked = rows.find((r) => r.history?.dates?.length) || null;
  let range = picked ? initialRange(picked.history.dates, preferred) : 'MAX';
  const draw = () => {
    if (!picked) return;
    const cut = sliceRange(picked.history.dates, { values: picked.history.values }, range);
    head.textContent = `${picked.label} · click a row to plot it`;
    timeLines(node, [{ name: picked.label, dates: cut.dates, values: cut.values, ...line(picked) }], { value, markY: marks(picked) });
    switchHost.replaceChildren(rangeSwitch(picked.history.dates, range, (label) => { range = label; draw(); }));
  };
  const pick = (row, tr) => {
    if (!row.history?.dates?.length) return;
    picked = row;
    range = initialRange(row.history.dates, range);
    tr.parentNode.querySelectorAll('tr.picked').forEach((x) => x.classList.remove('picked'));
    tr.classList.add('picked');
    draw();
  };
  const cardNode = card(title, switchHost, [el('div', { class: 'chart-head' }, [head]), node]);
  requestAnimationFrame(draw);
  return { card: cardNode, pick, isPicked: (row) => row === picked };
}

// COMMODITIES: their own view beside CPI & macro -- prices, not prints.
export function renderCommodities(root, data) {
  root.append(sectionTitle('COMMODITIES', '· ENERGY, METALS, AGRICULTURE'));
  const cols = data.commodities.periods;
  const commodityChart = pickedChart(data.commodities.rows, {
    title: 'PRICE HISTORY',
    line: () => ({ width: 1.4 }),
    value: (v) => num(v, 2),
  });
  const pickable = (row, cells) => {
    const tr = el('tr', { class: `pickable${commodityChart.isPicked(row) ? ' picked' : ''}` }, cells);
    tr.addEventListener('click', () => commodityChart.pick(row, tr));
    return tr;
  };
  // PRICE and 1D take live values once the reader presses REFRESH; the longer
  // windows stay on the build's closes.
  let live = null;
  const liveOf = (row) => {
    const q = live?.get(row.symbol);
    return q && typeof q.price === 'number' ? q : null;
  };
  const buildRows = () => data.commodities.rows.map((row) => {
    if (row.status !== 'ok') {
      return el('tr', {}, [
        el('td', {}, [el('span', { text: row.label }), el('span', { class: 'sub', text: row.symbol })]),
        el('td', { class: 'dim', text: 'unavailable' }),
        ...cols.map(() => el('td', { class: 'dim', text: DASH })),
      ]);
    }
    const q = liveOf(row);
    const failed = live && !q ? live.get(row.symbol)?.error || 'no live price' : null;
    return pickable(row, [
      el('td', {}, [el('span', { text: row.label }), el('span', { class: 'sub', text: row.symbol })]),
      q ? el('td', { class: 'live-cell', title: `close ${num(row.price)}`, text: num(q.price) })
        : el('td', { title: failed || '', text: num(row.price) }),
      ...cols.map((c) => (c === '1D' && q
        ? el('td', { class: `live-cell ${dirClass(q.change_pct)}`, title: `close-to-close ${pct(row[c])}`, text: pct(q.change_pct) })
        : el('td', { class: dirClass(row[c]), text: pct(row[c]) }))),
    ]);
  });
  const tableHost = el('div');
  const liveNote = el('div', { class: 'note-text' });
  const drawTable = () => {
    tableHost.replaceChildren(table(['ASSET', live ? 'PRICE · LIVE' : 'PRICE', ...cols.map((c) => (live && c === '1D' ? '1D · LIVE' : c))], buildRows()));
  };
  const feed = createManualFeed(['api/quotes?board=macro'], {
    onData: ([body]) => {
      live = new Map(body.quotes.map((q) => [q.symbol, q]));
      liveNote.textContent = 'PRICE and 1D: Yahoo, unofficial, a few minutes old, against the previous close or settlement; '
        + '1W and longer are the build\'s closes. Futures trade nearly around the clock, so 1D moves outside US hours too.';
      drawTable();
    },
  });
  drawTable();
  root.append(el('div', { class: 'grid two' }, [
    card('COMMODITIES', el('div', { class: 'live-controls' }, [el('span', { class: 'dim', text: `close ${data.as_of || DASH} · click a row to plot it` }), feed.controls]),
      [tableHost, liveNote]),
    commodityChart.card,
  ]));
}

export default async function renderMacro(root, data, ctx = {}) {
  root.append(sectionTitle('MACRO'));
  const [overview, catalysts, priced] = await Promise.all(['overview', 'catalysts', 'priced'].map((key) => ctx.loadArtifact?.(key).catch(() => null) || null));
  root.append(macroSnapshot(overview, data.regime, data.regime_gdp, priced, data.regime_nowcast?.gdpnow),
    el('div', { class: 'grid two' }, [macroRegimeCard(data.regime, data.regime_nowcast), upcomingMacro(catalysts)]));
  renderCpi(root, data.cpi);

  const inflation = data.inflation;
  const header = ['METRIC', 'UNIT', ...inflation.months.map((m) => {
    const [year, month] = m.split('-');
    return `${MONTH_NAMES[Number(month) - 1]} ${year}`;
  })];

  // Inflation rates carry the Fed's 2% line; income and spending growth do not.
  const isRate = (row) => /yoy|ann/i.test(row.unit || '');
  const inflationChart = pickedChart(inflation.rows, {
    title: 'INFLATION OVER TIME',
    preferred: '5Y',
    line: () => ({ width: 1.4 }),
    marks: (row) => (isRate(row) ? [{ y: 2, label: 'Fed 2%' }] : [{ y: 0 }]),
    value: (v, line) => `${num(v, 2)}${(inflation.rows.find((r) => r.label === line.name)?.unit || '').includes('%') ? '%' : ''}`,
  });
  const inflationRows = inflation.rows.map((row) => {
    if (row.status !== 'ok' || !row.values.length) {
      return el('tr', {}, [
        el('td', { text: row.label }),
        el('td', { class: 'dim', text: row.unit }),
        el('td', { class: 'dim', colspan: String(inflation.months.length), text: 'series unavailable in this build' }),
      ]);
    }
    const valid = row.values.filter((v) => v !== null);
    const low = Math.min(...valid);
    const high = Math.max(...valid);
    const tr = el('tr', { class: `pickable${inflationChart.isPicked(row) ? ' picked' : ''}` }, [
      el('td', { text: row.label }),
      el('td', { class: 'dim', text: row.unit }),
      ...row.values.map((v) => el('td', {
        text: v === null ? DASH : num(v, 2),
        style: `background:${heatColor(v, low, high)}`,
      })),
    ]);
    tr.addEventListener('click', () => inflationChart.pick(row, tr));
    return tr;
  });

  root.append(card(`PCE, INCOME & SPENDING — LAST ${data.inflation.releases ?? data.inflation.months.length} MONTHLY RELEASES`, el('span', { class: 'dim', text: 'click a row to plot it' }), [
    table(header, inflationRows),
  ]));
  root.append(inflationChart.card);
  root.append(el('div', { class: 'note-text', text: data.note }));
}
