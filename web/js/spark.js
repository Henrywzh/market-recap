// Inline SVG sparkline: one small line with an optional dashed threshold.
// Tiles carry dozens of these; an ECharts instance each would be far heavier.

const NS = 'http://www.w3.org/2000/svg';

export function spark(values, { threshold = null, width = 150, height = 34, color = 'currentColor' } = {}) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('preserveAspectRatio', 'none');
  const points = (values || []).map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined && Number.isFinite(v));
  if (points.length < 2) return svg;
  let lo = Math.min(...points.map(([, v]) => v));
  let hi = Math.max(...points.map(([, v]) => v));
  if (threshold !== null && Number.isFinite(threshold) && threshold >= lo - (hi - lo) && threshold <= hi + (hi - lo)) {
    lo = Math.min(lo, threshold);
    hi = Math.max(hi, threshold);
  }
  const span = hi - lo || 1;
  const last = values.length - 1 || 1;
  const x = (i) => (i / last) * (width - 2) + 1;
  const y = (v) => height - 2 - ((v - lo) / span) * (height - 4);
  if (threshold !== null && Number.isFinite(threshold) && threshold >= lo && threshold <= hi) {
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', '0'); line.setAttribute('x2', String(width));
    line.setAttribute('y1', String(y(threshold))); line.setAttribute('y2', String(y(threshold)));
    line.setAttribute('class', 'spark-threshold');
    svg.append(line);
  }
  const path = document.createElementNS(NS, 'polyline');
  path.setAttribute('points', points.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' '));
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', color);
  path.setAttribute('stroke-width', '1.3');
  path.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(path);
  const [li, lv] = points[points.length - 1];
  const dot = document.createElementNS(NS, 'circle');
  dot.setAttribute('cx', String(x(li))); dot.setAttribute('cy', String(y(lv))); dot.setAttribute('r', '2');
  dot.setAttribute('fill', color);
  svg.append(dot);
  return svg;
}
