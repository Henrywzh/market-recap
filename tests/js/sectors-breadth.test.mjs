// The sub-industry table's BREADTH 30D cell: net upgrades over analysts, toned
// by direction, with the shares of names up and down on hover; a dash without counts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { breadthCell } from '../../web/js/tabs/sectors.js';

function withDocument(run) {
  const saved = globalThis.document;
  globalThis.document = {
    createElement: (tag) => ({ tagName: tag, children: [], attrs: {}, className: '', textContent: '', title: '',
      setAttribute(k, v) { this.attrs[k] = v; }, append(...n) { this.children.push(...n); } }),
    createTextNode: (text) => ({ nodeType: 3, text }),
  };
  try { return run(); } finally { if (saved === undefined) delete globalThis.document; else globalThis.document = saved; }
}

test('breadth reads net upgrades as a signed share, with the up and down shares on hover', () => withDocument(() => {
  const cell = breadthCell({ net_pct: -12.4, upgraded_pct: 20, downgraded_pct: 55, names: 15 });
  assert.equal(cell.textContent, '-12%');
  assert.match(cell.className, /down/);
  assert.match(cell.title || cell.attrs.title, /20% of names net upgraded, 55% net downgraded \(15 names\)/);
  assert.equal(breadthCell({ net_pct: null }).textContent, '—');
  assert.equal(breadthCell(undefined).textContent, '—');
}));
