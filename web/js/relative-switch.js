// RELATIVE VALUE is one menu entry with two pages. This switch, drawn at the top of
// each, moves between them; the pages keep their own hashes (#kshape, #sizek), so a
// bookmark to either still works.

import { periodSwitch } from './fmt.js';

const PAGES = [['K-SHAPE', 'kshape'], ['SIZE & STYLE', 'sizek']];

export function relativeSwitch(active, ctx = {}) {
  const current = PAGES.find(([, id]) => id === active)[0];
  return periodSwitch(PAGES.map(([label]) => label), current, (label) => {
    const target = PAGES.find(([l]) => l === label)[1];
    if (target !== active) ctx.navigate?.(target);
  });
}
