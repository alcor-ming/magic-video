// 手绘纸地图：数据（世界坐标 x 向东、z 向南）→ 一份确定性的绘制计划 → 画进任意视窗（整图或局部高清片）。
// 地图上不写字：地名、兵力都由牌子给。
import { rng, clamp } from './util.js';

const INK = '#4a3726';
const PAPER = '#eee5d0';

function pip(pt, poly) { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, zi] = poly[i], [xj, zj] = poly[j]; if ((zi > pt[1]) !== (zj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - zi) / (zj - zi) + xi) c = !c; } return c; }
export { pip };
// 点到多边形的有符号距离（内部为正），并给出朝外（下坡）的单位方向
export function polyDist(pt, poly) {
  let best = 1e9, bx = 0, bz = 0;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [ax, az] = poly[j], [cx, cz] = poly[i]; const ex = cx - ax, ez = cz - az; const L2 = ex * ex + ez * ez || 1e-9;
    const u = Math.max(0, Math.min(1, ((pt[0] - ax) * ex + (pt[1] - az) * ez) / L2)); const qx = ax + ex * u, qz = az + ez * u;
    const d = (pt[0] - qx) ** 2 + (pt[1] - qz) ** 2; if (d < best) { best = d; bx = qx; bz = qz; }
  }
  const d = Math.sqrt(best), ins = pip(pt, poly); const nx = (bx - pt[0]) / (d || 1), nz = (bz - pt[1]) / (d || 1);
  return { d: ins ? d : -d, nx: ins ? nx : -nx, nz: ins ? nz : -nz };
}
// 坡宽：西坡与东坡可以不同
export function slopeW(h, x) { const bb = h.bb || (h.bb = bbox(h.pts)); if (h.w1 == null) return h.w0; const u = Math.max(0, Math.min(1, (x - bb[0]) / (bb[2] - bb[0]))); return h.w0 + (h.w1 - h.w0) * u * u * (3 - 2 * u); }
function bbox(pts) { let a = 1e9, b = 1e9, c = -1e9, d = -1e9; for (const [x, z] of pts) { a = Math.min(a, x); b = Math.min(b, z); c = Math.max(c, x); d = Math.max(d, z); } return [a, b, c, d]; }
const hit = (bb, v, m = 0) => !(bb[2] < v.x0 - m || bb[0] > v.x1 + m || bb[3] < v.z0 - m || bb[1] > v.z1 + m);

function smoothPath(ctx, pts, closed) {
  const n = pts.length; if (n < 2) return;
  if (!closed) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < n - 1; i++) { const mx = (pts[i][0] + pts[i + 1][0]) / 2, mz = (pts[i][1] + pts[i + 1][1]) / 2; ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, mz); }
    ctx.lineTo(pts[n - 1][0], pts[n - 1][1]); return;
  }
  const m = i => [(pts[i % n][0] + pts[(i + 1) % n][0]) / 2, (pts[i % n][1] + pts[(i + 1) % n][1]) / 2];
  const s = m(0); ctx.moveTo(s[0], s[1]);
  for (let i = 1; i <= n; i++) { const p = pts[i % n], e = m(i); ctx.quadraticCurveTo(p[0], p[1], e[0], e[1]); }
  ctx.closePath();
}
// 手抖：沿线加小幅确定性扰动
function wobble(pts, amp, seed, step = 0.06) {
  const r = rng(seed); const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, az] = pts[i], [bx, bz] = pts[i + 1]; const L = Math.hypot(bx - ax, bz - az); const n = Math.max(1, Math.round(L / step));
    for (let k = 0; k < n; k++) { const u = k / n; out.push([ax + (bx - ax) * u + (r() - .5) * amp, az + (bz - az) * u + (r() - .5) * amp]); }
  }
  out.push(pts[pts.length - 1]); return out;
}
function closeWobble(pts, amp, seed, step) { const p = wobble(pts.concat([pts[0]]), amp, seed, step); p.pop(); return p; }

