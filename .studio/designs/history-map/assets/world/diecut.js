// 模切：给透明底的图加一圈白色纸边、填掉内部空洞、压一层纸纹，并描出外轮廓（给纸片做厚度和投影）。
import { canvas } from './util.js';

function edt1d(f, n, d, v, z) {
  let k = 0; v[0] = 0; z[0] = -1e30; z[1] = 1e30;
  for (let q = 1; q < n; q++) {
    let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]); }
    k++; v[k] = q; z[k] = s; z[k + 1] = 1e30;
  }
  k = 0;
  for (let q = 0; q < n; q++) { while (z[k + 1] < q) k++; const dq = q - v[k]; d[q] = dq * dq + f[v[k]]; }
}
// 到最近「内部」像素的平方距离（Felzenszwalb）
function edt(mask, W, H) {
  const g = new Float64Array(W * H);
  for (let i = 0; i < W * H; i++) g[i] = mask[i] ? 0 : 1e20;
  const n = Math.max(W, H), f = new Float64Array(n), d = new Float64Array(n), v = new Int32Array(n), z = new Float64Array(n + 1);
  for (let x = 0; x < W; x++) { for (let y = 0; y < H; y++) f[y] = g[y * W + x]; edt1d(f, H, d, v, z); for (let y = 0; y < H; y++) g[y * W + x] = d[y]; }
  for (let y = 0; y < H; y++) { const o = y * W; for (let x = 0; x < W; x++) f[x] = g[o + x]; edt1d(f, W, d, v, z); for (let x = 0; x < W; x++) g[o + x] = d[x]; }
  return g;
}

function traceBoundary(lab, id, sx, sy, gw, gh) {
  const inside = (x, y) => x >= 0 && y >= 0 && x < gw && y < gh && lab[y * gw + x] === id;
  let x = sx, y = sy, dx = 1, dy = 0; const pts = [[x, y]]; let guard = 0;
  do {
    x += dx; y += dy;
    let fl, fr;
    if (dx === 1) { fl = inside(x, y - 1); fr = inside(x, y); }
    else if (dy === 1) { fl = inside(x, y); fr = inside(x - 1, y); }
    else if (dx === -1) { fl = inside(x - 1, y); fr = inside(x - 1, y - 1); }
    else { fl = inside(x - 1, y - 1); fr = inside(x, y - 1); }
    let nx, ny;
    if (fl) { nx = dy; ny = -dx; } else if (fr) { nx = dx; ny = dy; } else { nx = -dy; ny = dx; }
    if (nx !== dx || ny !== dy) pts.push([x, y]);
    dx = nx; dy = ny;
  } while (!(x === sx && y === sy && dx === 1 && dy === 0) && ++guard < 2e6);
  const l = pts[pts.length - 1]; if (l[0] === pts[0][0] && l[1] === pts[0][1]) pts.pop();
  return pts;
}

