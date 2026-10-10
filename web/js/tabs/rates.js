// RATES & MACRO: the Treasury curve and the macro prints on one page. Each
// half is its own panel with its own artifact; this view only stacks them, so
// a failure in one leaves the other readable.

import { el, card } from '../fmt.js';
import renderFixedIncome from './fixed-income.js';
import renderMacro from './macro.js';
import { tileNode, historyChart } from './risk.js';

// MOVE under the Treasury table: how much the market expects those yields to
// move. It is RISK's own tile (read after the page is up; RISK is the larger
// artifact), so the value, percentiles and line agree with that page.
function moveCard(risk) {
  const tile = (risk?.sections || []).flatMap((s) => s.tiles || []).find((t) => t.key === 'move');
  if (!tile) return null;
  const chart = el('div', { class: 'chart' });
  requestAnimationFrame(() => historyChart(chart, tile));
  return card('TREASURY VOLATILITY — MOVE', el('a', { href: '#risk', class: 'dim', text: 'risk ↗' }), [
    el('div', { class: 'move-card' }, [tileNode(tile, { asOf: risk.as_of }), chart]),
    el('div', { class: 'note-text', text: 'ICE BofA MOVE as Yahoo serves it: the implied volatility of one-month Treasury options '
      + '(2, 5, 10 and 30-year), in basis points of yield a year. Weekly closes over ten years; the dashed line is the level RISK flags.' }),
  ]);
}

export default async function renderRates(root, [fixedIncome, macro], _manifest, ctx = {}) {
  for (const [label, render, data] of [['FIXED INCOME', renderFixedIncome, fixedIncome], ['MACRO', renderMacro, macro]]) {
    const host = el('div', {});
    root.append(host);
    try {
      if (data?.unavailable) throw new Error(data.unavailable);
      await render(host, data);
    } catch (error) {
      host.replaceChildren(el('div', { class: 'gap', text: `${label} is unavailable: ${error.message}.` }));
    }
  }
  const risk = await ctx.loadArtifact?.('risk').catch(() => null);
  const node = moveCard(risk);
  const yields = [...root.querySelectorAll('.card')].find((c) => c.querySelector('.card-title')?.textContent.startsWith('TREASURY YIELDS'));
  if (node && yields) yields.after(node);
}
