// Formatting and small DOM helpers. Absence is rendered as an em dash, never
// as a zero: "no data" and "no change" are different statements.

export const DASH = '—';

export function num(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  // A value that rounds to zero prints as zero: "-0.00%" reads as a fall.
  const rounded = Math.abs(value) < 0.5 * 10 ** -digits ? 0 : Number(value);
  return rounded.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function pct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const sign = value >= 0.5 * 10 ** -digits ? '+' : '';
  return `${sign}${num(value, digits)}%`;
}

export function bps(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const sign = value > 0 ? '+' : '';
  return `${sign}${num(value, digits)}`;
}

export function money(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${value < 0 ? '-' : '+'}$${num(abs / 1e9, 2)}B`;
  if (abs >= 1e6) return `${value < 0 ? '-' : '+'}$${num(abs / 1e6, 0)}M`;
  return `${value < 0 ? '-' : '+'}$${num(abs, 0)}`;
}

export function aum(value) {
  if (!value) return DASH;
  if (value >= 1e9) return `$${num(value / 1e9, 1)}B`;
  return `$${num(value / 1e6, 0)}M`;
}

export function dirClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'flat';
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
}

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function card(title, right, body) {
  const head = el('div', { class: 'card-head' }, [el('span', { class: 'card-title', text: title })]);
  if (right) head.append(right);
  return el('div', { class: 'card' }, [head, ...[].concat(body)]);
}

export function sectionTitle(title, muted) {
  return el('h2', { class: 'section-title' }, [
    title,
    muted ? el('span', { class: 'muted', text: ` ${muted}` }) : null,
  ]);
}

// A period switch that owns its own state and calls back with the choice.
export function periodSwitch(periods, active, onPick) {
  const wrap = el('div', { class: 'period-switch' });
  periods.forEach((period) => {
    const button = el('button', {
      type: 'button',
      text: period,
      'aria-pressed': String(period === active),
      onclick: () => {
        [...wrap.children].forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === period)));
        onPick(period);
      },
    });
    wrap.append(button);
  });
  return wrap;
}

export function table(headers, rows, options = {}) {
  const thead = el('thead', {}, [el('tr', {}, headers.map((h) => el('th', { text: h })))]);
  const tbody = el('tbody', {}, rows);
  const node = el('table', { class: `data ${options.class || ''}` }, [thead, tbody]);
  // Wrapped so a table that cannot fit scrolls within its own card. A table
  // that overflows the page instead pushes every other panel's right-hand
  // column off screen, which is how a 70px-too-wide movers table made the
  // whole dashboard scroll sideways.
  return el('div', { class: 'table-scroll' }, [node]);
}

export function gap(message) {
  return el('div', { class: 'gap', text: message });
}

export function notice(message) {
  return el('div', { class: 'notice', text: message });
}
