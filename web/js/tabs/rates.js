// RATES & MACRO: the Treasury curve and the macro prints on one page. Each
// half is its own panel with its own artifact; this view only stacks them, so
// a failure in one leaves the other readable.

import { el } from '../fmt.js';
import renderFixedIncome from './fixed-income.js';
import renderMacro from './macro.js';

export default async function renderRates(root, [fixedIncome, macro]) {
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
}
