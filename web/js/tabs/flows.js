// FLOWS: who is buying, from published records rather than a model. Fastest
// first: ETF creations (daily), futures by trader type (weekly), then the
// quarterly hedge-fund filings and the Fed's account of who bought equities.

import { el, metaRow } from '../fmt.js';
import { section as etfSection } from '../flows-etf.js';
import { section as cotSection } from '../flows-cot.js';
import { section as z1Section } from '../flows-z1.js';
import { section as leverageSection } from '../flows-hf-leverage.js';
import { section as crowdingSection } from '../flows-hf-13f.js';

const SECTIONS = [
  { key: 'etf', title: 'ETF FLOWS · DAILY', build: etfSection },
  { key: 'cot', title: 'INDEX FUTURES BY TRADER TYPE · WEEKLY', build: cotSection },
  { key: 'hf_13f', title: 'HEDGE-FUND HOLDINGS · QUARTERLY', build: crowdingSection },
  { key: 'hf_leverage', title: 'HEDGE-FUND LEVERAGE · QUARTERLY', build: leverageSection },
  { key: 'z1', title: 'WHO BOUGHT US EQUITIES · QUARTERLY', build: z1Section },
];

const NOTES = [
  'Every figure here is a published record — an issuer\'s shares outstanding, a CFTC report, a 13F or Form PF filing, the Fed\'s financial accounts — not a model. Each is as of its own date, shown on its card; the slower ones are weeks or months old.',
  'ETF flows are primary-market creations and redemptions: they show money entering or leaving a fund, not who the end buyer was.',
];

export default function renderFlows(root, data) {
  if (!data || data.unavailable) throw new Error(data?.unavailable || 'flows artifact missing');
  root.append(metaRow(`FLOWS · WHO IS BUYING · AS OF ${data.as_of}`, NOTES));
  for (const { key, title, build } of SECTIONS) {
    root.append(el('h2', { class: 'section-title', text: title }));
    const part = data[key];
    if (!part || part.unavailable) {
      root.append(el('div', { class: 'gap', text: `Not built this session${part?.unavailable ? `: ${part.unavailable}` : ''}.` }));
      continue;
    }
    for (const node of build(part)) if (node) root.append(node);
  }
}