export function planMap(data, seed = 7) {
  const [W, H] = data.size, m = data.margin || 0.3;
  const fx0 = -W / 2 + m, fz0 = -H / 2 + m, fx1 = W / 2 - m, fz1 = H / 2 - m;
  const R = rng(seed);
  const plan = { data, frame: [fx0, fz0, fx1, fz1], fields: [], woods: [], houses: [], hach: [], stains: [], frost: [], deckle: [] };
  // 纸边：略不齐的手撕边
  {
    const r = rng(seed + 1), pts = [], step = 0.05, j = 0.018;
    const edge = (ax, az, bx, bz) => { const L = Math.hypot(bx - ax, bz - az), n = Math.round(L / step); for (let i = 0; i < n; i++) { const u = i / n; pts.push([ax + (bx - ax) * u + (r() - .5) * j, az + (bz - az) * u + (r() - .5) * j]); } };
    const x0 = -W / 2 + 0.03, z0 = -H / 2 + 0.03, x1 = W / 2 - 0.03, z1 = H / 2 - 0.03;
    edge(x0, z0, x1, z0); edge(x1, z0, x1, z1); edge(x1, z1, x0, z1); edge(x0, z1, x0, z0);
    plan.deckle = pts;
  }
  // 污渍与发黄
  for (let i = 0; i < 26; i++) plan.stains.push({ x: (R() - .5) * W, z: (R() - .5) * H, r: 0.6 + R() * 2.4, a: 0.035 + R() * 0.06, warm: R() });
  const avoid = [];
  for (const p of data.ponds || []) avoid.push(q => pip(q, p.pts));
  for (const v of data.villages || []) avoid.push(q => Math.hypot(q[0] - v.at[0], q[1] - v.at[1]) < v.r * 0.75);
  // 田块：抖动网格，再切成窄长条（摩拉维亚的条田）
  const cw = 0.52, ch = 0.44; const nx = Math.ceil((fx1 - fx0) / cw) + 1, nz = Math.ceil((fz1 - fz0) / ch) + 1;
  const V = []; for (let j = 0; j <= nz; j++) for (let i = 0; i <= nx; i++) { const ed = i === 0 || j === 0 || i === nx || j === nz; V.push([fx0 + i * cw + (ed ? 0 : (R() - .5) * cw * 0.55), fz0 + j * ch + (ed ? 0 : (R() - .5) * ch * 0.55)]); }
  const types = [
    { c: '#8f7354', a: 0.26, furrow: 0.75 }, // 翻耕的黑土
    { c: '#a58a66', a: 0.2, furrow: 0.6 },
    { c: '#f1efe6', a: 0.28, furrow: 0.18, frost: 1 }, // 白霜
    { c: '#a3a77c', a: 0.24, furrow: 0.3 }, // 冬麦
    { c: '#c8b285', a: 0.2, furrow: 0.35 }, // 麦茬
  ];
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const a = V[j * (nx + 1) + i], b = V[j * (nx + 1) + i + 1], c = V[(j + 1) * (nx + 1) + i + 1], d = V[(j + 1) * (nx + 1) + i];
    const k = 1 + Math.floor(R() * 3.2); const alongX = R() < 0.5;
    for (let s = 0; s < k; s++) {
      const u0 = s / k, u1 = (s + 1) / k; const L = (p, q, u) => [p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u];
      const poly = alongX ? [L(a, d, u0), L(b, c, u0), L(b, c, u1), L(a, d, u1)] : [L(a, b, u0), L(a, b, u1), L(d, c, u1), L(d, c, u0)];
      const cen = [(poly[0][0] + poly[2][0]) / 2, (poly[0][1] + poly[2][1]) / 2];
      if (avoid.some(f => f(cen))) continue;
      const t = types[Math.floor(R() * types.length)];
      const ang = alongX ? Math.atan2(b[1] - a[1], b[0] - a[0]) : Math.atan2(d[1] - a[1], d[0] - a[0]);
      plan.fields.push({ poly, t, ang, bb: bbox(poly), seed: Math.floor(R() * 1e9) });
      if (t.frost || R() < 0.25) for (let q = 0; q < (t.frost ? 26 : 8); q++) { const u = R(), v = R(); const p = L(L(poly[0], poly[1], u), L(poly[3], poly[2], u), v); plan.frost.push([p[0], p[1], 0.004 + R() * 0.008]); }
    }
  }
  // 树林：一团团小树冠
  for (const w of data.woods || []) {
    const bb = bbox(w.pts); const trees = [];
    for (let z = bb[1]; z < bb[3]; z += 0.07) for (let x = bb[0]; x < bb[2]; x += 0.07) {
      const p = [x + (R() - .5) * 0.06, z + (R() - .5) * 0.06]; if (!pip(p, w.pts)) continue;
      trees.push({ x: p[0], z: p[1], r: 0.026 + R() * 0.02, kind: R() < (w.conifer || 0.15) ? 1 : 0, tone: R() });
    }
    trees.sort((p, q) => p.z - q.z);
    plan.woods.push({ pts: w.pts, bb, trees });
  }
  // 村庄：沿街两排小屋 + 教堂
  for (const v of data.villages || []) {
    const n = v.n || 9; const ax = v.axis || 0; const ca = Math.cos(ax), sa = Math.sin(ax);
    for (let i = 0; i < n; i++) {
      const along = (i / (n - 1) - 0.5) * v.r * 1.7 + (R() - .5) * 0.04, side = (i % 2 ? 1 : -1) * (0.05 + R() * 0.03);
      const x = v.at[0] + ca * along - sa * side, z = v.at[1] + sa * along + ca * side;
      plan.houses.push({ x, z, w: 0.05 + R() * 0.03, d: 0.032 + R() * 0.012, ang: ax + (R() - .5) * 0.25, roof: R() < 0.55 ? '#a8563b' : '#b49058', garden: R() < 0.7 ? 1 : 0 });
    }
    if (v.church) plan.houses.push({ x: v.at[0] + sa * 0.02, z: v.at[1] - ca * 0.02, w: 0.085, d: 0.04, ang: ax, roof: '#7d6b58', church: 1 });
    v.street = [[v.at[0] - ca * v.r, v.at[1] - sa * v.r], [v.at[0] + ca * v.r, v.at[1] + sa * v.r]];
  }
  // 晕滃线：坡上一笔笔顺着下坡方向的短线，坡陡处密而深，东南坡（背光）更深
  const slopeStrokes = (h, dark, seedH) => {
    const r = rng(seedH); const bb = bbox(h.pts); const gap = h.gap || 0.03;
    for (let z = bb[1]; z < bb[3]; z += gap) for (let x = bb[0]; x < bb[2]; x += gap) {
      const p = [x + (r() - .5) * gap * 0.9, z + (r() - .5) * gap * 0.9];
      const { d, nx, nz } = polyDist(p, h.pts); if (d <= 0) continue;
      const W = slopeW(h, p[0]); if (d >= W) continue;
      const u = d / W; const steep = 4 * u * (1 - u) * 0.8 + 0.2;
      if (r() > 0.35 + 0.65 * steep) continue;
      const l = (0.022 + 0.022 * steep) * (0.7 + r() * 0.6);
      const shade = clamp(0.4 + 0.6 * (nx * 0.55 + nz * 0.83));
      plan.hach.push([p[0], p[1], p[0] + nx * l, p[1] + nz * l, dark * steep * (0.55 + 0.45 * shade)]);
    }
  };
  let hs = 100;
  for (const h of data.hills || []) slopeStrokes({ gap: 0.036, ...h }, 0.5, hs++);
  for (const h of data.ridges || []) slopeStrokes({ w0: 0.32, gap: 0.04, ...h }, 0.34, hs++);
  // 零散的树和树篱：田边一颗颗小树，近看是地面的细节
  const trees = []; plan.lone = trees;
  const nLone = Math.round((fx1 - fx0) * (fz1 - fz0) * (data.lone ?? 4));
  for (let i = 0; i < nLone; i++) { const p = [fx0 + R() * (fx1 - fx0), fz0 + R() * (fz1 - fz0)]; if (avoid.some(f => f(p))) continue; trees.push([p[0], p[1], 0.008 + R() * 0.008, R()]); }
  plan.bbs = {
    ponds: (data.ponds || []).map(p => bbox(p.pts)), streams: (data.streams || []).map(s => bbox(s.pts)), roads: (data.roads || []).map(s => bbox(s.pts)),
  };
  // 河、路的手抖版本
  plan.streams = (data.streams || []).map((s, i) => ({ ...s, wp: wobble(s.pts, 0.012, 300 + i, 0.08) }));
  plan.roads = (data.roads || []).map((s, i) => ({ ...s, wp: wobble(s.pts, 0.01, 400 + i, 0.1) }));
  plan.ponds = (data.ponds || []).map((s, i) => ({ ...s, wp: closeWobble(s.pts, 0.01, 500 + i, 0.06) }));
  return plan;
}

