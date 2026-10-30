// TRADE DESK -> STRUCTURE: what is today for one ticker. Where it trades (an
// estimated volume-by-price profile), how unusual the move is in its own history,
// and the market backdrop; one button carries all of it to EVENT LAB, which holds
// the event study and the trade simulation.
import { el, num, pct, DASH, periodSwitch } from './fmt.js';
import { render } from './charts.js';
import { withSuggestions } from './ticker-suggest.js';
import { rangeStart } from './range.js';
import { chipView } from './chip-card.js';
import { dailyMoves, tailShare } from './trade-events.js';
import { returns as dailyReturns, sigmaOf } from './movecheck-model.js';
import { likeToday, readingText } from './trade-conditions.js';

const note = (text) => el('div', { class: 'wb-note', text });
const field = (label, node) => el('label', { class: 'wb-field' }, [el('span', { text: label }), node]);
const stat = (label, value, detail = '') => el('div', { class: 'wb-stat' }, [el('span', { text: label }), el('strong', { text: value, class: /^[−-]/.test(value) ? 'down' : /^\+/.test(value) ? 'up' : '' }), note(detail)]);
const pctText = (v) => Number.isFinite(v) ? pct(v, 2) : DASH;
// EVENT LAB's σ trigger for a move of `z`: at least this extreme, to 0.1σ, from 0.5σ.
export const labSigma = (z) => Math.max(0.5, Math.floor(Math.abs(z) * 10) / 10);

