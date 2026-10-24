import { el, card, table, num, DASH } from './fmt.js';
import { resolveTicker } from './routes.js';
import { finite, COMPARISON_BASES, comparisonBasisNote, comparisonEvidence, suggestPeer } from './valuation-compare-math.js';

const LABELS = { supports: 'SUPPORTING FACT', counterpoint: 'COUNTERPOINT', context: 'CONTEXT ONLY',
  similar: 'SIMILAR', unknown: 'NOT ESTABLISHED' };

// `fold`: start inside a closed fold (open when `open`), so the card does not
// push the page's own content down until it is asked for.
export function comparisonCard(data, { selectedTicker = null, idPrefix = 'valuation-compare', fold = false, open = false } = {}) {
  const rows = data?.rows || [];
  if (!rows.length) return null;
  const universe = new Map(rows.map((r) => [r.ticker, r]));
  const requested = resolveTicker(selectedTicker, (t) => universe.has(t));
  const first = universe.get(requested) || [...rows].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))[0];
  const second = suggestPeer(rows, first);
  const listId = `${idPrefix}-names`;
  const aInput = el('input', { id: `${idPrefix}-a`, list: listId, value: first.ticker,
    'aria-label': 'Compare company A', placeholder: 'Ticker A', size: 10 });
  const bInput = el('input', { id: `${idPrefix}-b`, list: listId, value: second?.ticker || '',
    'aria-label': 'Compare company B', placeholder: 'Ticker B', size: 10 });
  const basis = el('select', { id: `${idPrefix}-basis`, 'aria-label': 'Comparison valuation measure' },
    COMPARISON_BASES.map(([key, label]) => el('option', { value: key, text: label })));
  basis.value = 'pe_forward';
  const status = el('p', { class: 'compare-status note-text', role: 'status' });
  const host = el('div', { class: 'compare-output', 'aria-live': 'polite' });
  const resolve = (input) => universe.get(resolveTicker(input.value.trim().toUpperCase(), (t) => universe.has(t)));
  const draw = () => {
    host.replaceChildren();
    const a = resolve(aInput), b = resolve(bInput);
    if (!a || !b) {
      status.textContent = 'Choose two covered tickers. Unknown or blank names are not replaced with another company.';
      return;
    }
    const result = comparisonEvidence(a, b, { basis: basis.value, asOf: data.as_of, financialsSector: data.financials_sector });
    status.textContent = `${a.name || a.ticker} / ${b.name || b.ticker} · ${data.as_of || 'price session unknown'} · `
      + (result.sameBusinessGroup ? `${a.sub_sector}. Same GICS group, not a validated business-model match.` : 'Different / missing GICS groups. Values are shown, but directional evidence is withheld.');
    const format = (v, unit = '%') => finite(v) ? `${num(v, 1)}${unit === 'pp' ? ' pp' : unit}` : DASH;
    const basisLabel = COMPARISON_BASES.find(([key]) => key === basis.value)?.[1] || '';
    const premium = result.premium;
    const headline = !finite(premium) ? 'MULTIPLE COMPARISON UNAVAILABLE'
      : !result.leader ? 'NO VISIBLE MULTIPLE PREMIUM'
        : `${a.ticker} AT ${num(Math.abs(premium), 1)}% ${premium > 0 ? 'PREMIUM' : 'DISCOUNT'} TO ${b.ticker}`;
    host.append(el('div', { class: 'compare-price' }, [
      el('div', { class: 'compare-price-title', text: headline }),
      el('div', { class: 'compare-price-values', text: `${a.ticker} ${format(result.primaryA, '×')}  /  ${b.ticker} ${format(result.primaryB, '×')}` }),
      el('p', { class: 'note-text', text: `${basisLabel}. A price difference to investigate, not a fair-value verdict.` }),
      el('p', { class: 'note-text compare-basis-note', text: comparisonBasisNote(basis.value, a, b) }),
    ]));
    const evidenceLabel = result.leader ? `CONTEXT FOR ${result.leader}'S HIGHER MULTIPLE` : 'COMPARISON CONTEXT';
    host.append(el('h3', { class: 'compare-evidence-title', text: evidenceLabel }));
    host.append(table(['DIMENSION', a.ticker, b.ticker, 'READING'], result.rows.map((r) => el('tr', {}, [
      el('td', { class: 'wrap-cell compare-dimension' }, [r.label, el('span', { class: 'sub', text: r.note })]),
      el('td', { text: format(r.a, r.unit) }), el('td', { text: format(r.b, r.unit) }),
      el('td', { class: 'wrap-cell compare-reading' }, [
        el('span', { class: `compare-reading-label compare-${r.state}`, text: LABELS[r.state] }),
        r.state === 'unknown' ? el('span', { class: 'sub', text: r.reason }) : null,
      ]),
    ])), { class: 'compare-table' }));
    host.append(el('p', { class: 'note-text compare-limit', text: 'Facts can support one dimension of a premium; they do not measure how much premium is justified. No aggregate score or buy / sell signal. Competitive durability and unobserved business risks remain open questions.' }));
    host.append(el('div', { class: 'compare-links' }, [a, b].map((r) => el('span', {}, [
      el('a', { href: `#ticker/${encodeURIComponent(r.ticker)}/VALUATION`, text: `${r.ticker} · valuation` }), ' · ',
      el('a', { href: `#dcf/${encodeURIComponent(r.ticker)}`, text: 'inspect price requirements →' }),
    ]))));
    host.append(el('details', { class: 'method-fold compare-audit' }, [
      el('summary', { text: 'Dates, accounting limits & anchoring check' }),
      el('p', { class: 'note-text', text: `${a.ticker}: statements ${a.period_end || DASH}, filed ${a.filed || DASH}. ${b.ticker}: statements ${b.period_end || DASH}, filed ${b.filed || DASH}. NTM consensus and reported TTM earnings are different bases; the selector never blends them.` }),
      el('p', { class: 'note-text', text: 'Supporting / counterpoint labels compare the higher-multiple name with the other on one displayed metric only, within the same GICS sub-industry and aligned periods. They do not establish causality, future persistence or an appropriate multiple. A suggested peer uses only classification and size, excluding duplicate issuers.' }),
      el('p', { class: 'note-text', text: 'ROIC, ROE and book multiples depend on buybacks, leverage, acquired goodwill and unrecorded internal intangibles. No intangible-capital adjustment or brand value is estimated here. For financial firms, comparable asset-quality and capital-buffer inputs are not supplied.' }),
      el('p', { class: 'note-text', text: 'ANCHORING CHECK · Would the historical multiple still be appropriate if growth, competition or capital needs changed? Compare independent operating assumptions before using past prices or peer multiples as a target.' }),
    ]));
  };
  const controls = el('div', { class: 'field-row compare-controls' }, [
    el('div', { class: 'field' }, [el('label', { for: `${idPrefix}-a`, text: 'COMPANY A' }), aInput]),
    el('div', { class: 'field' }, [el('label', { for: `${idPrefix}-b`, text: 'COMPANY B' }), bInput]),
    el('div', { class: 'field' }, [el('label', { for: `${idPrefix}-basis`, text: 'VALUATION MEASURE' }), basis]),
    el('button', { type: 'button', class: 'action', text: 'COMPARE', onclick: draw }),
    el('button', { type: 'button', class: 'action', text: 'SWAP', onclick: () => {
      const before = aInput.value; aInput.value = bInput.value; bInput.value = before; draw();
    } }),
    el('button', { type: 'button', class: 'action', text: 'SUGGEST PEER', onclick: () => {
      const peer = suggestPeer(rows, resolve(aInput)); bInput.value = peer?.ticker || ''; draw();
    } }),
    el('datalist', { id: listId }, rows.map((r) => el('option', { value: r.ticker, text: r.name || r.ticker }))),
  ]);
  for (const input of [aInput, bInput]) {
    input.addEventListener('change', draw);
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') draw(); });
  }
  basis.addEventListener('change', draw);
  draw();
  const node = card('COMPARE · WHAT COULD SUPPORT THE PREMIUM?', el('span', { class: 'dim', text: 'Evidence, not a price target' }), [controls, status, host]);
  if (!fold) return node;
  return el('details', { class: 'fold compare-fold', open: open ? '' : null }, [
    el('summary', { text: 'COMPARE TWO COMPANIES · WHAT COULD SUPPORT A PREMIUM?' }), node]);
}