/** 把计划画进视窗 view = { x0, z0, x1, z1, W, H }（世界矩形 → 画布像素），ice: 冰面贴图（可缺） */
export function drawMapView(plan, ctx, view, assets = {}) {
  const { data } = plan; const [MW, MH] = data.size;
  const sx = view.W / (view.x1 - view.x0), sz = view.H / (view.z1 - view.z0);
  const px = 1 / sx; // 一个像素等于多少世界单位
  ctx.save();
  ctx.clearRect(0, 0, view.W, view.H);
  ctx.setTransform(sx, 0, 0, sz, -view.x0 * sx, -view.z0 * sz);
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  // 纸
  ctx.beginPath(); plan.deckle.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath();
  ctx.fillStyle = PAPER; ctx.fill();
  ctx.save(); ctx.clip();
  for (const s of plan.stains) {
    if (s.x + s.r < view.x0 || s.x - s.r > view.x1 || s.z + s.r < view.z0 || s.z - s.r > view.z1) continue;
    const g = ctx.createRadialGradient(s.x, s.z, 0, s.x, s.z, s.r);
    const c = s.warm > 0.5 ? '150,105,55' : '120,100,70';
    g.addColorStop(0, `rgba(${c},${s.a})`); g.addColorStop(0.75, `rgba(${c},${s.a * 0.6})`); g.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = g; ctx.fillRect(s.x - s.r, s.z - s.r, s.r * 2, s.r * 2);
  }
  // 四周泛黄
  const edgeG = (x0, z0, x1, z1) => { const g = ctx.createLinearGradient(x0, z0, x1, z1); g.addColorStop(0, 'rgba(140,96,48,.22)'); g.addColorStop(1, 'rgba(140,96,48,0)'); return g; };
  ctx.fillStyle = edgeG(-MW / 2, 0, -MW / 2 + 0.9, 0); ctx.fillRect(-MW / 2, -MH / 2, 0.9, MH);
  ctx.fillStyle = edgeG(MW / 2, 0, MW / 2 - 0.9, 0); ctx.fillRect(MW / 2 - 0.9, -MH / 2, 0.9, MH);
  ctx.fillStyle = edgeG(0, -MH / 2, 0, -MH / 2 + 0.9); ctx.fillRect(-MW / 2, -MH / 2, MW, 0.9);
  ctx.fillStyle = edgeG(0, MH / 2, 0, MH / 2 - 0.9); ctx.fillRect(-MW / 2, MH / 2 - 0.9, MW, 0.9);
  const [fx0, fz0, fx1, fz1] = plan.frame;
  ctx.save(); ctx.beginPath(); ctx.rect(fx0, fz0, fx1 - fx0, fz1 - fz0); ctx.clip();
  // 田
  for (const f of plan.fields) {
    if (!hit(f.bb, view, 0.05)) continue;
    ctx.beginPath(); f.poly.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath();
    ctx.globalAlpha = f.t.a; ctx.fillStyle = f.t.c; ctx.fill();
    ctx.globalAlpha = 0.22; ctx.strokeStyle = '#6e5840'; ctx.lineWidth = Math.max(px * 0.8, 0.0035); ctx.stroke();
    if (f.t.furrow > 0.2) {
      ctx.save(); ctx.clip(); ctx.globalAlpha = 0.1 * f.t.furrow / 0.75 + 0.03; ctx.strokeStyle = '#3e2f22'; ctx.lineWidth = Math.max(px * 0.6, 0.0028);
      const c = Math.cos(f.ang), s = Math.sin(f.ang); const cx = (f.bb[0] + f.bb[2]) / 2, cz = (f.bb[1] + f.bb[3]) / 2; const R = Math.hypot(f.bb[2] - f.bb[0], f.bb[3] - f.bb[1]);
      ctx.beginPath();
      for (let o = -R; o < R; o += 0.03) { ctx.moveTo(cx - c * R - s * o, cz - s * R + c * o); ctx.lineTo(cx + c * R - s * o, cz + s * R + c * o); }
      ctx.stroke(); ctx.restore();
    }
  }
  ctx.globalAlpha = 1;
  // 白霜点
  ctx.fillStyle = 'rgba(255,255,255,.55)';
  for (const [x, z, r] of plan.frost) { if (x < view.x0 || x > view.x1 || z < view.z0 || z > view.z1) continue; ctx.beginPath(); ctx.arc(x, z, Math.max(r, px * 0.8), 0, 6.283); ctx.fill(); }
  // 高地底色
  for (const h of data.hills || []) { ctx.beginPath(); smoothPath(ctx, h.pts, true); ctx.fillStyle = 'rgba(176,140,86,.16)'; ctx.fill(); }
  for (const h of data.ridges || []) { ctx.beginPath(); smoothPath(ctx, h.pts, true); ctx.fillStyle = 'rgba(176,140,86,.09)'; ctx.fill(); }
  // 残雪
  (data.snow || []).forEach((sn, i) => {
    // 软边：先描一圈宽而淡的边，再填实心；里面几道风吹出的浅灰弧线
    ctx.beginPath(); smoothPath(ctx, sn, true); ctx.strokeStyle = 'rgba(248,249,250,.3)'; ctx.lineWidth = 0.07; ctx.stroke(); ctx.lineWidth = 0.035; ctx.stroke();
    ctx.fillStyle = 'rgba(249,250,251,.86)'; ctx.fill();
    ctx.save(); ctx.clip(); const r = rng(900 + i); const bb = bbox(sn);
    ctx.strokeStyle = 'rgba(140,155,175,.22)'; ctx.lineWidth = Math.max(px, 0.005);
    for (let k = 0; k < 7; k++) { const cx = bb[0] + r() * (bb[2] - bb[0]), cz = bb[1] + r() * (bb[3] - bb[1]), rw = 0.12 + r() * 0.2; ctx.beginPath(); ctx.ellipse(cx, cz, rw, rw * 0.3, -0.15, Math.PI * 1.1, Math.PI * 1.9); ctx.stroke(); }
    ctx.fillStyle = 'rgba(120,110,95,.28)'; for (let k = 0; k < 22; k++) { ctx.beginPath(); ctx.arc(bb[0] + r() * (bb[2] - bb[0]), bb[1] + r() * (bb[3] - bb[1]), 0.004 + r() * 0.006, 0, 6.283); ctx.fill(); }
    ctx.restore();
  });
  // 田边的小树
  for (const [x, z, r, k] of plan.lone || []) {
    if (x < view.x0 - 0.05 || x > view.x1 + 0.05 || z < view.z0 - 0.05 || z > view.z1 + 0.05) continue;
    ctx.fillStyle = 'rgba(60,45,30,.14)'; ctx.beginPath(); ctx.ellipse(x + r * 0.5, z + r * 0.4, r, r * 0.75, 0, 0, 6.283); ctx.fill();
    ctx.globalAlpha = 0.8; ctx.fillStyle = k < 0.5 ? '#94825f' : '#858060'; ctx.beginPath(); ctx.arc(x, z, r, 0, 6.283); ctx.fill();
    ctx.strokeStyle = INK; ctx.globalAlpha = 0.45; ctx.lineWidth = Math.max(px * 0.6, 0.002); ctx.stroke(); ctx.globalAlpha = 1;
  }
  // 晕渲
  ctx.lineWidth = Math.max(px * 0.8, 0.0032); ctx.strokeStyle = INK;
  for (const [x0, z0, x1, z1, a] of plan.hach) {
    if (x0 < view.x0 - 0.1 || x0 > view.x1 + 0.1 || z0 < view.z0 - 0.1 || z0 > view.z1 + 0.1) continue;
    ctx.globalAlpha = Math.min(1, a); ctx.beginPath(); ctx.moveTo(x0, z0); ctx.lineTo(x1, z1); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  // 池塘：冰面贴图裁进池形
  plan.ponds.forEach((p, i) => {
    if (!hit(plan.bbs.ponds[i], view, 0.1)) return;
    ctx.save(); ctx.beginPath(); smoothPath(ctx, p.wp, true);
    ctx.fillStyle = '#a7c3cf'; ctx.fill();
    if (assets.ice) { ctx.clip(); const bb = plan.bbs.ponds[i]; const s = Math.max(bb[2] - bb[0], bb[3] - bb[1]) * 1.1; ctx.globalAlpha = 0.42; ctx.drawImage(assets.ice, (bb[0] + bb[2]) / 2 - s / 2, (bb[1] + bb[3]) / 2 - s / 3, s, s * 0.667); ctx.globalAlpha = 1; }
    ctx.restore();
    ctx.beginPath(); smoothPath(ctx, p.wp, true); ctx.strokeStyle = '#3f5562'; ctx.lineWidth = Math.max(px * 1.2, 0.007); ctx.stroke();
    // 岸边水线
    ctx.save(); ctx.globalAlpha = 0.45; ctx.lineWidth = Math.max(px * 0.7, 0.003);
    for (let k = 1; k <= 2; k++) { ctx.beginPath(); const cx = (plan.bbs.ponds[i][0] + plan.bbs.ponds[i][2]) / 2, cz = (plan.bbs.ponds[i][1] + plan.bbs.ponds[i][3]) / 2; smoothPath(ctx, p.wp.map(q => [cx + (q[0] - cx) * (1 + 0.06 * k), cz + (q[1] - cz) * (1 + 0.12 * k)]), true); ctx.stroke(); }
    ctx.restore();
  });
  // 河
  plan.streams.forEach((s, i) => {
    if (!hit(plan.bbs.streams[i], view, 0.1)) return;
    const w = s.w || 0.03;
    ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = '#3f5562'; ctx.lineWidth = w + 0.012; ctx.stroke();
    ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = '#8fa9b4'; ctx.lineWidth = w; ctx.stroke();
    ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = 'rgba(235,242,240,.55)'; ctx.lineWidth = w * 0.25; ctx.stroke();
  });
  // 路
  plan.roads.forEach((s, i) => {
    if (!hit(plan.bbs.roads[i], view, 0.1)) return;
    if (s.main) {
      const w = s.w || 1;
      ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = '#5f4630'; ctx.lineWidth = 0.05 * w; ctx.stroke();
      ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = s.ruts ? '#a88f6a' : '#e4d3ab'; ctx.lineWidth = 0.05 * w - 0.014; ctx.stroke();
      if (s.ruts) { // 冬天的驿路：泥色路面，两道压深的车辙（按 rutAxis 平移出两条）
        ctx.save(); ctx.strokeStyle = 'rgba(72,52,32,.55)'; ctx.lineWidth = 0.008 * w; ctx.setLineDash([0.12, 0.03, 0.05, 0.02]);
        for (const d of [-0.011 * w, 0.011 * w]) { ctx.save(); if (s.rutAxis === 'x') ctx.translate(d, 0); else ctx.translate(0, d); ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.stroke(); ctx.restore(); }
        ctx.restore();
      }
      // 路边行道树
      ctx.fillStyle = '#6a5a3c';
      for (let k = 0; k < s.wp.length; k += 2) { const p = s.wp[k], q = s.wp[Math.min(s.wp.length - 1, k + 1)]; const dx = q[0] - p[0], dz = q[1] - p[1], L = Math.hypot(dx, dz) || 1; for (const sd of [-1, 1]) { ctx.beginPath(); ctx.arc(p[0] - dz / L * 0.04 * (s.w || 1) * sd, p[1] + dx / L * 0.04 * (s.w || 1) * sd, 0.009, 0, 6.283); ctx.fill(); } }
    } else {
      ctx.beginPath(); smoothPath(ctx, s.wp, false); ctx.strokeStyle = '#6b5038'; ctx.lineWidth = 0.011; ctx.setLineDash([0.04, 0.025]); ctx.stroke(); ctx.setLineDash([]);
    }
  });
  // 树林
  for (const w of plan.woods) {
    if (!hit(w.bb, view, 0.1)) continue;
    ctx.beginPath(); smoothPath(ctx, w.pts, true); ctx.fillStyle = 'rgba(120,118,80,.18)'; ctx.fill();
    for (const t of w.trees) {
      if (t.x < view.x0 - 0.1 || t.x > view.x1 + 0.1 || t.z < view.z0 - 0.1 || t.z > view.z1 + 0.1) continue;
      ctx.fillStyle = 'rgba(60,45,30,.22)'; ctx.beginPath(); ctx.ellipse(t.x + t.r * 0.45, t.z + t.r * 0.35, t.r, t.r * 0.8, 0, 0, 6.283); ctx.fill();
      if (t.kind) { ctx.beginPath(); ctx.moveTo(t.x, t.z - t.r * 1.5); ctx.lineTo(t.x + t.r * 0.9, t.z + t.r * 0.7); ctx.lineTo(t.x - t.r * 0.9, t.z + t.r * 0.7); ctx.closePath(); ctx.fillStyle = '#5f6d4c'; }
      else { ctx.beginPath(); ctx.arc(t.x, t.z, t.r, 0, 6.283); ctx.fillStyle = t.tone < 0.5 ? '#8a7650' : '#7b7a55'; }
      ctx.fill(); ctx.strokeStyle = INK; ctx.lineWidth = Math.max(px * 0.8, 0.0032); ctx.globalAlpha = 0.8; ctx.stroke(); ctx.globalAlpha = 1;
    }
  }
  // 房屋
  for (const h of plan.houses) {
    if (h.x < view.x0 - 0.2 || h.x > view.x1 + 0.2 || h.z < view.z0 - 0.2 || h.z > view.z1 + 0.2) continue;
    ctx.save(); ctx.translate(h.x, h.z); ctx.rotate(h.ang);
    if (h.garden) { ctx.fillStyle = 'rgba(150,160,110,.35)'; ctx.fillRect(-h.w / 2 - 0.01, h.d / 2, h.w + 0.02, h.d * 1.3); ctx.strokeStyle = 'rgba(70,55,35,.5)'; ctx.lineWidth = Math.max(px * 0.6, 0.002); ctx.strokeRect(-h.w / 2 - 0.01, h.d / 2, h.w + 0.02, h.d * 1.3); }
    ctx.fillStyle = 'rgba(50,35,20,.3)'; ctx.fillRect(-h.w / 2 + 0.008, -h.d / 2 + 0.008, h.w, h.d);
    ctx.fillStyle = '#efe6d2'; ctx.fillRect(-h.w / 2, -h.d / 2, h.w, h.d);
    ctx.fillStyle = h.roof; ctx.fillRect(-h.w / 2, -h.d / 2, h.w, h.d * 0.72);
    ctx.fillStyle = 'rgba(0,0,0,.2)'; ctx.fillRect(-h.w / 2, -h.d * 0.14, h.w, h.d * 0.36);
    ctx.strokeStyle = 'rgba(40,25,15,.6)'; ctx.lineWidth = Math.max(px * 0.6, 0.002); ctx.beginPath(); ctx.moveTo(-h.w / 2, -h.d * 0.14); ctx.lineTo(h.w / 2, -h.d * 0.14); ctx.stroke();
    ctx.strokeStyle = INK; ctx.lineWidth = Math.max(px * 0.8, 0.003); ctx.strokeRect(-h.w / 2, -h.d / 2, h.w, h.d);
    if (h.church) { ctx.fillStyle = '#efe6d2'; ctx.fillRect(h.w / 2 - 0.004, -0.018, 0.03, 0.036); ctx.strokeRect(h.w / 2 - 0.004, -0.018, 0.03, 0.036); ctx.beginPath(); ctx.moveTo(h.w / 2 + 0.011, -0.03); ctx.lineTo(h.w / 2 + 0.011, -0.05); ctx.moveTo(h.w / 2 + 0.002, -0.042); ctx.lineTo(h.w / 2 + 0.02, -0.042); ctx.stroke(); }
    ctx.restore();
  }
  ctx.restore(); // 图框裁剪
  // 图框：双线 + 角花 + 指北
  ctx.strokeStyle = INK; ctx.globalAlpha = 0.85;
  ctx.lineWidth = 0.018; ctx.strokeRect(fx0, fz0, fx1 - fx0, fz1 - fz0);
  ctx.lineWidth = 0.006; ctx.strokeRect(fx0 - 0.07, fz0 - 0.07, fx1 - fx0 + 0.14, fz1 - fz0 + 0.14);
  // 刻度条纹
  ctx.lineWidth = 0.03; for (let x = fx0; x < fx1; x += 0.5) { if (Math.round((x - fx0) / 0.5) % 2) continue; ctx.beginPath(); ctx.moveTo(x, fz0 - 0.035); ctx.lineTo(Math.min(fx1, x + 0.5), fz0 - 0.035); ctx.moveTo(x, fz1 + 0.035); ctx.lineTo(Math.min(fx1, x + 0.5), fz1 + 0.035); ctx.stroke(); }
  for (let z = fz0; z < fz1; z += 0.5) { if (Math.round((z - fz0) / 0.5) % 2) continue; ctx.beginPath(); ctx.moveTo(fx0 - 0.035, z); ctx.lineTo(fx0 - 0.035, Math.min(fz1, z + 0.5)); ctx.moveTo(fx1 + 0.035, z); ctx.lineTo(fx1 + 0.035, Math.min(fz1, z + 0.5)); ctx.stroke(); }
  ctx.globalAlpha = 1;
  if (data.compass) drawCompass(ctx, data.compass[0], data.compass[1], data.compass[2] || 0.55);
  ctx.restore(); // deckle clip
  ctx.restore();
}

function drawCompass(ctx, x, z, r) {
  ctx.save(); ctx.translate(x, z);
  ctx.strokeStyle = INK; ctx.lineWidth = 0.008;
  ctx.beginPath(); ctx.arc(0, 0, r * 0.62, 0, 6.283); ctx.stroke();
  ctx.beginPath(); ctx.arc(0, 0, r * 0.56, 0, 6.283); ctx.stroke();
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4 - Math.PI / 2, L = i % 2 ? r * 0.55 : r, w = i % 2 ? r * 0.08 : r * 0.13;
    const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(a + Math.PI / 2), sb = Math.sin(a + Math.PI / 2);
    for (const side of [1, -1]) {
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(ca * L, sa * L); ctx.lineTo(cb * w * side, sb * w * side); ctx.closePath();
      ctx.fillStyle = side > 0 ? (i === 0 ? '#8a2f24' : '#4a3726') : '#efe6d2'; ctx.fill(); ctx.stroke();
    }
  }
  // 北端的百合花饰
  ctx.translate(0, -r * 1.06); ctx.fillStyle = '#8a2f24';
  ctx.beginPath(); ctx.moveTo(0, -r * 0.16); ctx.quadraticCurveTo(r * 0.06, -r * 0.05, 0, r * 0.02); ctx.quadraticCurveTo(-r * 0.06, -r * 0.05, 0, -r * 0.16); ctx.fill(); ctx.stroke();
  for (const s of [1, -1]) { ctx.beginPath(); ctx.moveTo(0, r * 0.0); ctx.quadraticCurveTo(s * r * 0.14, -r * 0.1, s * r * 0.1, r * 0.04); ctx.quadraticCurveTo(s * r * 0.05, r * 0.0, 0, r * 0.03); ctx.fill(); ctx.stroke(); }
  ctx.restore();
}
