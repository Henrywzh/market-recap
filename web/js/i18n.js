// Simplified Chinese as a layer over the English page: a dictionary of exact
// phrases and of sentence patterns (i18n-zh.js) applied to the text a view
// renders, to the attributes a reader sees (title, placeholder, aria-label)
// and, through charts.js, to each chart's names, labels and tooltips. The tabs
// stay written in English; anything the dictionary lacks stays English, never
// blank. ?i18n=report collects every miss in window.__i18nMisses, which
// scripts/i18n-report.mjs reads to list what is left to translate.

import { EXACT, PATTERNS } from './i18n-zh.js';

const KEY = 'mr-lang';
const LATIN = /[A-Za-z]/;
// One short all-caps word is often a ticker (ALL, NOW, LOW, KEY, ON): it is
// translated only where a ticker never sits -- buttons, headers, labels.
const SHORT_CAPS = /^[A-Z&]{1,5}$/;
const LABEL_PARENTS = 'button, th, summary, label, option, legend, .stat-label, .card-title, .section-title, .period-switch, .view-switch, .subtab, .tab, [class*="tag"], [class*="badge"], [class*="chip"], [class*="kind"]';
const SKIP_PARENTS = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE', 'NOSCRIPT']);
const SEPARATORS = ['\n', ' · ', ' — ', ' | '];

function readLanguage() {
  try {
    const asked = new URLSearchParams(window.location.search).get('lang');
    if (asked === 'zh' || asked === 'en') { localStorage.setItem(KEY, asked); return asked; }
    return localStorage.getItem(KEY) === 'zh' ? 'zh' : 'en';
  } catch {
    return 'en';
  }
}

export const LANG = typeof window === 'undefined' ? 'en' : readLanguage();
export const ZH = LANG === 'zh';
const REPORT = typeof window !== 'undefined' && /[?&]i18n=report\b/.test(window.location.search);
if (REPORT) window.__i18nMisses = new Map();

export function setLanguage(lang) {
  try { localStorage.setItem(KEY, lang); } catch { /* storage unavailable: the URL still carries it */ }
  // A real reload: replacing the address with itself, hash and all, is a hash-only
  // navigation that reloads nothing, so the switch did nothing until ⌘R.
  const url = new URL(window.location.href);
  if (url.searchParams.has('lang')) {
    url.searchParams.delete('lang');
    window.history.replaceState(null, '', url.toString());
  }
  window.location.reload();
}

const UPPER = new Map(Object.entries(EXACT).map(([k, v]) => [k.toUpperCase(), v]));
const memo = new Map();

function lookup(core, labelContext) {
  if (SHORT_CAPS.test(core) && !labelContext) return null;
  return EXACT[core] ?? UPPER.get(core.toUpperCase()) ?? null;
}

// A number or a date (with its sign, currency and %), which reads the same in both
// languages: "76 names" is the template "# names", filled back in order. Units
// written as letters (3M, 21D, 52W, 25bp) stay in the template: "#M", "#D".
const TOKEN = /\d{4}-\d{2}(?:-\d{2})?|[+\-−]?[$€£]?\d(?:[\d,]*\d)?(?:\.\d+)?[%×xσ]?/g;

function byTemplate(core, labelContext) {
  const tokens = core.match(TOKEN);
  if (!tokens) return null;
  const template = core.replace(TOKEN, '#');
  const value = lookup(template, true);
  if (value === null) return null;
  let i = 0;
  // {0}, {1} place a token where Chinese word order wants it; a bare # takes the next one.
  return value.replace(/\{(\d+)\}|#/g, (m, at) => (at !== undefined ? tokens[Number(at)] ?? m : tokens[i++] ?? m));
}

const piece = (s) => translateText(s, { label: true });
const known = (s) => piece(s) !== s;

// A pattern's function may decline (null) when its parts are not known.
function byPattern(core) {
  for (const [re, out] of PATTERNS) {
    const m = core.match(re);
    if (!m) continue;
    const done = typeof out === 'function' ? out(m, piece, known) : core.replace(re, out);
    if (done !== null && done !== undefined) return done;
  }
  return null;
}

// One string, whitespace kept; null when nothing in it is known. A title built of
// parts ("CREDIT SPREADS · AS OF 2026-11-04") is split before any sentence
// pattern, so a pattern never swallows a whole title.
function translateCore(core, labelContext) {
  const exact = lookup(core, labelContext);
  if (exact !== null) return exact;
  const template = byTemplate(core, labelContext);
  if (template !== null) return template;
  for (const sep of SEPARATORS) {
    if (!core.includes(sep)) continue;
    const parts = core.split(sep);
    const out = parts.map((part) => (LATIN.test(part) ? translateCore(part.trim(), true) ?? part : part));
    return out.some((part, i) => part !== parts[i]) ? out.join(sep) : null;
  }
  return byPattern(core);
}

export function translateText(text, { label = false } = {}) {
  if (!ZH || typeof text !== 'string' || !LATIN.test(text)) return text;
  const key = `${label ? 1 : 0}${text}`;
  if (memo.has(key)) {
    const known = memo.get(key);
    if (REPORT && known === text) window.__i18nMisses.set(text.trim(), (window.__i18nMisses.get(text.trim()) || 0) + 1);
    return known;
  }
  // ECharts rich text, "{rare|2.4σ · RARE: 0.3% of days}": the words inside the braces.
  const rich = text.match(/^\{(\w+)\|([\s\S]*)\}$/);
  if (rich) {
    const inner = translateText(rich[2], { label });
    return inner === rich[2] ? text : `{${rich[1]}|${inner}}`;
  }
  const lead = text.match(/^\s*/)[0];
  const tail = text.slice(lead.length).match(/\s*$/)[0];
  const core = text.slice(lead.length, text.length - tail.length);
  const done = translateCore(core, label);
  const out = done === null ? text : `${lead}${done}${tail}`;
  if (done === null && REPORT) {
    const misses = window.__i18nMisses;
    misses.set(core, (misses.get(core) || 0) + 1);
  }
  memo.set(key, out);
  return out;
}

// HTML a chart's tooltip formatter returns: the text between tags only.
export function translateHtml(html) {
  if (!ZH || typeof html !== 'string') return html;
  if (!html.includes('<')) return translateText(html);
  return html.replace(/(^|>)([^<]+)(?=<|$)/g, (m, open, text) => `${open}${translateText(text)}`);
}

// --- the page ------------------------------------------------------------------

const done = new WeakMap();   // text node -> the value this layer last wrote

function translateTextNode(node) {
  const parent = node.parentElement;
  if (!parent || SKIP_PARENTS.has(parent.tagName) || parent.closest('[data-i18n-skip]')) return;
  const value = node.nodeValue;
  if (done.get(node) === value || !LATIN.test(value)) return;
  const out = translateText(value, { label: Boolean(parent.closest(LABEL_PARENTS)) });
  if (out !== value) node.nodeValue = out;
  done.set(node, out);
}

function translateAttributes(element) {
  for (const name of ['title', 'placeholder', 'aria-label']) {
    const value = element.getAttribute?.(name);
    if (value && LATIN.test(value)) {
      const out = translateText(value, { label: true });
      if (out !== value) element.setAttribute(name, out);
    }
  }
}

export function translateTree(root) {
  if (!ZH || !root) return;
  if (root.nodeType === Node.TEXT_NODE) { translateTextNode(root); return; }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
    else translateAttributes(node);
  }
}

