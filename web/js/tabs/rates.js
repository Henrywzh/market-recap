// RATES & MACRO: the Treasury curve and the macro prints on one page. Each
// half is its own panel with its own artifact; this view only stacks them, so
// a failure in one leaves the other readable.

import { el, card } from '../fmt.js';
import renderFixedIncome from './fixed-income.js';
import renderMacro, { renderCommodities } from './macro.js';
import renderPpi from './ppi.js';
import { tileNode, historyChart } from './risk.js';
import { resizeAll } from '../charts.js';

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
  // Treasury rates opens first: it is the page's standing view; the macro prints are one click away.
  const choices = [['yields', 'Treasury rates', renderFixedIncome, fixedIncome], ['macro', 'CPI & macro', renderMacro, macro], ['commodities', 'Commodities', renderCommodities, macro], ['ppi', 'PPI · AI prices', renderPpi, macro?.ppi]];
  const nav = el('div', { class: 'view-switch', role: 'tablist', 'aria-label': 'Rates and macro views' });
  const panes = new Map(choices.map(([key]) => [key, el('div', { role: 'tabpanel',
    id: `rates-view-${key}`, 'aria-labelledby': `rates-tab-${key}`, hidden: key !== 'yields' ? '' : null })]));
  const ready = new Set();
  const select = async (key) => {
    for (const [id] of choices) {
      const button = nav.querySelector(`#rates-tab-${id}`);
      button.setAttribute('aria-selected', String(id === key));
      button.tabIndex = id === key ? 0 : -1;
      panes.get(id).hidden = id !== key;
    }
    const host = panes.get(key);
    if (!ready.has(key)) {
      ready.add(key);
      const [, label, draw, data] = choices.find(([id]) => id === key);
      try {
        if ((!data && key !== 'ppi') || data?.unavailable) throw new Error(data?.unavailable || 'artifact missing');
        await draw(host, data, ctx);
        if (key === 'yields') {
          const risk = await ctx.loadArtifact?.('risk').catch(() => null);
          if (!host.isConnected) return;
          const node = moveCard(risk);
          const yields = [...host.querySelectorAll('.card')].find((c) => c.querySelector('.card-title')?.textContent.startsWith('TREASURY YIELDS'));
          if (node && yields) yields.after(node);
        }
      } catch (error) {
        host.replaceChildren(el('div', { class: 'gap', text: `${label} is unavailable: ${error.message}.` }));
      }
    }
    requestAnimationFrame(resizeAll);
  };
  choices.forEach(([key, label], index) => nav.append(el('button', {
    type: 'button', role: 'tab', id: `rates-tab-${key}`, text: label,
    'aria-controls': `rates-view-${key}`, 'aria-selected': String(index === 0), tabindex: index === 0 ? '0' : '-1',
    onclick: () => select(key), onkeydown: (event) => {
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = (index + (event.key === 'ArrowRight' ? 1 : -1) + choices.length) % choices.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = choices.length - 1;
      else return;
      event.preventDefault();
      nav.children[next].focus();
      select(choices[next][0]);
    },
  })));
  root.append(nav, ...panes.values());
  await select('yields');
}
