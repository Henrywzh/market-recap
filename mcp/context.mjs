// One tool call's view of the deployment: it reads the site's own published
// artifacts through the Pages ASSETS binding (nothing else is ever fetched),
// remembers what it read and what it could not, and wraps the adapter's data
// in the envelope every result carries.
//
// A missing artifact or field never fails a call. The part is null and the
// reason is listed under `unavailable`, the way the pages show a dash.

import { isObj } from './util.mjs';
import { T } from './schema.mjs';

export const SITE_URL = 'https://market-recap-b5p.pages.dev';
export const METHOD_VERSION = 'market-recap-mcp/1';
export const MAX_TEXT = 20000;

// Names an adapter may read are file stems under artifacts/ (up to two levels,
// such as events/AAPL or mcp/ticker/AAPL); the pattern keeps a symbol typed by
// a client from becoming any other path.
const NAME = /^[A-Za-z0-9][A-Za-z0-9._\-]*(\/[A-Za-z0-9][A-Za-z0-9._\-]*){0,2}$/;

export class Context {
  constructor({ assets, origin = SITE_URL, now = new Date() }) {
    this.assets = assets;
    this.origin = origin;
    this.now = now;
    this.cache = new Map();
    this.sliceCache = new Map();
    this.slices = [];          // loaded slices that hold reduced artifacts
    this.sources = new Map();   // artifact file -> its own as_of
    this.notes = [];
    this.caveats = [];
    this.unavailable = [];
    this.manifest = null;
  }

  // A slice is a file under artifacts/mcp/ (written by src/market_recap/mcp_slices.py):
  // either reduced copies of the artifacts this call reads, which read() serves
  // in place of the full files, or an index the adapter resolves a name with.
  // Null when this build does not publish it; the adapter then reads the full
  // artifacts, as an older deploy always did.
  async loadSlice(name) {
    if (!NAME.test(name)) return null;
    if (!this.sliceCache.has(name)) this.sliceCache.set(name, this.fetchJson(`mcp/${name}`));
    const slice = await this.sliceCache.get(name);
    if (slice && isObj(slice.artifacts) && !this.slices.includes(slice)) this.slices.push(slice);
    return slice;
  }

  // The parsed artifact, or null with the reason recorded under `part`.
  async get(name, part) {
    const data = await this.read(name);
    if (data === null) {
      this.missing(part, `artifacts/${name}.json is not published in this build`);
      return null;
    }
    this.sources.set(`${name}.json`, isObj(data) ? data.as_of ?? null : null);
    return data;
  }

  // Like get(), but an absent file is expected (a ticker without events) and
  // is not an error worth a line of its own.
  async read(name) {
    if (!NAME.test(name)) return null;
    for (const slice of this.slices) {
      if (Object.hasOwn(slice.artifacts, name)) return slice.artifacts[name];
    }
    if (!this.cache.has(name)) this.cache.set(name, this.fetchJson(name));
    return this.cache.get(name);
  }

