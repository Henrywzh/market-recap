// One calendar range, anchored to the risk artifact session (not each feed's last date).
import { el, periodSwitch } from './fmt.js';
let active = 'YTD';
let anchor = null;
const listeners = new Set();
const labels = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX'];
const days = { '1M': 31, '3M': 92, '6M': 182, '1Y': 365, '3Y': 1096, '5Y': 1826 };
export function initialRange() { return active; }
export function sliceRange(dates, columns, _label, { future = false } = {}) {
  const end = anchor || dates?.at(-1);
  const cut = active === 'YTD' ? `${end?.slice(0, 4)}-01-01` : active === 'MAX' ? null : new Date(Date.parse(end) - days[active] * 86400000).toISOString().slice(0, 10);
  const indices = (dates || []).flatMap((d, i) => ((!cut || d >= cut) && (future || !end || d <= end)) ? [i] : []);
  return { ...Object.fromEntries(Object.entries(columns).filter(([k]) => k !== 'dates').map(([k, v]) => [k, indices.map((i) => v?.[i] ?? null)])), dates: indices.map((i) => dates[i]) };
}
// Invisible registration slots replace per-chart range controls.
export function rangeSwitch(_dates, _active, onPick) {
  const node = el('span', { hidden: true });
  listeners.add({ node, onPick });
  return node;
}
export function riskRangeControl(asOf) {
  anchor = asOf;
  listeners.clear();
  const node = el('div', { class: 'risk-global-range' });
  const paint = () => {
    node.replaceChildren(el('strong', { text: 'ALL RISK HISTORIES' }), periodSwitch(labels, active, (label) => {
      active = label;
      for (const entry of listeners) {
        if (entry.node.isConnected) entry.onPick(label);
        else listeners.delete(entry);
      }
      paint();
    }), el('span', { class: 'rc-note', text: `Through ${asOf} · missing / shorter histories stay incomplete; latest cards retain their own dates. Term structure is a snapshot; blackout projections remain dashed.` }));
  };
  paint();
  return node;
}
