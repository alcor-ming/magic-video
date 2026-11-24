// 作战地图桌 · 通用小工具。全部确定性：随机只来自种子，时间只来自 t。
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, u) => a + (b - a) * u;
export const mix3 = (a, b, u) => [lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u)];
export const smooth = (e0, e1, x) => { const u = clamp((x - e0) / (e1 - e0)); return u * u * (3 - 2 * u); };
export const smoother = (e0, e1, x) => { const u = clamp((x - e0) / (e1 - e0)); return u * u * u * (u * (u * 6 - 15) + 10); };
export const ease = {
  inOut: u => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
  out: u => 1 - Math.pow(1 - u, 3),
  in: u => u * u * u,
  outBack: (u, s = 1.2) => 1 + (s + 1) * Math.pow(u - 1, 3) + s * Math.pow(u - 1, 2),
};
// 定格动画的顿挫：把时间量化到 fps 帧
export const stepT = (t, fps = 12) => Math.floor(t * fps + 1e-6) / fps;
// 0→1 的窗口进度（可选缓动 + 定格）
export function win(t, t0, t1, fn = ease.inOut, fps = 0) {
  const tt = fps ? stepT(t, fps) : t;
  return fn(clamp((tt - t0) / (t1 - t0)));
}

export function hashStr(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
export function hash1(n) { n = (n | 0) * 374761393; n = (n ^ (n >>> 13)) * 1274126177; n = n ^ (n >>> 16); return (n >>> 0) / 4294967296; }
export function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
// 一维平滑值噪声，seed 区分通道；返回 -1..1
export function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
  const a = hash1(i * 7919 + seed * 104729) * 2 - 1, b = hash1((i + 1) * 7919 + seed * 104729) * 2 - 1;
  return a + (b - a) * u;
}
export function fbm1(x, seed = 0, oct = 3) { let s = 0, a = 0.5, f = 1, n = 0; for (let o = 0; o < oct; o++) { s += a * noise1(x * f, seed + o * 31); n += a; a *= 0.5; f *= 2.03; } return s / n; }

// 关键帧轨道：keys = [[t, v], ...]，v 是数或数组；段内用 fn 缓动（默认平滑）
export function track(keys, fn = ease.inOut) {
  return t => {
    if (t <= keys[0][0]) return keys[0][1];
    const n = keys.length;
    if (t >= keys[n - 1][0]) return keys[n - 1][1];
    let i = 0; while (i < n - 2 && t > keys[i + 1][0]) i++;
    const [t0, a] = keys[i], [t1, b] = keys[i + 1];
    const u = fn(clamp((t - t0) / (t1 - t0)));
    if (typeof a === 'number') return lerp(a, b, u);
    return a.map((x, k) => lerp(x, b[k], u));
  };
}

// 三次 Hermite 样条（有限差分切线，首尾切线为 0）：给镜头用，速度连续，在关键帧之间不停顿
export function spline(keys) {
  const n = keys.length, dim = keys[0][1].length;
  // 单调三次（Fritsch–Carlson）：逐分量取两侧斜率的加权调和平均，两侧反向时取 0，关键帧之间不会冲过头
  const tan = keys.map((k, i) => {
    if (i === 0 || i === n - 1 || k[2] === 'hold') return new Array(dim).fill(0);
    const [ta, a] = keys[i - 1], [t1, p] = keys[i], [tb, b] = keys[i + 1];
    const h0 = t1 - ta, h1 = tb - t1;
    return p.map((_, d) => {
      const d0 = (p[d] - a[d]) / h0, d1 = (b[d] - p[d]) / h1;
      if (d0 * d1 <= 0) return 0;
      const w0 = 2 * h1 + h0, w1 = h1 + 2 * h0;
      return (w0 + w1) / (w0 / d0 + w1 / d1);
    });
  });
  return t => {
    if (t <= keys[0][0]) return keys[0][1].slice();
    if (t >= keys[n - 1][0]) return keys[n - 1][1].slice();
    let i = 0; while (i < n - 2 && t > keys[i + 1][0]) i++;
    const [t0, p0] = keys[i], [t1, p1] = keys[i + 1], h = t1 - t0, u = (t - t0) / h;
    const u2 = u * u, u3 = u2 * u;
    const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
    return p0.map((_, d) => h00 * p0[d] + h10 * h * tan[i][d] + h01 * p1[d] + h11 * h * tan[i + 1][d]);
  };
}

export function loadImage(url) {
  return new Promise((res, rej) => { const im = new Image(); im.crossOrigin = 'anonymous'; im.onload = () => res(im); im.onerror = () => rej(new Error('image failed: ' + url)); im.src = url; });
}

export function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

export function hexRGB(h) { const n = parseInt(h.replace('#', ''), 16); return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; }