function dp(pts, eps) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1;
  const st = [[0, pts.length - 1]];
  while (st.length) {
    const [a, b] = st.pop(); const [ax, ay] = pts[a], [bx, by] = pts[b];
    const L = Math.hypot(bx - ax, by - ay) || 1e-9; let md = -1, mi = -1;
    for (let i = a + 1; i < b; i++) { const d = Math.abs((bx - ax) * (ay - pts[i][1]) - (ax - pts[i][0]) * (by - ay)) / L; if (d > md) { md = d; mi = i; } }
    if (md > eps) { keep[mi] = 1; st.push([a, mi], [mi, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}
function simplifyClosed(pts, eps) {
  // 从离起点最远的点切开成两段分别简化
  let far = 0, fd = -1; for (let i = 0; i < pts.length; i++) { const d = (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2; if (d > fd) { fd = d; far = i; } }
  const a = dp(pts.slice(0, far + 1), eps), b = dp(pts.slice(far).concat([pts[0]]), eps);
  return a.slice(0, -1).concat(b.slice(0, -1));
}

let GRAIN = null; // { data: Uint8Array, w, h }
export function setGrain(img) {
  const c = canvas(img.width, img.height), x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const d = x.getImageData(0, 0, c.width, c.height).data, g = new Uint8Array(c.width * c.height);
  for (let i = 0; i < g.length; i++) g[i] = d[i * 4];
  GRAIN = { data: g, w: c.width, h: c.height };
}
export function grainAt(x, y) { if (!GRAIN) return 128; return GRAIN.data[((y % GRAIN.h) * GRAIN.w) + (x % GRAIN.w)]; }

/**
 * src: Image/Canvas（透明底）。返回 { canvas, aspect, polys: [[[u,v]...]], floorV }
 * opts.border 纸边宽度（占长边比例），opts.fill 是否填内部空洞（细枝条类给 false）
 */
export function diecut(src, opts = {}) {
  const { maxSize = 1400, border = 0.013, minBorder = 4, paper = [246, 241, 230], edge = [196, 186, 168], fill = true, grain = 0.55, cut = 90, flipX = false, trim = 0 } = opts;
  let sx = 0, sy = 0, sw = src.naturalWidth || src.width, sh = src.naturalHeight || src.height;
  // trim：按 alpha ≥ trim 的外接框裁掉透明边（生图四角常有 1/255 的噪声）
  if (trim) {
    const t = canvas(sw, sh), tx = t.getContext('2d', { willReadFrequently: true }); tx.drawImage(src, 0, 0);
    const d = tx.getImageData(0, 0, sw, sh).data; let x0 = sw, y0 = sh, x1 = -1, y1 = -1;
    for (let yy = 0; yy < sh; yy++) for (let xx = 0; xx < sw; xx++) if (d[(yy * sw + xx) * 4 + 3] >= trim) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; if (yy < y0) y0 = yy; if (yy > y1) y1 = yy; }
    if (x1 >= x0) { sx = x0; sy = y0; sw = x1 - x0 + 1; sh = y1 - y0 + 1; }
  }
  const s = Math.min(1, maxSize / Math.max(sw, sh));
  const w0 = Math.round(sw * s), h0 = Math.round(sh * s);
  const b = Math.max(minBorder, Math.round(border * Math.max(w0, h0)));
  const pad = b + 4, W = w0 + 2 * pad, H = h0 + 2 * pad;
  const c = canvas(W, H), x = c.getContext('2d', { willReadFrequently: true });
  if (flipX) { x.save(); x.translate(W, 0); x.scale(-1, 1); }
  x.drawImage(src, sx, sy, sw, sh, pad, pad, w0, h0);
  if (flipX) x.restore();
  const art = x.getImageData(0, 0, W, H);
  const N = W * H, A = new Uint8Array(N);
  for (let i = 0; i < N; i++) A[i] = art.data[i * 4 + 3] >= cut ? 1 : 0;
  const D = edt(A, W, H);
  const thr = (b + 0.5) * (b + 0.5);
  // 外部：从边框泛洪，穿过距离 > 纸边的像素
  const out = new Uint8Array(N); const st = [];
  const push = i => { if (!out[i] && D[i] > thr) { out[i] = 1; st.push(i); } };
  for (let xx = 0; xx < W; xx++) { push(xx); push((H - 1) * W + xx); }
  for (let yy = 0; yy < H; yy++) { push(yy * W); push(yy * W + W - 1); }
  while (st.length) { const i = st.pop(), xx = i % W, yy = (i / W) | 0; if (xx > 0) push(i - 1); if (xx < W - 1) push(i + 1); if (yy > 0) push(i - W); if (yy < H - 1) push(i + W); }
  // 纸边层 + 原画叠上去
  const pl = x.createImageData(W, H), pd = pl.data;
  const cov = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let a = 0;
    if (!out[i]) {
      const d = Math.sqrt(D[i]);
      if (!fill && d > b + 0.5) a = 0; // 不填洞：洞里保持透明
      else a = d <= b - 0.5 ? 1 : (d > b + 0.5 ? 1 : (b + 0.5 - d));
    }
    cov[i] = a;
    const d = Math.sqrt(D[i]);
    const e = a > 0 ? Math.max(0, Math.min(1, (d - (b - 2.2)) / 1.6)) : 0; // 外沿一圈略深的切口
    pd[i * 4] = paper[0] + (edge[0] - paper[0]) * e;
    pd[i * 4 + 1] = paper[1] + (edge[1] - paper[1]) * e;
    pd[i * 4 + 2] = paper[2] + (edge[2] - paper[2]) * e;
    pd[i * 4 + 3] = a * 255;
  }
  // 合成：纸边在下，原画在上；再统一压纸纹
  const fin = pd;
  for (let i = 0; i < N; i++) {
    const sa = art.data[i * 4 + 3] / 255; if (sa <= 0) continue;
    const da = fin[i * 4 + 3] / 255; const oa = sa + da * (1 - sa);
    for (let k = 0; k < 3; k++) fin[i * 4 + k] = (art.data[i * 4 + k] * sa + fin[i * 4 + k] * da * (1 - sa)) / (oa || 1);
    fin[i * 4 + 3] = oa * 255;
  }
  if (GRAIN && grain > 0) {
    for (let yy = 0; yy < H; yy++) for (let xx = 0; xx < W; xx++) {
      const i = yy * W + xx; if (!fin[i * 4 + 3]) continue;
      const g = 1 + (grainAt(xx, yy) - 128) / 512 * grain;
      fin[i * 4] *= g; fin[i * 4 + 1] *= g; fin[i * 4 + 2] *= g;
    }
  }
  x.putImageData(pl, 0, 0);

  // 轮廓：降采样网格（任一像素在内即在内），连通块逐个描边
  const k = Math.max(1, Math.round(Math.max(W, H) / 300));
  const gw = Math.ceil(W / k) + 2, gh = Math.ceil(H / k) + 2; // 外圈留空
  const M = new Uint8Array(gw * gh);
  for (let yy = 0; yy < H; yy++) for (let xx = 0; xx < W; xx++) if (cov[yy * W + xx] > 0.35) M[((yy / k | 0) + 1) * gw + (xx / k | 0) + 1] = 1;
  if (!fill) { // 不填洞的纸片：轮廓用闭运算后的粗外形（只给投影和厚度用）
    const r = 3; const M2 = new Uint8Array(M);
    for (let yy = 0; yy < gh; yy++) for (let xx = 0; xx < gw; xx++) if (M[yy * gw + xx]) for (let oy = -r; oy <= r; oy++) for (let ox = -r; ox <= r; ox++) { const X = xx + ox, Y = yy + oy; if (X >= 0 && Y >= 0 && X < gw && Y < gh) M2[Y * gw + X] = 1; }
    M.set(M2);
  }
  const lab = new Int32Array(gw * gh); let nl = 0; const comps = [];
  for (let i = 0; i < gw * gh; i++) {
    if (!M[i] || lab[i]) continue;
    nl++; let cnt = 0; const q = [i]; lab[i] = nl;
    while (q.length) {
      const j = q.pop(); cnt++; const jx = j % gw, jy = (j / gw) | 0;
      for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) {
        const X = jx + ox, Y = jy + oy; if (X < 0 || Y < 0 || X >= gw || Y >= gh) continue;
        const n = Y * gw + X; if (M[n] && !lab[n]) { lab[n] = nl; q.push(n); }
      }
    }
    comps.push({ id: nl, cnt, sx: i % gw, sy: (i / gw) | 0 });
  }
  const total = comps.reduce((s, c) => s + c.cnt, 0);
  const polys = [];
  for (const cp of comps) {
    if (cp.cnt < total * 0.004) continue;
    let p = traceBoundary(lab, cp.id, cp.sx, cp.sy, gw, gh);
    p = simplifyClosed(p, 0.85);
    polys.push(p.map(([gx, gy]) => [((gx - 1) * k) / W, 1 - ((gy - 1) * k) / H]));
  }
  let floorV = 1; for (const p of polys) for (const q of p) floorV = Math.min(floorV, q[1]);
  // 最低处的实际纸边像素（比轮廓更准，用来把纸片的脚放在地面上）
  let lowRow = 0; for (let yy = H - 1; yy >= 0 && !lowRow; yy--) for (let xx = 0; xx < W; xx++) if (cov[yy * W + xx] > 0.5) { lowRow = yy; break; }
  // 脚的横向范围：最低 6% 的行里有纸的列
  let f0 = W, f1 = 0; const band = Math.max(3, Math.round(H * 0.06));
  for (let yy = Math.max(0, lowRow - band); yy <= lowRow; yy++) for (let xx = 0; xx < W; xx++) if (cov[yy * W + xx] > 0.5) { if (xx < f0) f0 = xx; if (xx > f1) f1 = xx; }
  // uvOf：原图像素 → 纸片 uv（v 自下而上），给炮口、枪尖这类挂点用
  const [ax, ay, aw, , as] = opts.pixelMap || [sx, sy, sw, sh, s];
  const uvOf = (qx, qy) => {
    const x = qx - ax;
    return [(pad + (flipX ? aw - x : x) * as) / W, 1 - (pad + (qy - ay) * as) / H];
  };
  return { canvas: c, aspect: W / H, polys, floorV: Math.max(floorV, 1 - (lowRow + 1) / H), foot: [f0 / W, f1 / W], px: { W, H, b }, uvOf };
}
