// Squarified treemap laid out by hand.
//
// The stock heat map is the one panel where an off-the-shelf chart gets the
// *meaning* wrong: it wants to size tiles by the value it colours by. Here
// area is the issuer's published index weight and colour is return, and the
// two must stay independent, so the layout is computed directly.

import { el } from './fmt.js';

function squarify(items, x, y, width, height, out) {
  if (!items.length) return out;
  if (items.length === 1) {
    out.push({ ...items[0], x, y, w: width, h: height });
    return out;
  }
  const total = items.reduce((sum, item) => sum + item.value, 0);
  let split = 0;
  let accumulated = 0;
  const half = total / 2;
  while (split < items.length - 1 && accumulated + items[split].value < half) {
    accumulated += items[split].value;
    split += 1;
  }
  const head = items.slice(0, Math.max(1, split));
  const tail = items.slice(Math.max(1, split));
  const headShare = head.reduce((sum, item) => sum + item.value, 0) / total;

  if (width >= height) {
    const cut = width * headShare;
    squarify(head, x, y, cut, height, out);
    squarify(tail, x + cut, y, width - cut, height, out);
  } else {
    const cut = height * headShare;
    squarify(head, x, y, width, cut, out);
    squarify(tail, x, y + cut, width, height - cut, out);
  }
  return out;
}

// Return -> colour. The midpoint is a neutral slate rather than black so a
// flat name stays legible, and the scale saturates at +/- `cap` percent so one
// outlier cannot wash the whole map out.
export function returnColor(value, cap = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) return '#2b2b2b';
  const clamped = Math.max(-cap, Math.min(cap, value));
  const strength = Math.abs(clamped) / cap;
  const neutral = [38, 43, 50];
  const target = clamped >= 0 ? [34, 197, 94] : [220, 38, 38];
  const mix = neutral.map((base, i) => Math.round(base + (target[i] - base) * (0.25 + 0.75 * strength)));
  return `rgb(${mix.join(',')})`;
}

export function flowColor(value, cap) {
  return returnColor(value === null || value === undefined ? null : (value / cap) * 3, 3);
}

/**
 * @param {HTMLElement} host
 * @param {Array<{group:string, items:Array<{key:string,value:number,color:string,label:string,sublabel:string,payload:object}>}>} groups
 * @param {(payload:object, event:MouseEvent)=>void} onHover
 */
export function drawTreemap(host, groups, onHover, onLeave) {
  host.innerHTML = '';
  const width = host.clientWidth;
  const height = host.clientHeight;
  if (!width || !height) return;

  const sized = groups
    .map((group) => ({ ...group, value: group.items.reduce((sum, item) => sum + item.value, 0) }))
    .filter((group) => group.value > 0)
    .sort((a, b) => b.value - a.value);

  const groupBoxes = squarify(sized, 0, 0, width, height, []);

  groupBoxes.forEach((box) => {
    const wrapper = el('div', { class: 'tm-group' });
    Object.assign(wrapper.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` });
    wrapper.append(el('div', { class: 'tm-group-label', text: box.group.toUpperCase() }));

    const items = [...box.items].filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
    const inner = squarify(items, 1, 16, Math.max(0, box.w - 2), Math.max(0, box.h - 17), []);

    inner.forEach((tile) => {
      const node = el('div', { class: 'tm-tile' });
      Object.assign(node.style, {
        left: `${tile.x}px`, top: `${tile.y}px`,
        width: `${Math.max(0, tile.w - 1)}px`, height: `${Math.max(0, tile.h - 1)}px`,
        background: tile.color,
      });
      const area = tile.w * tile.h;
      // Only label a tile that can actually hold the text. A clipped ticker is
      // worse than no ticker: it reads as a different symbol.
      if (area > 900 && tile.w > 34 && tile.h > 22) {
        const scale = Math.max(8, Math.min(26, Math.sqrt(area) / 5.2));
        node.append(el('span', { class: 'tm-sym', text: tile.label, style: `font-size:${scale}px;color:#fff` }));
        if (tile.h > 34) {
          node.append(el('span', { class: 'tm-val', text: tile.sublabel, style: `font-size:${Math.max(8, scale * 0.6)}px;color:#f0f0f0` }));
        }
      }
      node.addEventListener('mousemove', (event) => onHover(tile.payload, event));
      node.addEventListener('mouseleave', onLeave);
      wrapper.append(node);
    });
    host.append(wrapper);
  });
}