export default function workbench(root, technicals, ctx, { openLab } = {}) {
  root.className = `${root.className || ''} trade-workbench`.trim();
  const available = technicals.available || [];
  const picker = el('input', { value: ctx.arg || 'QQQ', 'aria-label': 'Workbench ticker' });
  const symbolInfo = el('div', { class: 'wb-symbol-info' });
  const identities = Object.fromEntries(available.map(ticker => [ticker, {
    type: technicals.etf_names?.[ticker] ? 'ETF' : '',
  }]));
  const names = { ...(technicals.names || {}), ...(technicals.etf_names || {}) };
  const suggested = withSuggestions(picker, available, names, () => load(), technicals.rank || [], identities);
  const symbolPicker = el('div', { class: 'wb-symbol-picker' }, [field('SYMBOL', suggested), symbolInfo]);
  const status = note('Loading…');
  const map = el('div', { class: 'wb-map', 'aria-label': 'Price volume structure map' });
  const readings = el('aside', { class: 'wb-readings' });
  let profileRange = '1Y';
  const profileNote = note('');
  const profileRanges = periodSwitch(['YTD', '1Y', '2Y', '5Y', 'MAX'], profileRange, (range) => {
    profileRange = range; update(); drawMap();
  });
  const mapTitle = el('h2', { text: 'Market structure' });
  // A move the reader types (today's intraday move, a level they are watching): read
  // against the last 20 completed sessions in place of the latest close-to-close move.
  const myMove = el('input', { type: 'number', step: '0.1', placeholder: 'e.g. −3.2', 'aria-label': 'Your move in percent' });
  const myMoveNote = note('Blank = the latest daily move. A typed move is read against the last 20 completed sessions.');
  myMove.addEventListener('change', () => update());
  myMove.addEventListener('keydown', (e) => { if (e.key === 'Enter') update(); });
  let conditions = null;
  const backdropList = el('div', { class: 'wb-backdrop-fields' }, [note('Loading market backdrop…')]);
  const labButton = el('button', { type: 'button', class: 'action wb-lab-button', text: 'STUDY THIS IN EVENT LAB →', disabled: true });
  const labNote = note('');
  let prices = null; let bars = null; let revision = 0; let moves = []; let preset = null;

  root.append(
    el('header', { class: 'wb-heading' }, [el('div', {}, [el('span', { class: 'wb-eyebrow', text: 'STRUCTURE' }), el('h1', { text: 'Where it trades, how unusual today is' }), note('Choose a stock. See where it trades, how rare its move is in its own history and the market backdrop; then study days like it in EVENT LAB.')]),
      symbolPicker]),
    status,
    el('section', { class: 'wb-structure' }, [el('div', { class: 'wb-map-panel' }, [mapTitle, el('div', { class: 'wb-profile-tools' }, [profileRanges, profileNote]), map]), readings]),
    el('div', { class: 'wb-config wb-today' }, [
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Your move' }), field('YOUR MOVE · %', myMove), myMoveNote]),
      el('div', { class: 'wb-config-block wb-backdrop' }, [el('h3', { text: 'Market backdrop today' }), backdropList]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'What followed days like this?' }), labButton, labNote]),
    ]),
    el('details', { class: 'method-fold' }, [el('summary', { text: 'Data limits' }), note('Moves are close-to-close total returns from the nightly build; σ divides a move by the standard deviation of the 20 completed sessions before it. Rarity = the share of sessions in the ticker\'s own history at least as far out in the same direction, including the latest. Volume structure is estimated from daily bars, smoothed for display; it does not measure investors’ holdings or predict support.')]),
    el('div', { class: 'wb-links' }, [el('a', { href: '#technicals', text: 'Advanced technicals →' }), el('a', { href: '#movecheck', text: 'Move Check →' })]),
  );

  labButton.addEventListener('click', () => { if (preset && openLab) openLab(preset); });

  function update() {
    if (!prices) return;
    const latest = moves.at(-1) || null;
    const typedMove = myMove.value !== '' && Number.isFinite(Number(myMove.value)) ? Number(myMove.value) : null;
    const typedZ = typedMove !== null ? sigmaOf([...dailyReturns(prices.dates, prices.close, 1), { ret: typedMove }], typedMove, 20, 1) : null;
    myMoveNote.textContent = typedMove === null ? 'Blank = the latest daily move. A typed move is read against the last 20 completed sessions.'
      : Number.isFinite(typedZ) ? `${pct(typedMove, 2)} = ${num(typedZ, 2)}σ of the last 20 sessions.` : 'Needs 20 sessions of history and a non-zero move.';
    const view = bars && profileView();
    // How rare the move is in this ticker's own history: share of sessions at least as far.
    const since = moves[0]?.date?.slice(0, 4) || DASH;
    const rarity = (values, x) => {
      const t = tailShare(values, x);
      if (!t) return '';
      const odds = t.hits ? ` (1 in ${num(t.n / t.hits, 0)})` : '';
      return ` · ${num(100 * t.share, 1)}% of sessions since ${since}${odds} ${x < 0 ? 'fell' : 'rose'} this far`;
    };
    const rets = moves.map((r) => r.ret); const zs = moves.map((r) => r.z);
    const shownMove = typedMove !== null ? typedMove : latest?.ret; const shownZ = typedMove !== null ? typedZ : latest?.z;
    readings.replaceChildren(el('span', { class: 'wb-eyebrow', text: 'SESSION SNAPSHOT' }),
      ...(typedMove !== null ? [
        stat('YOUR MOVE', pctText(typedMove), `typed · against the latest close history${rarity(rets, shownMove)}`),
        stat('OWN VOLATILITY', Number.isFinite(typedZ) ? `${num(typedZ, 2)}σ` : DASH, `last 20 completed sessions to ${latest?.date || DASH}${rarity(zs, shownZ)}`)] : [
        stat('LATEST DAILY MOVE', pctText(latest?.ret), `${latest?.date || ''} · total-return basis${rarity(rets, shownMove)}`),
        stat('OWN VOLATILITY', Number.isFinite(latest?.z) ? `${num(latest.z, 2)}σ` : DASH, `close → close · prior 20-session volatility${rarity(zs, shownZ)}`)]),
      stat('PRICE ACCEPTANCE', view?.area ? (view.close > view.area.high ? 'ABOVE VALUE' : view.close < view.area.low ? 'BELOW VALUE' : 'INSIDE VALUE') : DASH, `${profileRange} · 70% of estimated traded volume`),
      stat('MOST TRADED', view?.area ? num(view.area.poc, 2) : DASH, 'volume peak · not fair value'));
    // What the button hands to EVENT LAB: this move as a σ trigger. The backdrop starts
    // at ANY: all six of today's states at once leave too few events to read.
    const today = Object.keys(likeToday(conditions?.conditions)).length;
    if (Number.isFinite(shownZ) && shownZ !== 0) {
      const size = labSigma(shownZ);
      preset = { symbol: prices.ticker, trigger: { kind: 'sigma', dir: shownZ < 0 ? -1 : 1, size },
        source: `${prices.ticker} ${pctText(shownMove)} = ${num(shownZ, 2)}σ` };
      labButton.disabled = false;
      labNote.textContent = `Fills EVENT LAB with ${prices.ticker}, close move ${shownZ < 0 ? 'fall' : 'rise'} ≥ ${num(size, 1)}σ${Math.abs(shownZ) < 0.5 ? ' (floored at 0.5σ)' : ''}, over every backdrop${today ? `; LIKE TODAY there narrows it to today's ${today} conditions` : ''}. Every field stays editable.`;
    } else {
      preset = null; labButton.disabled = true;
      labNote.textContent = 'Needs a move with 20 sessions of history before it.';
    }
  }
  function drawBackdrop() {
    const list = conditions?.conditions || [];
    if (!list.length) { backdropList.replaceChildren(note('Market backdrop unavailable in this build.')); update(); return; }
    backdropList.replaceChildren(...list.map((c) => el('div', { class: 'wb-field', title: c.definition }, [el('span', { text: c.label }),
      el('strong', { class: 'wb-today-state', text: c.today || DASH }),
      el('small', { text: Number.isFinite(c.reading) ? readingText(c.key, c.reading) : '' })])));
    update();
  }
  function profileView() {
    if (!bars?.dates?.length) return null;
    const start = rangeStart(bars.dates, profileRange);
    return chipView(bars, { sessions: bars.dates.length - start, mode: 'volume' });
  }
  function drawMap() {
    const view = bars && profileView();
    if (!view?.area) { map.replaceChildren(note('Volume structure unavailable for this symbol.')); return; }
    profileNote.textContent = `${bars.dates[view.from]} → ${view.date} · ${view.last - view.from + 1} sessions available · estimated OHLCV`;
    // Weighted local smoothing of observed price-bin volume; no probability claim.
    const smooth = view.profile.map((_, i, a) => { let sum = 0; let w = 0; for (let k = -3; k <= 3; k++) if (i+k >= 0 && i+k < a.length) { const weight = 4-Math.abs(k); sum += a[i+k]*weight; w += weight; } return sum / w; });
    requestAnimationFrame(() => render(map, (o, p) => ({ ...o,
      grid: { left: 48, right: 26, top: 40, bottom: 44 },
      xAxis: { ...o.xAxis, type: 'value', min: view.g.min, max: view.g.max, name: '', axisLabel: { color: p.dim, formatter: (v) => num(v, 0), hideOverlap: true, showMinLabel: false, showMaxLabel: false } },
      yAxis: { ...o.yAxis, type: 'value', axisLabel: { show: false }, name: '' },
      tooltip: { ...o.tooltip, trigger: 'axis', confine: true,
        formatter: (params) => {
          const point = params.find((v) => Array.isArray(v.value));
          if (!point) return '';
          const volume = point.value[1];
          const compact = volume >= 1e9 ? `${num(volume / 1e9, 2)}B` : volume >= 1e6 ? `${num(volume / 1e6, 1)}M` : num(volume, 0);
          return `PRICE · $${num(point.value[0], 2)}<br/>EST. VOLUME / BIN · ${compact} shares`;
        } },
      series: [{ name: 'Smoothed volume by price', type: 'line', smooth: .35, showSymbol: false, data: view.g.centers.map((v, i) => [v, smooth[i]]), lineStyle: { color: p.accent, width: 3 }, areaStyle: { color: p.accent, opacity: .16 },
        markLine: { symbol: 'none', data: [{ xAxis: view.close, name: 'CURRENT', lineStyle: { color: p.text, type: 'dashed' } }, { xAxis: view.area.poc, name: 'VOLUME PEAK', lineStyle: { color: p.accent, type: 'dotted' } }], label: { formatter: (v) => `${v.name} ${num(v.value, 2)}`, color: p.dim } },
        markArea: { silent: true, itemStyle: { color: p.accent, opacity: .05 }, data: [[{ xAxis: view.area.low }, { xAxis: view.area.high }]] } }],
    })));
  }
  async function load() {
    const symbol = picker.value.trim().toUpperCase();
    if (!available.includes(symbol)) { status.textContent = `${symbol} has no prepared history in this build.`; return; }
    const run = ++revision; status.textContent = `Loading ${symbol}…`;
    try {
      const [next, candles] = await Promise.all([ctx.loadArtifact(`tickers/${symbol}`), ctx.loadArtifact(`bars/${symbol}`).catch(() => null)]);
      if (run !== revision) return;
      prices = next; bars = candles; ctx.setArg?.(symbol);
      moves = dailyMoves(prices.dates, prices.close, 20);
      showIdentity(symbol);
      mapTitle.textContent = `${symbol} · Market structure`;
      status.textContent = `AS OF ${next.as_of || next.dates.at(-1)} · USD prices · historical estimates`;
      [...root.querySelectorAll('.wb-links a')].forEach((a, i) => { a.href = `#${i ? 'movecheck' : 'technicals'}/${symbol}`; });
      update();
      drawMap();
    } catch (e) { if (run === revision) status.textContent = `Unable to load ${symbol}: ${e.message}`; }
  }
  function showIdentity(symbol) {
    symbolInfo.replaceChildren(el('span', { class: 'wb-asset-type', text: identities[symbol]?.type || 'TYPE UNAVAILABLE' }),
      el('span', { text: names[symbol] || 'Name unavailable in this build' }));
  }
  picker.addEventListener('change', load);
  picker.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  Promise.all(['valuation', 'heatmaps'].map(key => ctx.loadArtifact(key).catch(() => null))).then(([valuation, heatmaps]) => {
    for (const row of [...(heatmaps?.constituents || []), ...(valuation?.rows || [])]) {
      if (identities[row.ticker]) { names[row.ticker] = row.name || names[row.ticker] || ''; identities[row.ticker].type = 'STOCK'; }
    }
    for (const row of heatmaps?.etfs || []) {
      const ticker = row.ticker || row.symbol;
      if (identities[ticker]) { names[ticker] = technicals.etf_names?.[ticker] || row.name || row.label || names[ticker] || ''; identities[ticker].type = 'ETF'; }
    }
    showIdentity(prices?.ticker || picker.value.trim().toUpperCase());

  });
  ctx.loadArtifact('trade_conditions').then((data) => { conditions = data; drawBackdrop(); }).catch(() => drawBackdrop());
  load();
}