// Everything already on the page, then whatever any view adds or rewrites later
// (live quotes, a switched chart's caption, a lazily loaded section).
export function startTranslating() {
  if (!ZH) return;
  document.documentElement.lang = 'zh-Hans';
  translateTree(document.body);
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'characterData') translateTextNode(record.target);
      else if (record.type === 'attributes') translateAttributes(record.target);
      else record.addedNodes.forEach((node) => translateTree(node));
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ['title', 'placeholder', 'aria-label'] });
}

// --- charts --------------------------------------------------------------------

const TEXT_KEYS = new Set(['text', 'subtext', 'name']);
const LABEL_KEYS = new Set(['data']);

// An ECharts option with every reader-facing string translated: titles, series
// and axis names, category and legend entries, and whatever a formatter returns.
export function translateOption(option) {
  if (!ZH) return option;
  // Chart code keys its own lookups by the English name (a tooltip finds a
  // series' unit by seriesName): a formatter is handed the English back, and
  // only what it returns is translated.
  const english = new Map();
  const shown = (value) => {
    const out = translateText(value);
    if (out !== value) english.set(out, value);
    return out;
  };
  const back = (value) => {
    if (typeof value === 'string') return english.get(value) ?? value;
    if (Array.isArray(value)) return value.map(back);
    if (value && typeof value === 'object' && !(value instanceof Date)) {
      const out = { ...value };
      for (const key of ['seriesName', 'name', 'value', 'axisValue', 'axisValueLabel']) {
        if (typeof out[key] === 'string') out[key] = english.get(out[key]) ?? out[key];
      }
      // A legend event's state is keyed by the shown names.
      if (out.selected && typeof out.selected === 'object' && !Array.isArray(out.selected)) {
        out.selected = Object.fromEntries(Object.entries(out.selected).map(([name, on]) => [english.get(name) ?? name, on]));
      }
      return out;
    }
    return value;
  };
  const walk = (value, key) => {
    if (typeof value === 'string') {
      // A formatter given as plain text is a label; one with {a}/{b} placeholders is a template.
      if (key === 'formatter') return value.includes('{') ? value : translateText(value);
      return TEXT_KEYS.has(key) || LABEL_KEYS.has(key) ? shown(value) : value;
    }
    if (typeof value === 'function') {
      if (key !== 'formatter' && key !== 'valueFormatter') return value;
      const fn = value;
      return function translated(...args) { return translateHtml(fn.apply(this, args.map(back))); };
    }
    if (Array.isArray(value)) return value.map((item) => walk(item, key === 'data' ? 'data' : key));
    if (value && typeof value === 'object' && !(value instanceof Date)) {
      const out = {};
      for (const [k, v] of Object.entries(value)) {
        // Legend state is keyed by series name, so its keys follow the names.
        if (k === 'selected' && v && typeof v === 'object' && !Array.isArray(v)) {
          out[k] = Object.fromEntries(Object.entries(v).map(([name, on]) => [shown(name), on]));
        } else {
          out[k] = walk(v, k);
        }
      }
      return out;
    }
    return value;
  };
  const out = walk(option, null);
  // Event handlers (a click that picks a series) get the English names back too: charts.js reads this.
  if (out && typeof out === 'object') Object.defineProperty(out, 'englishNames', { value: back });
  return out;
}
