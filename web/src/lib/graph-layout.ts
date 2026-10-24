// Deterministic force layout for the knowledge map (no dependency; ~150 nodes in a few ms).
// Prerequisite edges pull concepts together; each concept is also pulled gently toward an
// invisible anchor for its main document, so ideas from one source sit near each other.
// Same input, same picture: positions are seeded from the ids, not Math.random().

export type Point = { x: number; y: number };

function seed(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

export function layout(
  ids: string[], edges: [string, string][], groupOf: Map<string, string>,
  width = 1000, height = 640, iterations = 260,
): Map<string, Point> {
  const groups = [...new Set(groupOf.values())];
  const all = [...ids, ...groups.map((g) => `doc:${g}`)];
  const idx = new Map(all.map((id, i) => [id, i]));
  const n = all.length;
  const xs = new Float64Array(n), ys = new Float64Array(n);
  all.forEach((id, i) => {
    const a = seed(id) * Math.PI * 2, r = 0.25 + 0.7 * seed(`${id}~`);
    xs[i] = width / 2 + Math.cos(a) * r * width * 0.45;
    ys[i] = height / 2 + Math.sin(a) * r * height * 0.45;
  });
  const springs: [number, number, number][] = edges
    .filter(([a, b]) => idx.has(a) && idx.has(b))
    .map(([a, b]) => [idx.get(a)!, idx.get(b)!, 1]);
  for (const [id, g] of groupOf) if (idx.has(id)) springs.push([idx.get(id)!, idx.get(`doc:${g}`)!, 0.35]);

  const k = Math.sqrt((width * height) / Math.max(n, 1)) * 0.75;
  const far2 = (3 * k) ** 2;
  let temp = width / 8;
  const dx = new Float64Array(n), dy = new Float64Array(n);
  for (let it = 0; it < iterations; it++) {
    dx.fill(0); dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ex = xs[i] - xs[j], ey = ys[i] - ys[j];
        let d2 = ex * ex + ey * ey;
        if (d2 > far2) continue;  // distant clusters stop pushing apart, so the centre pull can keep them close
        if (d2 < 0.01) { ex = 0.1; ey = 0.1; d2 = 0.02; }
        const f = (k * k) / d2;
        dx[i] += ex * f; dy[i] += ey * f; dx[j] -= ex * f; dy[j] -= ey * f;
      }
    }
    for (const [a, b, w] of springs) {
      const ex = xs[a] - xs[b], ey = ys[a] - ys[b];
      const d = Math.sqrt(ex * ex + ey * ey) || 0.1;
      const f = (d / k) * w;
      dx[a] -= ex * f; dy[a] -= ey * f; dx[b] += ex * f; dy[b] += ey * f;
    }
    for (let i = 0; i < n; i++) {
      // A weak pull to the centre keeps unconnected concepts on screen.
      dx[i] += (width / 2 - xs[i]) * 0.05; dy[i] += (height / 2 - ys[i]) * 0.05;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1;
      const step = Math.min(d, temp);
      xs[i] += (dx[i] / d) * step; ys[i] += (dy[i] / d) * step;
    }
    temp *= 0.985;
  }
  // Turn the picture so its long axis runs along the wide frame (principal axis), then fit the
  // concepts (not the anchors) into the frame with a margin for labels.
  const pts = ids.map((id) => idx.get(id)!);
  const mx = pts.reduce((t, i) => t + xs[i], 0) / pts.length, my = pts.reduce((t, i) => t + ys[i], 0) / pts.length;
  let cxx = 0, cyy = 0, cxy = 0;
  for (const i of pts) { cxx += (xs[i] - mx) ** 2; cyy += (ys[i] - my) ** 2; cxy += (xs[i] - mx) * (ys[i] - my); }
  const turn = -0.5 * Math.atan2(2 * cxy, cxx - cyy), cos = Math.cos(turn), sin = Math.sin(turn);
  for (const i of pts) {
    const x = xs[i] - mx, y = ys[i] - my;
    xs[i] = x * cos - y * sin; ys[i] = x * sin + y * cos;
  }
  const minX = Math.min(...pts.map((i) => xs[i])), maxX = Math.max(...pts.map((i) => xs[i]));
  const minY = Math.min(...pts.map((i) => ys[i])), maxY = Math.max(...pts.map((i) => ys[i]));
  const mx2 = 120, my2 = 50, sx = (width - 2 * mx2) / Math.max(maxX - minX, 1), sy = (height - 2 * my2) / Math.max(maxY - minY, 1);
  const s = Math.min(sx, sy);
  const ox = (width - (maxX - minX) * s) / 2, oy = (height - (maxY - minY) * s) / 2;
  return new Map(ids.map((id) => {
    const i = idx.get(id)!;
    return [id, { x: ox + (xs[i] - minX) * s, y: oy + (ys[i] - minY) * s }];
  }));
}