  async fetchJson(name) {
    try {
      const url = new URL(`/artifacts/${name}.json`, this.origin);
      const response = await this.assets.fetch(new Request(url));
      if (!response.ok) return null;
      const parsed = JSON.parse(await response.text());
      return isObj(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }

  async loadManifest() {
    this.manifest = await this.read('manifest');
    if (!this.manifest) this.missing('manifest', 'artifacts/manifest.json is not published, so as_of and generated_at are unknown');
    else this.sources.set('manifest.json', this.manifest.as_of ?? null);
    return this.manifest;
  }

  missing(part, reason) {
    if (!this.unavailable.some((u) => u.part === part && u.reason === reason)) this.unavailable.push({ part, reason });
  }

  // Null for a value the artifact lacks, with the reason recorded.
  need(value, part, reason) {
    if (value === null || value === undefined) {
      this.missing(part, reason);
      return null;
    }
    return value;
  }

  note(...texts) {
    texts.forEach((t) => { if (typeof t === 'string' && t.trim() && !this.notes.includes(t.trim())) this.notes.push(t.trim()); });
  }

  caveat(...texts) {
    texts.forEach((t) => { if (!this.caveats.includes(t)) this.caveats.push(t); });
  }

  link(hash) {
    return `${this.origin}/#${hash}`;
  }

  // The envelope around an adapter's data, cut to fit the size budget.
  finish(data, { budget = MAX_TEXT } = {}) {
    const asOf = this.manifest?.as_of ?? null;
    const sourceAsOf = Object.fromEntries([...this.sources].filter(([file]) => file !== 'manifest.json'));
    const older = Object.entries(sourceAsOf).filter(([, d]) => asOf && d && d < asOf);
    if (older.length) this.caveat('Some sources are dated before as_of (their own dates are in source_as_of); each page shows its own date too.');
    const result = {
      as_of: asOf,
      generated_at: this.manifest?.generated_at ?? null,
      sources: [...this.sources.keys()].sort(),
      source_as_of: sourceAsOf,
      method: { version: METHOD_VERSION, notes: this.notes.slice(0, 6).map((n) => (n.length > 800 ? `${n.slice(0, 799)}…` : n)) },
      caveats: this.caveats.slice(),
      unavailable: this.unavailable.slice(),
      truncated: [],
      ...data,
    };
    return fitBudget(result, budget);
  }
}

const PROTECTED = new Set(['sources', 'unavailable', 'caveats', 'method', 'truncated', 'source_as_of']);

function arrays(node, path, found) {
  if (Array.isArray(node)) {
    if (node.length > 1) found.push({ path, node });
    node.forEach((item, i) => arrays(item, `${path}[${i}]`, found));
  } else if (isObj(node)) {
    Object.entries(node).forEach(([key, value]) => {
      if (!path && PROTECTED.has(key)) return;
      arrays(value, path ? `${path}.${key}` : key, found);
    });
  }
  return found;
}

// If the result is still over budget, halve the largest list and say so. The
// adapters already cap their own lists; this is the backstop, so a client
// always gets a whole, parseable result instead of a cut-off one.
export function fitBudget(input, budget) {
  // A copy, so cutting a list never touches an artifact the cache still holds.
  const result = JSON.parse(JSON.stringify(input));
  let guard = 60;
  while (JSON.stringify(result).length > budget && guard > 0) {
    guard -= 1;
    const biggest = arrays(result, '', []).sort((a, b) => JSON.stringify(b.node).length - JSON.stringify(a.node).length)[0];
    if (!biggest) break;
    const total = biggest.node.length;
    biggest.node.length = Math.ceil(total / 2);
    const existing = result.truncated.find((t) => t.path === biggest.path);
    if (existing) existing.shown = biggest.node.length;
    else result.truncated.push({ path: biggest.path, shown: biggest.node.length, total });
  }
  if (result.truncated.length) {
    result.caveats.push('The result was cut to fit about 20 KB: `truncated` lists each cut list (shown of total). Ask again with narrower arguments (a date range, one kind, a smaller limit) for the rest.');
  }
  return result;
}

// The properties every tool result has; each tool's schema adds its own.
export const ENVELOPE_PROPERTIES = {
  as_of: T.strNull,
  generated_at: T.strNull,
  sources: T.arr(T.str),
  source_as_of: { type: 'object' },
  method: T.obj({ version: T.str, notes: T.arr(T.str) }, ['version', 'notes']),
  caveats: T.arr(T.str),
  unavailable: T.arr(T.obj({ part: T.str, reason: T.str }, ['part', 'reason'])),
  truncated: T.arr(T.obj({ path: T.str, shown: { type: 'integer' }, total: { type: 'integer' } }, ['path', 'shown', 'total'])),
};
export const ENVELOPE_REQUIRED = ['as_of', 'generated_at', 'sources', 'method', 'caveats', 'unavailable'];

export function outputSchema(properties, required = []) {
  return {
    type: 'object',
    properties: { ...ENVELOPE_PROPERTIES, ...properties },
    required: [...ENVELOPE_REQUIRED, ...required],
  };
}
