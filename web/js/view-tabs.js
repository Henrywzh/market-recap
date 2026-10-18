// A row of sub-tabs over panels (role=tablist, arrow keys), each panel built the
// first time it is shown, so a chart is drawn at its real size; showing a built
// panel again resizes the charts (a hidden node has no size).
import { el } from './fmt.js';
import { resizeAll } from './charts.js';

// tabs: [[id, LABEL], ...]. build(id) returns the panel's nodes (or a promise of
// them); onPick(id) runs when the reader picks a tab (not on the first show).
export function viewTabs(tabs, active, { label, idPrefix, build, onPick = () => {} }) {
  const nav = el('div', { class: 'view-switch', role: 'tablist', 'aria-label': label });
  const panes = new Map(tabs.map(([id]) => [id, el('div', {
    role: 'tabpanel', id: `${idPrefix}-view-${id}`, 'aria-labelledby': `${idPrefix}-tab-${id}`,
  })]));
  const built = new Set();
  let current = null;

  const show = async (id) => {
    current = id;
    [...nav.children].forEach((button, i) => {
      const picked = tabs[i][0] === id;
      button.setAttribute('aria-selected', String(picked));
      button.setAttribute('tabindex', picked ? '0' : '-1');
    });
    panes.forEach((pane, key) => { pane.hidden = key !== id; });
    if (!built.has(id)) {
      built.add(id);
      const nodes = await build(id, panes.get(id));
      if (nodes) panes.get(id).replaceChildren(...nodes.filter(Boolean));
    }
    requestAnimationFrame(resizeAll);
  };
  const pick = (id) => {
    if (id === current) return;
    show(id);
    onPick(id);
  };

  tabs.forEach(([id, text], i) => nav.append(el('button', {
    type: 'button', role: 'tab', id: `${idPrefix}-tab-${id}`, text,
    'aria-controls': `${idPrefix}-view-${id}`, 'aria-selected': String(id === active), tabindex: id === active ? '0' : '-1',
    onclick: () => pick(id),
    onkeydown: (event) => {
      let next = i;
      if (event.key === 'ArrowRight') next = (i + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (i + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      nav.children[next].focus();
      pick(tabs[next][0]);
    },
  })));

  return { nav, panes: [...panes.values()], show };
}
