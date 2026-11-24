// 示范片：三皇会战 · 拿破仑视角，18 秒五个镜头。地图 → 小景 → 地图。
// 画面是 t 的纯函数：位置、出场、烟、闪光都由 t 和固定种子算出，不读 RAF/Date/Math.random。
import { createWorld, LIGHTS, mixLight, chaikin, sprites } from './vendor/components/history-map/world/v1/index.js';
import { clamp, lerp, smooth, ease, stepT, spline, rng, noise1 } from './vendor/components/history-map/world/v1/util.js';
import { battleParticles } from './vendor/components/history-map/world/v1/index.js';

export const meta = { id: 'napoleon', title: '三皇会战 · 拿破仑', dur: 18 };
const MEDIA = new URL('./media/', import.meta.url);
const PIXEL_MAP = {"gun": [19, 16, 1581, 951, 0.8855154965211891], "frCol": [65, 114, 1431, 859, 0.9783368273934312], "frFire": [10, 9, 2152, 715, 0.6505576208178439], "ruFire": [8, 47, 2161, 650, 0.6478482184173994], "auFire": [14, 12, 2075, 733, 0.6746987951807228]};
import { createPlates } from './vendor/components/history-map/plates/v1/plates.js';
const SIDES = { a: { name: '法军', color: '#2b4f8c' }, b: { name: '联军', color: '#3f6a46' } };

// ───────────── 地理（经纬度 → 地图纸面坐标；x 向东，z 向南，1 单位 ≈ 1.35 km）─────────────
const G = { lon0: 16.61, lon1: 16.87, lat0: 49.065, lat1: 49.205, W: 14, H: 11.5 };
const P = (lon, lat) => [((lon - G.lon0) / (G.lon1 - G.lon0) - 0.5) * G.W, -((lat - G.lat0) / (G.lat1 - G.lat0) - 0.5) * G.H];
const KM = 1 / 1.354;
const LL = a => a.map(([lon, lat]) => P(lon, lat));
function blob([lon, lat], rx, rz, seed, n = 12, jit = 0.14, rot = 0) {
  const r = rng(seed), [cx, cz] = P(lon, lat), out = [];
  for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2, k = 1 + (r() - 0.5) * 2 * jit, x = Math.cos(a) * rx * KM * k, z = Math.sin(a) * rz * KM * k; out.push([cx + x * Math.cos(rot) - z * Math.sin(rot), cz + x * Math.sin(rot) + z * Math.cos(rot)]); }
  return out;
}
function rough(poly, amp, seed) { const r = rng(seed); return poly.map(([x, z]) => [x + (r() - 0.5) * amp, z + (r() - 0.5) * amp]); }

const PLACE = {
  zuran: P(16.733, 49.178), santon: P(16.770, 49.192), summit: P(16.766, 49.130), pratzen: P(16.763, 49.140),
  telnitz: P(16.716, 49.101), sokolnitz: P(16.721, 49.114), kobelnitz: P(16.737, 49.141), ujezd: P(16.758, 49.104),
};
// 高地：纸面下垫着缓坡（h 高度，w0/w1 西坡/东坡宽度）。普拉岑西坡较陡、东坡缓长。
const HILLS = [
  { id: 'pratzen', h: 0.34, w0: 0.7, w1: 1.2, pts: chaikin(rough(LL([[16.745, 49.140], [16.748, 49.151], [16.760, 49.156], [16.778, 49.153], [16.795, 49.147], [16.807, 49.139], [16.805, 49.126], [16.791, 49.114], [16.775, 49.108], [16.760, 49.110], [16.750, 49.118], [16.744, 49.129]]), 0.12, 21), 3) },
  { id: 'zuran', h: 0.2, w0: 0.5, pts: chaikin(blob([16.733, 49.178], 0.75, 0.6, 31), 3) },
  { id: 'santon', h: 0.12, w0: 0.42, pts: chaikin(blob([16.770, 49.192], 0.5, 0.45, 33), 3) },
  { id: 'ujezd', h: 0.1, w0: 0.3, pts: chaikin(blob([16.762, 49.098], 0.9, 0.45, 35, 12, 0.18, 0.3), 3) },
];

const MAP = {
  size: [G.W, G.H], margin: 0.32, compass: [-6.05, 4.6, 0.5],
  hills: HILLS,
  ridges: [
    { pts: blob([16.80, 49.185], 1.6, 0.8, 41, 12, 0.2, -0.3), inner: blob([16.80, 49.185], 0.9, 0.4, 42, 10, 0.2, -0.3) },
    { pts: blob([16.845, 49.095], 1.4, 1.0, 43, 12, 0.2, 0.4), inner: blob([16.845, 49.095], 0.7, 0.5, 44, 10, 0.2, 0.4) },
    { pts: blob([16.66, 49.125], 1.2, 1.6, 45, 12, 0.2, 0.2), inner: blob([16.66, 49.125], 0.6, 0.8, 46) },
    { pts: blob([16.69, 49.19], 0.9, 0.6, 47, 12, 0.2) },
    { pts: blob([16.785, 49.072], 1.3, 0.5, 48, 12, 0.2) },
  ],
  streams: [
    { w: 0.034, pts: LL([[16.700, 49.205], [16.712, 49.188], [16.722, 49.176], [16.729, 49.166], [16.738, 49.158], [16.744, 49.151], [16.740, 49.145], [16.736, 49.139], [16.731, 49.128], [16.725, 49.118], [16.720, 49.109], [16.716, 49.100], [16.713, 49.090], [16.710, 49.083]]) },
    { w: 0.026, pts: LL([[16.776, 49.205], [16.768, 49.193], [16.761, 49.179], [16.754, 49.166], [16.748, 49.157], [16.744, 49.151]]) },
    { w: 0.03, pts: LL([[16.870, 49.150], [16.846, 49.137], [16.823, 49.124], [16.801, 49.111], [16.779, 49.100], [16.760, 49.093], [16.748, 49.091]]) },
    { w: 0.028, pts: LL([[16.705, 49.072], [16.690, 49.066]]) },
  ],
  ponds: [
    { pts: blob([16.741, 49.094], 0.95, 0.24, 51, 14, 0.12, -0.55) },
    { pts: blob([16.712, 49.077], 1.05, 0.62, 52, 16, 0.12, 0.15) },
    { pts: blob([16.729, 49.144], 0.28, 0.12, 53, 10, 0.12, 0.3) },
    { pts: blob([16.756, 49.087], 0.35, 0.15, 54, 10, 0.12, -0.2) },
  ],
  roads: [
    { main: true, pts: LL([[16.605, 49.199], [16.66, 49.197], [16.70, 49.195], [16.74, 49.193], [16.77, 49.189], [16.80, 49.192], [16.84, 49.198], [16.875, 49.204]]) },
    { main: true, pts: LL([[16.605, 49.178], [16.65, 49.174], [16.69, 49.170], [16.727, 49.167], [16.745, 49.155], [16.765, 49.150], [16.795, 49.151], [16.826, 49.146], [16.85, 49.150], [16.875, 49.152]]) },
    { main: true, pts: LL([[16.628, 49.206], [16.632, 49.15], [16.640, 49.10], [16.650, 49.062]]) },
    { main: true, pts: LL([[16.826, 49.146], [16.838, 49.125], [16.851, 49.100], [16.862, 49.082], [16.875, 49.070]]) },
    { pts: LL([[16.727, 49.167], [16.737, 49.141], [16.722, 49.114], [16.716, 49.101], [16.700, 49.085]]) },
    { pts: LL([[16.716, 49.101], [16.736, 49.103], [16.758, 49.104], [16.772, 49.099]]) },
    { pts: LL([[16.758, 49.104], [16.746, 49.092], [16.737, 49.087]]) },
    { pts: LL([[16.737, 49.141], [16.763, 49.140], [16.793, 49.137], [16.826, 49.142]]) },
    { pts: LL([[16.722, 49.114], [16.745, 49.126], [16.763, 49.140]]) },
    { pts: LL([[16.763, 49.140], [16.773, 49.118], [16.758, 49.104]]) },
    { pts: LL([[16.733, 49.178], [16.745, 49.155]]) },
    { pts: LL([[16.753, 49.164], [16.787, 49.164], [16.808, 49.175]]) },
  ],
  villages: [
    [16.727, 49.168, 0.3, 12, 1, 0.9], [16.713, 49.179, 0.16, 7, 0, 0.2], [16.744, 49.152, 0.14, 6, 0, 0.5], [16.737, 49.141, 0.18, 8, 1, 1.3],
    [16.721, 49.114, 0.2, 9, 1, 1.4], [16.716, 49.101, 0.2, 9, 1, 1.5], [16.763, 49.140, 0.18, 8, 1, 0.1], [16.753, 49.164, 0.15, 7, 0, 0],
    [16.787, 49.164, 0.18, 8, 1, 0.2], [16.808, 49.175, 0.15, 6, 0, 0.5], [16.826, 49.142, 0.2, 9, 1, 0.3], [16.773, 49.118, 0.12, 5, 0, 1.2],
    [16.758, 49.104, 0.18, 8, 1, 0.2], [16.737, 49.087, 0.16, 7, 0, 0.6], [16.694, 49.084, 0.2, 9, 1, 0.4], [16.775, 49.197, 0.16, 7, 1, 0.1],
    [16.810, 49.110, 0.12, 5, 0, 0.8], [16.790, 49.084, 0.13, 5, 0, 0.2], [16.66, 49.155, 0.16, 7, 1, 1.2], [16.86, 49.175, 0.16, 7, 1, 0.4],
  ].map(([lon, lat, r, n, church, axis]) => ({ at: P(lon, lat), r: r / 0.74, n, church: !!church, axis })),
  woods: [
    { pts: blob([16.708, 49.118], 0.5, 0.32, 61, 10, 0.2) },
    { pts: blob([16.665, 49.085], 1.5, 0.9, 62, 14, 0.25), conifer: 0.3 },
    { pts: blob([16.735, 49.068], 1.2, 0.35, 63, 12, 0.25) },
    { pts: blob([16.835, 49.195], 1.1, 0.6, 64, 12, 0.25), conifer: 0.4 },
    { pts: blob([16.855, 49.08], 0.8, 0.7, 65, 12, 0.25) },
    { pts: blob([16.64, 49.16], 0.7, 0.9, 66, 12, 0.25), conifer: 0.5 },
    // 普拉岑东坡下那片小树林不画成符号：镜头 4 近看时它像一摊圆片，改由小景里的纸片果树表示
  ],
};

// 12 月 4 日的小纸：驿路边，地图之外（实际地点在战场东南约 20 km，不在这张图上）。
// 和主图之间隔开一截桌面，一根红线从主图东南角系到小纸上。
const MILL_SHEET = { center: [11.0, 7.5], rot: -0.08, size: [6.2, 5.8] };
const MILL_MAP = {
  size: MILL_SHEET.size, margin: 0.2,
  streams: [{ w: 0.06, pts: [[1.5, -1.9], [1.3, -0.95], [1.12, -0.4], [1.2, 0.5], [1.4, 1.9]] }],
  roads: [{ main: true, w: 2.4, ruts: true, pts: [[-3.1, 0.78], [-1.5, 0.66], [-0.3, 0.6], [0.8, 0.62], [1.9, 0.74], [3.1, 0.86]] }, { main: true, w: 2.4, ruts: true, rutAxis: 'x', pts: [[1.75, 2.95], [1.35, 2.1], [1.02, 1.4], [0.85, 0.66]] }, { pts: [[0.3, 0.6], [0.25, 0.1]] }],
  ponds: [{ pts: [[1.0, -0.62], [1.42, -0.74], [1.56, -0.42], [1.32, -0.26], [1.06, -0.34]] }],
  villages: [], woods: [{ pts: [[-2.4, -1.6], [-1.2, -1.75], [-0.8, -1.1], [-1.9, -0.9]] }, { pts: [[1.9, -1.7], [2.6, -1.5], [2.5, -0.6], [1.8, -0.9]], conifer: 0.2 }],
  ridges: [{ pts: [[-2.5, 1.3], [-1.2, 1.15], [-0.6, 1.6], [-2.2, 1.75]] }],
  snow: [
    [[-1.9, 0.2], [-1.4, 0.05], [-1.1, 0.3], [-1.5, 0.45], [-1.95, 0.4]], [[0.7, 1.05], [1.3, 0.95], [1.6, 1.25], [1.1, 1.45], [0.75, 1.3]],
    [[-0.9, 1.15], [-0.4, 1.1], [-0.25, 1.4], [-0.8, 1.5]], [[1.8, -0.2], [2.3, -0.3], [2.5, 0.05], [2.0, 0.15]], [[-2.4, 1.0], [-2.0, 0.95], [-1.9, 1.25], [-2.35, 1.3]],
    [[-0.5, -0.9], [0.1, -1.0], [0.3, -0.7], [-0.3, -0.6]], [[2.0, 1.2], [2.5, 1.1], [2.6, 1.5], [2.1, 1.55]],
  ],
};
const MW0 = (lx, lz) => { const c = Math.cos(MILL_SHEET.rot), s = Math.sin(MILL_SHEET.rot); return [MILL_SHEET.center[0] + c * lx + s * lz, MILL_SHEET.center[1] - s * lx + c * lz]; };
const m3 = (lx, y, lz) => { const [x, z] = MW0(lx, lz); return [x, y, z]; };

// ───────────── 镜头：位置、目标、视角、光圈（关键帧三次样条）─────────────
// [t, [px,py,pz, tx,ty,tz, fov, aperture]]
const cm = (lx, ly, lz, tx, ty, tz, fov, ap) => { const p = m3(lx, ly, lz), q = m3(tx, ty, tz); return [p[0], p[1], p[2], q[0], q[1], q[2], fov, ap]; };
// 镜头 4 的小景机位（从西南偏南、约 30° 俯角看普拉岑东坡）
const S4CAM = [[2.76, 1.97, 3.18, 3.03, 0.17, 0.71, 37, 0.25], [2.88, 1.87, 3.08, 3.09, 0.17, 0.75, 37, 0.29]];
const CAM = spline([
  // 1 夜：从茹拉尼的拿破仑拉开到整张图（全图早一点到位，留时间看蓝钉西撤）
  [0.0, [-1.6, 2.95, 0.45, -0.45, 0.82, -3.3, 34, 0.32]],
  [1.0, [-1.45, 3.9, 1.9, -0.5, 0.62, -2.85, 34, 0.26]],
  [2.05, [0.1, 7.1, 7.3, 0.10, 0.05, -0.12, 34, 0.12]],
  [3.2, [0.0, 6.5, 7.3, 0.32, 0.06, 0.86, 34, 0.13]],
  // 2 拂晓：俯冲到特尔尼茨，画底留出岸边的前列。
  [3.95, [-0.72, 2.36, 5.99, -0.42, 0.12, 2.9, 34, 0.22]],
  [4.75, [-0.61, 1.42, 5.43, -0.31, 0.18, 3.18, 37, 0.25]],
  [6.0, [-0.52, 1.44, 5.40, -0.25, 0.17, 3.22, 37, 0.25]],
  [7.0, [-0.42, 1.45, 5.34, -0.20, 0.17, 3.18, 37, 0.26]],
  // 3 先掠过茹拉尼的骑马观察组，再落到普拉岑西坡。
  [7.59, [-0.12, 3.18, 4.72, 0.14, 0.13, 1.52, 35, 0.19]],
  [8.12, [-0.55, 1.33, -0.73, -0.46, 0.50, -3.06, 36, 0.22]],
  [8.62, [-0.49, 1.47, -0.29, -0.37, 0.47, -2.80, 36, 0.20]],
  [9.23, [0.53, 1.98, 3.21, 0.57, 0.22, 0.37, 39, 0.23]],
  [9.95, [0.60, 1.97, 3.18, 0.60, 0.22, 0.42, 39, 0.24]],
  [10.6, [0.69, 1.94, 3.11, 0.69, 0.22, 0.43, 39, 0.25]],
  [10.95, [0.82, 2.01, 3.15, 0.85, 0.23, 0.45, 39, 0.24]],
  // 4 午后：先高一点看地图上蓝箭切断绿条，再压低到东坡：左边高地沿上的炮组，右边被截成两段的联军
  [11.55, [2.35, 3.1, 2.95, 2.8, 0.2, 0.45, 34, 0.24]],
  [12.25, S4CAM[0]],
  [13.82, S4CAM[1]],
  // 拉回地图（看得见主图东南角、红线和另一张小纸），稍停，再落到 12 月 4 日的小纸上
  [14.55, [6.65, 6.15, 10.9, 7.66, 0.0, 5.76, 35, 0.12]],
  [14.9, [7.78, 5.90, 11.4, 8.70, 0.05, 6.1, 35, 0.12]],
  [15.95, cm(-0.35, 1.7, 5.6, 0.0, 0.46, 0.5, 32, 0.3)],
  [16.7, cm(-0.20, 1.13, 4.18, 0.0, 0.49, 0.54, 33, 0.27)],
  [18.0, cm(-0.16, 1.06, 3.92, 0.0, 0.47, 0.55, 33, 0.30)],
]);
function camAt(t) {
  const v = CAM(clamp(t, 0, 18));
  const c = { pos: [v[0], v[1], v[2]], tgt: [v[3], v[4], v[5]], fov: v[6], ap: v[7] };
  c.dist = Math.hypot(v[0] - v[3], v[1] - v[4], v[2] - v[5]);
  c.focus = c.dist;
  return c;
}

// ───────────── 光：随时刻走 ─────────────
const LIGHT_KEYS = [[0, 'night'], [3.35, 'night'], [4.35, 'dawn'], [7.6, 'dawn'], [9.0, 'sun'], [10.95, 'sun'], [11.6, 'noon'], [13.6, 'noon'], [14.8, 'overcast'], [18, 'overcast']];
function lightAt(t) {
  let i = 0; while (i < LIGHT_KEYS.length - 2 && t > LIGHT_KEYS[i + 1][0]) i++;
  const [t0, a] = LIGHT_KEYS[i], [t1, b] = LIGHT_KEYS[i + 1];
  return mixLight(LIGHTS[a], LIGHTS[b], ease.inOut(clamp((t - t0) / (t1 - t0))));
}

// ───────────── 出场节奏（定格 12 fps 的立起、放倒）─────────────
function rise(t, up, down = 99, d = 0.42) {
  const tt = stepT(t, 12);
  if (tt < up) return 0;
  if (tt < up + d) return clamp(ease.outBack((tt - up) / d, 1.3), 0, 1.06);
  if (tt < down) return 1;
  if (tt < down + d) return 1 - ease.inOut((tt - down) / d);
  return 0;
}
// 一步一顿的行进：fps 步频，每步抬一下
function march(t, t0, t1, a, b, { fps = 8, bob = 0.014, run = false } = {}) {
  const tt = stepT(t, fps), u = clamp((tt - t0) / (t1 - t0)), k = Math.floor((tt - t0) * fps);
  const moving = tt > t0 && tt < t1;
  return { x: lerp(a[0], b[0], u), z: lerp(a[1], b[1], u), dy: moving ? bob * (k % 2) * (run ? 1.6 : 1) : 0, lean: moving ? (run ? 0.06 : 0.025) * (k % 2 ? 1 : -1) : 0 };
}

export function create({ canvas, overlay, fontFamily, seed = 1, quality = 'medium', mode } = {}) {
  mode = mode || 'page';
  let world = null, plates = null, live = false, disposed = false;
  const S = { cards: [], pins: [] };
  const inst = { ready: null, apply, dispose, plates: null, world: null, spec: null, camAt };

  inst.ready = (async () => {
    try {
      world = await createWorld({ canvas, quality });
      if (disposed) { world.dispose(); return; }
      inst.world = world;
      await build(world, S, quality, () => disposed);
      if (disposed) return;
      inst.spec = platesSpec(world);
      plates = createPlates(overlay, { fontFamily, sides: SIDES, mode });
      plates.load(inst.spec);
      await plates.ready;
      if (disposed) return;
      inst.plates = plates;
      live = true;
    } catch (error) {
      dispose();
      throw error;
    }
  })();

  function apply(t) {
    if (!live) return;
    t = clamp(+t || 0, 0, meta.dur);
    const cam = camAt(t);
    world.setCamera(cam);
    const lp = lightAt(t);
    lp.fogD *= clamp(2.4 / cam.dist, 0.05, 1.3);
    world.setLight(lp, cam.tgt, clamp(cam.dist * 0.75, 2.2, 10));
    // 烛光（夜里是主光，俯冲进拂晓时熄掉）
    const on = 1 - smooth(3.4, 4.1, t);
    const fl = S.candle.set(t, on, world.camera);
    const L = world.lights;
    L.candle.intensity = 30 * on * lp.candle * fl; L.candle.visible = on > 0.01;
    // 篝火的暖光：镜头 2 近景的营火、镜头 5 驿路边的篝火
    const fire5 = smooth(15.3, 15.9, t), fire2 = smooth(3.9, 4.5, t) * (1 - smooth(6.95, 7.3, t));
    const fireOn = fire5 > 0.01 ? fire5 : fire2, fireP = fire5 > 0.01 ? S.fireAt : S.fire2At;
    L.fill.position.set(...fireP); L.fill.intensity = fireOn * (fire5 > 0.01 ? 1.2 : 0.7) * (1 + 0.25 * noise1(t * 7, 11)); L.fill.visible = fireOn > 0.01;
    for (const c of S.cards) c.apply(t);
    for (const p of S.pins) p.apply(t);
    for (const f of S.updaters) f(t, lp, cam, world.camera);
    world.render({
      focus: cam.focus, aperture: cam.ap, exposure: lp.exposure, bloom: lp.bloom, sat: lp.sat, contrast: lp.contrast,
      lift: lp.lift, gain: lp.gain, vig: lp.vig, grain: lp.grain, seed: Math.floor(t * 24) % 997, bloomThr: 1.0,
    });
    if (plates) plates.apply(t);
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    live = false;
    plates?.dispose();
    world?.dispose();
    inst.world = inst.plates = inst.spec = null;
    world = plates = null;
  }
  return inst;
}

// ───────────── 搭世界 ─────────────
async function build(world, S, quality, isDisposed) {
  const hi = quality === 'high';
  const THREE = world.THREE;
  S.updaters = [];
  const img = {};
  const names = {
    napoleon: 'napoleon2-master.webp', au: 'troops-austrian.webp', mill: 'prop-burnt-mill.webp', letter: 'prop-letter-quill.webp', ice: 'prop-ice-crack.webp',
    napTel: 'napoleon2-telescope.webp', napGreet: 'napoleon2-greet.webp', frzGreet: 'franz-greet.webp', frDef: 'troops-french-defend.webp',
    ruRet: 'troops-russian-retreat.webp', auRet: 'troops-austrian-retreat-dark.webp', gun: 'french-gun-crew.webp', wreck: 'cannon-wreck-allied.webp',
    frRun: 'troops-french-advance.webp', frCol: 'troops-french-column-blue.webp', ruCol: 'troops-russian-column.webp', ru: 'troops-russian.webp',
    napHorse: 'napoleon2-horse.webp', napHorseTel: 'napoleon2-horse-telescope.webp', staff: 'staff-riders.webp',
    frHorse: 'cavalry-french-cuirassiers.webp', ruHorse: 'cavalry-russian-dragoons.webp',
    auCol: 'troops-austrian-column.webp', ruRun: 'troops-russian-advance.webp',
    frFire: 'troops-french-volley.webp', ruFire: 'troops-russian-volley.webp', auFire: 'troops-austrian-volley.webp',
    logs: 'campfire-logs.webp', flame: 'campfire-flame.webp', cottage: 'village-cottage.webp', church: 'village-church.webp', orch: 'tree-orchard.webp', poplar: 'tree-poplar.webp',
  };
  const fx = {};
  for (const k of ['blast-earth-a', 'blast-earth-b', 'blast-shell', 'blast-smoke', 'muzzle-flash', 'volley-smoke']) names[k] = k + '-trim.webp';
  await Promise.all(Object.entries(names).map(async ([k, f]) => { img[k] = await world.image(new URL(f, MEDIA)); }));
  if (isDisposed()) return;

  // 桌上的地图（纸蒙在缓坡上）
  const sheet = world.sheet({
    data: MAP, center: [0, 0], rot: 0, ppu: hi ? 330 : 250, assets: { ice: img.ice },
    creases: { x: [-2.33, 2.33], z: [-1.92, 1.92] }, seed: 7,
    details: [{ rect: [-3.4, 1.5, 1.0, 4.6], ppu: hi ? 720 : 520 }, { rect: [-1.0, -1.3, 3.8, 2.6], ppu: hi ? 620 : 460 }],
  });
  S.sheet = sheet;
  // 12 月 4 日的小纸
  const ms = world.sheet({ data: MILL_MAP, center: MILL_SHEET.center, rot: MILL_SHEET.rot, ppu: hi ? 560 : 420, assets: { ice: img.ice }, curl: 0.6, seed: 11, lift: 0.002 });
  S.millSheet = ms;
  const W5 = (lx, lz) => ms.toWorld(lx, lz);

  // 烛台：地图西侧桌面上
  const candle = world.candle(); candle.group.position.set(-8.05, 0, 3.3); S.candle = candle;
  world.lights.candle.position.set(-8.05, candle.flameY, 3.3); world.lights.candle.target.position.set(0.5, 0, -1.2);
  // 桌上的信和羽毛笔（平放）
  const dLetter = world.diecut(img.letter, { maxSize: 900, border: 0.01 });
  const letter = world.makeCard(dLetter, { height: 1.5, thick: 0.006 }); letter.set({ x: -9.6, y: 0.004, z: 5.4, yaw: 0.35, rise: 0.0011, flat: -1 });

  // ── 纸片 ──
  const DC = {};
  const dc = (k, src, o) => (DC[k] = world.diecut(src, { ...o, trim: 0, pixelMap: PIXEL_MAP[k] }));
  const GEN = { trim: 8, border: 0.005, minBorder: 3 }; // 生图自带白边：只补一圈细纸边，裁掉透明空边
  dc('napoleon', img.napoleon, { ...GEN, maxSize: 1100 });
  for (const k of ['napHorse', 'napHorseTel', 'staff', 'frHorse', 'ruHorse']) dc(k, img[k], { ...GEN, fill: false, maxSize: 1300 });
  dc('napTel', img.napTel, { ...GEN, maxSize: 1100 }); dc('napG', img.napGreet, { ...GEN, maxSize: 1100 }); dc('frzG', img.frzGreet, { ...GEN, maxSize: 1100 });
  dc('au', img.au, {}); dc('ru', img.ru, {});
  for (const k of ['frRun', 'frCol', 'ruCol', 'auCol', 'ruRun', 'frFire', 'ruFire', 'auFire']) dc(k, img[k], { ...GEN, fill: false });
  for (const k of ['blast-earth-a', 'blast-earth-b', 'blast-shell', 'blast-smoke', 'muzzle-flash', 'volley-smoke']) {
    const tex = new THREE.Texture(img[k]); tex.colorSpace = THREE.SRGBColorSpace; tex.needsUpdate = true; fx[k] = world.ownTexture(tex);
  }
  dc('frDef', img.frDef, GEN); dc('ruRet', img.ruRet, GEN); dc('auRet', img.auRet, GEN);
  dc('gun', img.gun, GEN); dc('wreck', img.wreck, GEN); dc('wreckR', img.wreck, { ...GEN, flipX: true });
  dc('logs', img.logs, { ...GEN, maxSize: 900 }); dc('flame', img.flame, { ...GEN, maxSize: 560 }); dc('flameR', img.flame, { ...GEN, maxSize: 560, flipX: true });
  dc('cottage', img.cottage, GEN); dc('cottageR', img.cottage, { ...GEN, flipX: true }); dc('church', img.church, GEN);
  dc('orch', img.orch, { ...GEN, fill: false }); dc('orchR', img.orch, { ...GEN, fill: false, flipX: true });
  dc('poplar', img.poplar, { ...GEN, fill: false, maxSize: 1200 }); dc('poplarR', img.poplar, { ...GEN, fill: false, maxSize: 1200, flipX: true });
  dc('mill', img.mill, { border: 0.011 });
  dc('wall1', sprites.stoneWall(5), { border: 0.012 }); dc('wall2', sprites.stoneWall(6, 0.7), { border: 0.014 });
  dc('wedge', sprites.wedge('#2c4f9a'), { border: 0.03 });
  dc('barW', sprites.columnBar('#3f6a3e', 'whole', 5), { border: 0.012 }); dc('barA', sprites.columnBar('#3f6a3e', 'a', 5), { border: 0.02 }); dc('barB', sprites.columnBar('#3f6a3e', 'b', 6), { border: 0.02 });

  const G0 = (x, z) => world.groundY(x, z);
  // 立牌。follow：沿坡斜着站（纵队爬坡）；否则取脚下最低点，不悬空
  function card(k, height, pose, o = {}) {
    const c = world.makeCard(DC[k], { height, thick: o.thick ?? Math.max(0.006, height * 0.022), solid: o.solid ?? true, batch: true });
    const obj = {
      c, pose, k,
      apply(t) {
        const p = pose(t); if (!p || p.rise <= 0) { c.set({ rise: 0 }); return; }
        let y = p.y, lean = p.lean || 0;
        if (y == null) {
          const hw = c.width * 0.42, cy = Math.cos(p.yaw || 0), sy = Math.sin(p.yaw || 0);
          const h0 = G0(p.x, p.z), hr = G0(p.x + hw * cy, p.z - hw * sy), hl = G0(p.x - hw * cy, p.z + hw * sy);
          if (o.follow) { lean += Math.atan2(hr - hl, 2 * hw); y = (hr + hl) / 2; } else y = Math.min(h0, hr, hl);
        }
        c.set({ ...p, lean, y: y + (p.dy || 0) });
      },
    };
    S.cards.push(obj); return obj;
  }
  // 纸片上的挂点（原图像素 → 世界坐标），纸片不在场时返回 null
  const cardPt = (obj, px, py, dz = 0.02) => { const d = DC[obj.k]; const [u, v] = d.uvOf(px, py); if (!obj.c.root.visible) return null; obj.c.root.updateMatrixWorld(true); return obj.c.mesh.localToWorld(new THREE.Vector3((u - 0.5) * obj.c.width, (v - d.floorV) * obj.c.height, dz)).toArray(); };
  // 平放在地图上的兵棋纸片（以中心为轴，随坡俯仰）
  function piece(k, len, pose) {
    const c = world.makeCard(DC[k], { height: len, thick: 0.024, pivot: 'center' }); c.blobBase = 0;
    const obj = {
      c, pose,
      apply(t) {
        const p = pose(t); if (!p) { c.set({ rise: 0 }); return; }
        const dx = -Math.sin(p.yaw), dz = -Math.cos(p.yaw), hl = len * (p.scale ?? 1) / 2;
        const hF = G0(p.x + dx * hl, p.z + dz * hl), hB = G0(p.x - dx * hl, p.z - dz * hl), h0 = G0(p.x, p.z);
        c.set({ x: p.x, z: p.z, y: Math.max(h0, (hF + hB) / 2) + 0.014 + (p.dy || 0), yaw: p.yaw, rise: 0.0015, flat: -1, pitch: Math.atan2(hF - hB, 2 * hl), scale: p.scale ?? 1, shadow: 0 });
      },
    };
    S.cards.push(obj); return obj;
  }
  const still = (x, z, up, down, o = {}) => t => ({ x, z, rise: rise(t, up, down, o.d), yaw: o.yaw || 0, lean: o.lean || 0, tilt: o.tilt || 0 });
  const tree = (k, h, x, z, up, down, o = {}) => card(k, h, still(x, z, up, down, o), { solid: false });
  // 前景虚化纸片的落点：取 tc 时刻镜头，沿视线走 frac 远，再向左右推到画边（side=-1 左，1 右）
  const edgeSpot = (tc, side, frac, k = 0.86) => {
    const c = camAt(tc); const dx = c.tgt[0] - c.pos[0], dz = c.tgt[2] - c.pos[2], L = Math.hypot(dx, dz);
    const fx = dx / L, fz = dz / L, d = L * frac; const half = Math.tan(c.fov * Math.PI / 360) * 16 / 9 * d * k;
    return [c.pos[0] + fx * d - fz * half * side, c.pos[2] + fz * d + fx * half * side];
  };
  // 纸偶火苗：几片纸火苗插在柴堆里，按种子错开地摇、伸缩（定格 8 fps），自发光
  function puppetFire(at, { up, down = 99, h = 0.2, seed = 1, n = 3, spread = 0.06 }) {
    const out = [];
    for (let i = 0; i < n; i++) {
      const k = i % 2 ? 'flameR' : 'flame', hh = h * [1, 0.78, 0.62][i % 3];
      const c = world.makeCard(DC[k], { height: hh, thick: 0.003, solid: false });
      c.mesh.castShadow = false;
      c.front.emissive = new THREE.Color(1, 0.62, 0.3); c.front.emissiveMap = c.tex; c.front.emissiveIntensity = 1.6;
      const ox = (i - (n - 1) / 2) * spread * (i % 2 ? 1.1 : 0.9), oz = (i % 2 ? -0.006 : 0.004) - i * 0.002;
      const ph = seed * 1.7 + i * 2.3;
      S.cards.push({ c, apply(t) {
        const r0 = rise(t, up + i * 0.04, down, 0.3); if (r0 <= 0) { c.set({ rise: 0 }); return; }
        const tt = stepT(t, 8);
        const sw = 0.16 * Math.sin(tt * 9.1 + ph) + 0.08 * Math.sin(tt * 15.7 + ph * 2); // 左右摆
        const sy = 1 + 0.12 * Math.sin(tt * 11.3 + ph * 1.3) + 0.06 * noise1(tt * 6, seed + i); // 一伸一缩
        c.set({ x: at[0] + ox, y: at[1], z: at[2] + oz, rise: Math.min(1, r0), lean: sw, scale: sy, shadow: 0 });
        c.hinge.scale.set(1 / sy * (0.94 + 0.06 * Math.sin(tt * 7 + ph)), 1, 1); // 只纵向伸缩
      } });
      out.push(c);
    }
    return out;
  }

  // ── 镜头 1：夜，地图桌。拿破仑立在茹拉尼高地上；蓝钉从普拉岑西撤，绿钉压上高地 ──
  const nap = card('napoleon', 1.1, t => ({ x: PLACE.zuran[0] + 0.11, z: PLACE.zuran[1] + 0.1, rise: rise(t, -1, 3.5, 0.45), yaw: 0.1 }));
  nap.c.mesh.castShadow = false; // 烛光太低，人影会拖过半张图；只留接地的软影
  S.napZ = nap;
  const blue = 0x3a62b8, green = 0x3f7a42, PINS = 1.7; // 图钉放大，全图镜头里看得清
  const frPins = [
    [[1.0, -0.1], [-0.55, -0.7]], [[1.45, 0.45], [-0.35, 0.15]], [[0.85, 0.85], [-0.75, 0.9]], [[1.7, -0.45], [-0.2, -1.25]],
    [[1.25, 1.25], [-1.05, 1.55]], [[2.05, 0.2], [-0.95, -0.25]], [[0.6, 0.3], [-1.35, 0.4]],
  ];
  const alPins = [
    [[4.2, -1.2], [2.25, -0.75]], [[4.6, -0.3], [2.0, 0.1]], [[4.3, 0.7], [1.85, 0.95]], [[3.9, 1.6], [1.6, 1.6]], [[5.0, 0.4], [2.7, 0.5]],
    [[4.8, -2.2], [3.3, -2.3]], [[5.3, -1.4], [3.6, -1.5]], [[3.6, 2.4], [0.9, 2.35]], [[5.4, 1.4], [3.1, 1.3]],
  ];
  // 蓝钉在全图镜头里一枚接一枚被拔起、西移、按下（1.55–3.2 s）；绿钉随后压上高地。
  // 图钉随镜头拉远放大到 1.7 倍（近景时还是原大，不在拿破仑的特写里抢画面）
  const pinMove = (t, i, a, b, t0, gap, dur) => {
    const s0 = t0 + i * gap, s1 = s0 + dur; const tt = stepT(t, 12); const u = ease.inOut(clamp((tt - s0) / (s1 - s0)));
    const lift = Math.sin(Math.PI * clamp((tt - s0) / (s1 - s0))) * 0.22;
    const sink = smooth(3.5, 3.95, t) * 0.6 * PINS;
    return [lerp(a[0], b[0], u), lerp(a[1], b[1], u), lift - sink];
  };
  const FRP = [1.55, 0.13, 0.85], ALP = [1.95, 0.08, 0.8];
  const pinScale = t => lerp(1, PINS, smooth(1.0, 2.0, t));
  frPins.forEach(([a, b], i) => { const g = world.pin(blue, '#3a62b8'); g.rotation.set(0.05 * Math.sin(i * 2.1), i * 0.9, 0.05 * Math.cos(i * 1.7)); S.pins.push({ apply(t) { const [x, z, dy] = pinMove(t, i, a, b, ...FRP); g.visible = t < 4.0; g.scale.setScalar(pinScale(t)); g.position.set(x, G0(x, z) + dy, z); } }); });
  alPins.forEach(([a, b], i) => { const g = world.pin(green, i % 3 === 2 ? '#ece7da' : '#3f7a42'); g.rotation.set(0.05 * Math.cos(i * 1.3), i * 1.4, 0.05 * Math.sin(i * 2.3)); S.pins.push({ apply(t) { const [x, z, dy] = pinMove(t, i, a, b, ...ALP); g.visible = t < 4.0; g.scale.setScalar(pinScale(t)); g.position.set(x, G0(x, z) + dy, z); } }); });
  S.frPinEnd = frPins.reduce((s, [, b]) => [s[0] + b[0] / frPins.length, s[1] + b[1] / frPins.length], [0, 0]);
  S.frPinCenter = t => { let x = 0, z = 0; frPins.forEach(([a, b], i) => { const p = pinMove(t, i, a, b, ...FRP); x += p[0]; z += p[1]; }); return [x / frPins.length, z / frPins.length]; };
  // 夜雾：低低地贴着地图
  const nightFog = [world.fogSheet({ w: 9, h: 6, rep: [2, 1.4], horizontal: true, near: 2 }), world.fogSheet({ w: 8, h: 5, rep: [1.6, 1.2], horizontal: true, near: 2 })];
  nightFog[0].mesh.position.set(-1.2, 0.5, 0.2); nightFog[1].mesh.position.set(1.5, 0.42, 1.2);
  S.updaters.push((t, lp) => { const k = (1 - smooth(3.2, 3.9, t)) * 0.24; nightFog.forEach((f, i) => f.set(t + i * 7, k, [0.1, 0.12, 0.18], 0.012)); });

  // 随图钉拉开显出地图各段的驻队，南端与拂晓小景交接。
  for (const [k, h, x, z, up, down] of [
    ['frCol', 0.96, -2.09, -1.63, 0.91, 3.6], ['frCol', 0.87, -1.85, -0.09, 0.96, 3.83],
    ['frRun', 0.64, -2.49, 1.57, 1.02, 3.78], ['frCol', 0.88, -2.49, 3.15, 1.08, 3.9],
    ['frCol', 0.84, -1.72, 4.21, 1.14, 3.78], ['frRun', 0.57, -0.80, -2.00, 1.08, 3.25],
    ['ruCol', 0.78, 2.29, -2.54, 1.06, 3.61], ['auCol', 0.91, 2.05, -1.18, 1.12, 3.65],
    ['ruCol', 0.79, 3.64, 0.61, 1.16, 3.83], ['auCol', 0.94, 2.59, 2.01, 1.19, 3.85],
    ['auCol', 0.92, 3.50, 3.41, 1.24, 3.85], ['ruCol', 0.83, 1.88, 4.43, 1.28, 3.9],
  ]) card(k, h, still(x, z, up, down, { yaw: z * 0.025 }), { solid: false, follow: true });

  const particles = [];
  const fxRand = rng(3004);
  const mirrored = {};
  function paperFX(k, order, mirror = false) {
    if (mirror && !mirrored[k]) {
      const t = fx[k].clone(); t.repeat.x = -1; t.offset.x = 1; t.needsUpdate = true; mirrored[k] = world.ownTexture(t);
    }
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: mirror ? mirrored[k] : fx[k], depthWrite: false, alphaTest: 0.025 }));
    s.renderOrder = order; s.visible = false; world.scene.add(s);
    return s;
  }
  function flash(at, muzzle, dir, size) {
    const s = paperFX('muzzle-flash', 8, dir < 0);
    s.center.set(dir > 0 ? 0.04 : 0.96, 0.51);
    S.updaters.push((t, lp) => {
      const age = t - at, p = age >= 0 && age < 2 / 12 ? muzzle(t) : null;
      s.visible = !!p; if (!p) return;
      const k = age < 1 / 12 ? 1 : 0.66;
      s.position.set(...p); s.scale.set(size * k, size * 0.49 * k, 1);
      s.material.opacity = k; s.material.color.setRGB(1.4, 1 + 0.35 * lp.sunC[1], 0.87 + 0.36 * lp.sunC[2]);
    });
  }
  function splinters(at, p, n, spread) {
    for (let i = 0; i < n; i++) {
      const a = fxRand() * Math.PI * 2, d = spread * (0.2 + 0.8 * fxRand());
      const b = [p[0] + Math.cos(a) * d, p[1] - 0.014, p[2] + Math.sin(a) * d];
      particles.push({ at: at + fxRand() * 0.035, a: p, b, arc: spread * (0.2 + 0.42 * fxRand()), tail: 0, kind: 1, life: 0.16 + 0.34 * fxRand(), size: 0.009 + spread * 0.035 * fxRand(), alpha: 0.85 });
    }
  }
  function blast(at, p, h, k) {
    const air = k === 'blast-shell', life = 1.05 + 0.23 * fxRand(), dir = fxRand() < 0.5 ? -1 : 1;
    const roll = (fxRand() - 0.5) * 0.24, scale = h * (0.83 + 0.33 * fxRand());
    const rim = paperFX(k, 6, dir < 0), smoke = paperFX('blast-smoke', 6, dir < 0);
    rim.center.set(0.5, air ? 0.5 : 0.06); smoke.center.set(0.5, 0.08);
    if (!air) splinters(at, p, 27, scale * 0.61);
    S.updaters.push((t, lp) => {
      const age = t - at, f = Math.floor(age * 12 + 1e-6), u = clamp((f - 3) / (life * 12));
      rim.visible = f >= 0 && f < 3; smoke.visible = f >= 3 && u < 1;
      if (rim.visible) {
        const s = scale * [0.47, 1.04, 0.87][f];
        rim.position.set(...p); rim.scale.set(s * img[k].width / img[k].height, s, 1);
        rim.material.rotation = roll; rim.material.color.setScalar(f === 1 ? 1.6 : 1.04);
      }
      if (smoke.visible) {
        const s = scale * (0.77 + 0.39 * u);
        smoke.position.set(p[0] + 0.22 * u, p[1] + scale * (0.035 + 0.52 * u), p[2] - 0.06 * u);
        smoke.scale.set(s * 0.68, s, 1); smoke.material.rotation = roll + 0.13 * u;
        smoke.material.opacity = 0.88 * (1 - smooth(0.17, 1, u)); smoke.material.color.setRGB(1, 0.94 + 0.06 * lp.sunC[1], 0.92 + 0.08 * lp.sunC[2]);
      }
    });
  }

  const ranksRand = rng(209);
  const muzzles = {
    frFire: [[306, 192], [628, 192], [942, 192], [1271, 191], [1597, 192], [2038, 190]],
    ruFire: [[116, 232], [353, 232], [668, 230], [978, 230], [1288, 230], [1599, 230], [1901, 231]],
    auFire: [[141, 278], [295, 271], [602, 272], [907, 271], [1218, 271], [1525, 270], [1824, 273]],
  };
  // 一张行进纸片、一张齐射纸片。只在齐射的定格帧露出图上画死的火光。
  function rank(k, fire, h, a, b, up, start, halt, shot, down, rear = false) {
    const phase = ranksRand() * 0.12, scale = 0.92 + ranksRand() * 0.16, yaw = (ranksRand() - 0.5) * 0.20;
    const pose = t => {
      const m = march(t + phase, start + phase, halt + phase, a, b, { fps: 9, bob: 0.011, run: k === 'frRun' || k === 'ruRun' });
      return { ...m, rise: rise(t, up, down), yaw, scale };
    };
    const firing = t => shot !== null && t >= shot && t < shot + 2 / 12;
    const o = card(k, h, t => firing(t) ? null : pose(t), { follow: true, solid: !rear && k === 'frDef' });
    o.pose = pose;
    if (rear) o.c.front.color.setRGB(0.82, 0.83, 0.86);
    if (!fire) return o;
    const fr = fire === 'frFire', dir = fr ? 1 : -1;
    const line = card(fire, h * (k === 'frCol' || k === 'ruCol' || k === 'auCol' || k === 'au' || k === 'ru' ? 0.72 : 0.87), t => {
      if (!firing(t)) return null;
      const p = pose(t); p.x += dir * 0.022; p.lean += dir * (t < shot + 1 / 12 ? 0.025 : -0.019); return p;
    }, { follow: true, solid: false });
    if (rear) line.c.front.color.copy(o.c.front.color);
    line.apply(shot);
    const ms = muzzles[fire];
    const ports = ms.map(([x, y]) => cardPt(line, x, y, 0.014));
    line.c.set({ rise: 0 });
    const c = ports[ports.length >> 1];
    flash(shot, () => ports[dir > 0 ? ports.length - 1 : 0], dir, 0.16);
    flash(shot + 1 / 24, () => c, dir, 0.12);
    const fog = paperFX('volley-smoke', 7, dir < 0);
    S.updaters.push((t, lp) => {
      const age = t - shot - 1 / 12, u = stepT(age, 12) / 1.05;
      fog.visible = age >= 0 && u < 1 && t < down + 0.20;
      if (!fog.visible) return;
      const w = line.c.width * (0.89 + 0.37 * u);
      fog.position.set(c[0] + dir * (0.055 + 0.15 * u), c[1] + 0.018 + 0.085 * u, c[2] + 0.026 + 0.06 * u);
      fog.scale.set(w, w * 0.205, 1); fog.material.opacity = 0.52 * (1 - smooth(0.43, 1, u));
      fog.material.color.setRGB(1, 0.92 + 0.075 * lp.sunC[1], 0.88 + 0.10 * lp.sunC[2]);
    });
    for (const port of ports) for (let i = 0; i < 4; i++) {
      const life = 0.17 + fxRand() * 0.12, t0 = shot + i * 0.032 + fxRand() * 0.029;
      const wall = !fr && t0 < 7.3 && i % 2 === 0;
      const x = wall ? -1.29 + fxRand() * 0.52 : b[0] + dir * (1.02 + fxRand() * 0.46);
      const z = wall ? 3.04 : b[1] + (fxRand() - 0.5) * 0.68;
      const y = G0(x, z) + (wall ? 0.065 + 0.075 * fxRand() : 0.012);
      const a0 = [port[0], port[1] + (fxRand() - 0.5) * 0.035, port[2] + (fxRand() - 0.5) * 0.08];
      const dst = [x, y, z];
      particles.push({ at: t0, a: a0, b: dst, arc: 0, tail: 0.055 + fxRand() * 0.07, kind: 0, life, size: 0.0055 + fxRand() * 0.005, alpha: 0.48 + 0.4 * fxRand() });
      if (i < 2) splinters(t0 + life, dst, 2, 0.10);
    }
    return o;
  }

  // ── 镜头 2：拂晓，特尔尼茨。石墙、果园、村舍、教堂；墙后的法军据守，达武的援军跑步入阵 ──
  const T2 = { up: 3.52, down: 7.62 };
  card('cottage', 0.4, still(-2.05, 2.45, T2.up + 0.05, T2.down + 0.1, { yaw: 0.08 }));
  card('church', 0.62, still(-1.48, 2.3, T2.up, T2.down + 0.05, { yaw: -0.04 }));
  card('cottageR', 0.36, still(-0.78, 2.42, T2.up + 0.1, T2.down + 0.1, { yaw: -0.1 }));
  card('cottage', 0.3, still(-2.6, 2.7, T2.up + 0.15, T2.down + 0.15, { yaw: 0.15 }));
  tree('poplar', 0.92, -0.16, 2.24, T2.up + 0.12, T2.down + 0.12);
  tree('poplarR', 0.8, -2.85, 2.3, T2.up + 0.18, T2.down + 0.18);
  tree('orch', 0.36, -1.14, 2.7, T2.up + 0.2, T2.down, { yaw: 0.1 });
  tree('orchR', 0.32, -0.6, 2.66, T2.up + 0.24, T2.down, { yaw: -0.1 });
  tree('orch', 0.34, -1.74, 2.76, T2.up + 0.28, T2.down + 0.05);
  tree('orchR', 0.3, -0.28, 2.74, T2.up + 0.3, T2.down + 0.05);
  // 两道石墙后的守军与从西边跑来的达武援军。
  card('wall1', 0.19, still(-1.08, 3.04, T2.up + 0.22, T2.down, { yaw: 0.02 }));
  card('wall2', 0.15, still(-1.82, 3.1, T2.up + 0.25, T2.down, { yaw: -0.06 }));
  [
    ['frDef', 0.40, [-1.00, 2.96], [-1.00, 2.96], 3.72, 4.45, 4.8, 5.63, false],
    ['frDef', 0.36, [-1.72, 2.87], [-1.72, 2.87], 3.83, 4.55, 4.9, 5.56, true],
    ['frRun', 0.47, [-2.14, 3.62], [-1.30, 3.59], 3.8, 4.65, 5.42, 6.21, false],
    ['frCol', 0.52, [-1.83, 2.39], [-1.19, 2.42], 3.62, 4.38, 5.6, null, true],
    ['frRun', 0.33, [-1.15, 1.91], [-0.55, 1.95], 3.68, 4.88, 5.79, null, true],
    ['frCol', 0.42, [-1.98, 3.26], [-1.68, 3.23], 3.79, 4.72, 5.71, null, true],
    ['frRun', 0.49, [-1.54, 4.15], [-1.02, 4.13], 3.9, 4.72, 5.75, null, false],
  ].forEach(([k, h, a, b, up, start, halt, shot, rear]) => rank(k, shot === null ? null : 'frFire', h, a, b, up, start, halt, shot, T2.down, rear));
  // 池北岸的齐射列和南岸的前列隔冰相望。
  [
    ['au', 'auFire', 0.50, [0.22, 2.93], [-0.08, 2.94], 3.76, 4.5, 5.30, 5.52, false],
    ['ruRun', 'ruFire', 0.42, [1.14, 2.86], [0.74, 2.89], 3.78, 4.6, 5.30, 5.58, false],
    ['ruRun', 'ruFire', 0.51, [0.77, 3.74], [0.44, 3.77], 3.8, 4.72, 5.81, 6.17, false],
    ['auCol', null, 0.65, [0.79, 4.18], [0.60, 4.16], 3.78, 4.78, 5.66, null, false],
    ['auCol', null, 0.54, [1.18, 3.28], [0.96, 3.30], 3.66, 4.65, 5.8, null, true],
    ['ruCol', null, 0.41, [0.42, 2.46], [0.14, 2.46], 3.66, 4.64, 5.8, null, true],
    ['auCol', null, 0.50, [1.23, 2.40], [0.90, 2.41], 3.62, 4.68, 5.80, null, true],
    ['ruCol', null, 0.42, [1.00, 1.81], [0.70, 1.85], 3.61, 4.58, 5.80, null, true],
    ['auCol', null, 0.51, [0.23, 1.86], [0.06, 1.85], 3.66, 4.60, 5.75, null, true],
    ['ruCol', null, 0.38, [1.59, 2.09], [1.43, 2.10], 3.7, 4.61, 5.78, null, true],
    ['auCol', null, 0.48, [0.49, 1.45], [0.35, 1.44], 3.7, 4.63, 5.76, null, true],
  ].forEach(([k, fire, h, a, b, up, start, halt, shot, rear]) => rank(k, fire, h, a, b, up, start, halt, shot, T2.down, rear));
  // 前景：右边一段虚着的石墙，左边一棵虚着的白杨
  { const a = edgeSpot(5.5, 1, 0.42, 0.7), b = edgeSpot(5.5, -1, 0.5, 1.20);
    card('wall1', 0.2, still(a[0], a[1], T2.up + 0.35, T2.down, { yaw: 0.3 }));
    tree('poplar', 1.0, b[0], b[1], T2.up + 0.3, T2.down); }
  // 下方三分之一：近处一段矮石墙、一堆夜里留下的营火、右下角一棵果树（都矮于动作区，只当地面）
  card('wall2', 0.11, still(-1.2, 3.42, T2.up + 0.3, T2.down, { yaw: 0.04 }));
  const fire2 = [-0.5, 3.56]; S.fire2At = [fire2[0], 0.22, fire2[1] - 0.05];
  card('logs', 0.075, still(fire2[0], fire2[1], T2.up + 0.32, T2.down));
  puppetFire([fire2[0], G0(...fire2) + 0.028, fire2[1] - 0.012], { up: T2.up + 0.4, down: T2.down, h: 0.09, seed: 2, n: 2, spread: 0.035 });
  tree('orchR', 0.34, 1.42, 3.54, T2.up + 0.34, T2.down);
  // 雾：只在中远景
  const dawnFog = [
    world.fogSheet({ w: 5, h: 1.0, rep: [2.4, 1], near: 0.5 }), world.fogSheet({ w: 4.2, h: 0.5, rep: [2, 1], near: 0.5 }),
    world.fogSheet({ w: 3.0, h: 0.5, rep: [1.6, 1], near: 0.5 }), world.fogSheet({ w: 6.0, h: 1.4, rep: [2, 1], near: 0.5 }),
  ];
  dawnFog[0].mesh.position.set(-1.0, 0.42, 2.05); dawnFog[1].mesh.position.set(-1.1, 0.14, 2.2); dawnFog[2].mesh.position.set(0.9, 0.18, 2.55); dawnFog[3].mesh.position.set(-0.6, 0.6, 1.5);
  S.updaters.push((t, lp) => { const k = smooth(3.7, 4.6, t) * (1 - smooth(7.0, 7.7, t)); dawnFog.forEach((f, i) => f.set(t + i * 3, k * [0.28, 0.18, 0.2, 0.4][i], [0.8, 0.84, 0.9], 0.015 + i * 0.004)); });
  // 对岸的雪土只掀一次，留出墙后还击的轮廓。
  { const x = -0.22 + 0.14 * fxRand(), z = 3.14 + 0.08 * fxRand(); blast(6.49, [x, G0(x, z) + 0.025, z], 0.23, 'blast-earth-b'); }
  // 营火的细烟
  { const puffs = []; for (let i = 0; i < 7; i++) puffs.push({ t0: T2.up + 0.5 + i * 0.42, life: 2.2, p: [fire2[0] + 0.01, 0.1, fire2[1] - 0.02], v: [0.05, 0.16, -0.03], s0: 0.03, s1: 0.1 });
    const sm = world.paperSmoke(puffs, { tone: 'grey' }); S.updaters.push((t, lp, cam, camera) => sm.set(t, camera, [0.95, 0.93, 0.9], 1 - smooth(6.95, 7.3, t))); }

  // ── 镜头 3：茹拉尼观察组和普拉岑西坡的蓝纵队 ──
  const T3 = { up: 7.29, down: 11.27 };
  const [zx, zz] = PLACE.zuran;
  const napFar = card('napHorseTel', 0.97, t => stepT(t, 12) >= 8.25
    ? { x: zx + 0.46, z: zz + 0.29, rise: rise(t, 7.6, 8.79), yaw: 0.03 } : null, { solid: false });
  card('staff', 0.87, still(zx - 0.65, zz + 0.28, 7.43, 8.85, { yaw: -0.09 }), { solid: false });
  card('napTel', 0.73, t => stepT(t, 12) < 8.25
    ? { x: zx + 0.46, z: zz + 0.29, rise: rise(t, 7.47), yaw: 0.03 } : null);
  card('frCol', 0.66, still(zx - 0.83, zz - 0.79, 7.36, 8.95), { solid: false });
  card('frCol', 0.61, still(zx + 1.17, zz - 0.65, 7.38, 8.95), { solid: false });
  card('frRun', 0.57, still(zx + 1.26, zz + 0.57, 7.45, 8.90), { solid: false });
  S.napFar = napFar;
  const cols = [
    ['frRun', 'frFire', 0.52, [-0.30, 0.39], [0.07, 0.28], 7.48, 8.90, 9.8, 10.06, false],
    ['frRun', 'frFire', 0.42, [-0.42, -0.65], [0.00, -0.68], 7.52, 8.90, 9.74, 10.11, false],
    ['frCol', null, 0.62, [-0.57, 1.65], [-0.30, 1.65], 7.41, 8.86, 10.37, null, false],
    ['frCol', null, 0.59, [-1.04, 1.34], [-0.81, 1.34], 7.44, 8.86, 10.50, null, false],
    ['frCol', null, 0.53, [-0.85, 0.90], [-0.57, 0.90], 7.40, 8.87, 10.52, null, false],
    ['frCol', null, 0.50, [-1.31, 0.60], [-1.08, 0.60], 7.40, 8.91, 10.55, null, false],
    ['frCol', null, 0.48, [-0.96, -0.24], [-0.68, -0.24], 7.39, 8.89, 10.45, null, false],
    ['frCol', null, 0.50, [-1.37, -0.78], [-1.03, -0.78], 7.39, 8.88, 10.52, null, true],
    ['frCol', null, 0.51, [-0.58, -1.49], [-0.26, -1.49], 7.4, 8.90, 10.50, null, true],
    ['frCol', null, 0.50, [-1.66, -1.74], [-1.39, -1.74], 7.39, 8.90, 10.55, null, true],
    ['frRun', null, 0.66, [-0.12, 1.13], [0.25, 1.11], 7.49, 8.88, 10.52, null, false],
    ['frCol', null, 0.53, [0.15, 0.72], [0.32, 0.71], 7.49, 8.93, 10.51, null, false],
    ['frCol', null, 0.57, [-0.20, 1.82], [0.03, 1.81], 7.50, 8.92, 10.52, null, false],
    ['frCol', null, 0.44, [-0.16, -2.28], [0.02, -2.25], 7.48, 8.90, 10.50, null, true],
  ].map(([k, fire, h, a, b, up, start, halt, shot, rear]) => rank(k, fire, h, a, b, up, start, halt, shot, T3.down, rear));
  S.lead = cols[0];
  card('frCol', 0.49, t => {
    const m = march(t, 8.93, 10.50, [-1.50, 0.27], [-1.23, 0.27], { fps: 9 });
    return { ...m, rise: rise(t, 7.47, T3.down), yaw: 0.08 };
  }, { follow: true, solid: false });
  // 俄军两排面朝西，枪口之间留出整条坡面。
  [
    ['ruRun', 'ruFire', 0.51, [1.68, 0.30], [1.46, 0.28], 7.58, 8.96, 9.67, 9.99, false],
    ['ruRun', 'ruFire', 0.41, [1.60, -0.65], [1.46, -0.67], 7.61, 8.99, 9.70, 10.07, false],
    ['ruCol', null, 0.45, [2.62, -0.30], [2.47, -0.29], 7.51, 8.91, 9.86, null, false],
    ['ruCol', null, 0.49, [2.13, -1.13], [1.96, -1.12], 7.52, 8.89, 9.87, null, true],
    ['ruCol', null, 0.49, [2.87, -1.57], [2.73, -1.55], 7.56, 8.90, 9.89, null, true],
    ['ruCol', null, 0.44, [1.57, -2.0], [1.50, -2.0], 7.54, 8.91, 9.9, null, true],
    ['auCol', null, 0.59, [2.18, 0.75], [2.01, 0.74], 7.62, 8.92, 9.9, null, false],
    ['ruRun', null, 0.56, [1.72, 1.53], [1.55, 1.50], 7.59, 8.90, 9.9, null, false],
  ].forEach(([k, fire, h, a, b, up, start, halt, shot, rear]) => rank(k, fire, h, a, b, up, start, halt, shot, T3.down, rear));
  tree('poplar', 0.84, 2.42, -1.74, 7.5, T3.down);
  tree('orch', 0.34, 2.63, 1.3, 7.6, T3.down);
  tree('orchR', 0.34, -1.75, 1.16, 7.6, T3.down);
  // 空中榴弹在两线之间开花，烟随午前的风抬高。
  { const x = 0.78 + 0.1 * fxRand(), z = 0.11 + 0.08 * fxRand(); blast(10.54, [x, G0(x, z) + 0.36, z], 0.23, 'blast-shell'); }
  // 雾在 8:30 左右散开、上升
  const fog3 = [world.fogSheet({ w: 4, h: 1.0, rep: [2, 1], near: 0.5 }), world.fogSheet({ w: 4.5, h: 1.2, rep: [2.2, 1], near: 0.5 }), world.fogSheet({ w: 5, h: 1.4, rep: [2, 1], near: 0.5 })];
  fog3[0].mesh.position.set(0.6, 0.35, 1.35); fog3[1].mesh.position.set(1.0, 0.45, 0.72); fog3[2].mesh.position.set(1.1, 0.6, -0.1);
  S.updaters.push((t, lp) => { const k = smooth(7.3, 7.9, t) * (1 - smooth(8.5, 9.6, t)); const up = smooth(8.4, 10, t) * 0.45; fog3.forEach((f, i) => { f.mesh.position.y = [0.35, 0.45, 0.6][i] + up; f.set(t + i * 5, k * [0.6, 0.5, 0.6][i], [0.86, 0.88, 0.92], 0.02); }); });
  const rays = world.rays(6); rays.group.position.set(2.4, 1.6, 0.0); rays.group.rotation.set(0, -0.35, -0.95);
  S.updaters.push((t, lp) => rays.set(t, 0.12 * smooth(8.6, 9.6, t) * (1 - smooth(10.6, 11.2, t))));
  // 刺刀亮点：取法军纸片上枪尖的位置（原图像素），一道光从排头扫到排尾
  {
    const tips = [[74, 376], [173, 296], [261, 347], [315, 296], [429, 298], [553, 297], [676, 301]];
    const items = [];
    cols.slice(2, 5).forEach((c, ci) => tips.forEach((tp, k) => {
      for (let rep = 0; rep < 2; rep++) items.push({ t0: 9.0 + ci * 0.19 + (6 - k) * 0.045 + rep * 0.85, dur: 0.22, size: 0.044, kind: 'star', color: [3.2, 3.0, 2.5], p: () => cardPt(c, tp[0], tp[1], 0.012) });
    }));
    const gl = world.sparks(items);
    S.updaters.push(t => gl.set(t, smooth(8.9, 9.1, t) * (1 - smooth(10.8, 11.0, t))));
  }

  // ── 镜头 4：午后，普拉岑东坡。
  //    地图层：联军纵队的绿条南北横在东坡下，法军蓝箭从高地上插进来，从中间切断；
  //    小景层：两截绿条上立起联军纸片兵，各自往东北、东南散；高地东沿的法军炮组朝东向下轰；路上丢着炮车 ──
  const T4 = { up: 11.03, down: 14.33 };
  const COL = { x: 3.51, cut: 0.10 }, CUT = 12.24;
  const place = (t, t0) => { const u = clamp((stepT(t, 12) - t0) / 0.25); return u <= 0 ? null : 0.6 + 0.4 * ease.outBack(u, 1.6); };
  const split = t => ease.out(clamp((stepT(t, 12) - CUT) / 0.40));
  const flee = t => ease.inOut(clamp((stepT(t, 8) - CUT) / 1.35)); // 散开的进度
  const gone = t => t > T4.down + 0.45;
  const near4 = t => camAt(t).pos[1] < 2.80;
  piece('barW', 1.7, t => { const s = place(t, 11.0); if (!s || t >= CUT || near4(t) || gone(t)) return null; return { x: COL.x, z: COL.cut, yaw: 0, scale: s }; });
  // 地图远景用两截绿条概括溃散的位置
  const halfPos = (t, sgn) => { const k = split(t), f = flee(t); return [COL.x + 0.03 + 0.04 * k + (sgn > 0 ? 0.46 : 0.4) * f, COL.cut + sgn * (0.43 + 0.14 * k + (sgn > 0 ? 0.07 : 0.16) * f)]; };
  piece('barA', 0.8, t => { if (t < CUT || near4(t) || gone(t)) return null; const k = split(t); const [x, z] = halfPos(t, -1); return { x, z, yaw: 0.2 * k, dy: 0.03 * Math.sin(Math.PI * k) }; });
  piece('barB', 0.8, t => { if (t < CUT || near4(t) || gone(t)) return null; const k = split(t); const [x, z] = halfPos(t, 1); return { x, z, yaw: -0.18 * k, dy: 0.03 * Math.sin(Math.PI * k) }; });
  const WEDGE = 1.0;
  const wedgeX = t => { const u = ease.inOut(clamp((stepT(t, 12) - 11.25) / 0.6)); return lerp(1.45, COL.x - WEDGE / 2 - 0.04, u) + 0.06 * split(t); };
  piece('wedge', WEDGE, t => { const s = place(t, 11.12); if (!s || gone(t)) return null; return { x: wedgeX(t), z: COL.cut, yaw: -Math.PI / 2, scale: s }; });
  S.cutPt = () => [COL.x, G0(COL.x, COL.cut) + 0.04, COL.cut];
  S.wedgeTail = t => { const x = wedgeX(t) - WEDGE / 2 + 0.05; return [x, G0(x, COL.cut) + 0.03, COL.cut]; };
  // 炮组：高地东沿，炮口朝东；人和炮在同一张图里，比例由原图保证（车轮到胸口）。
  // 橄榄绿炮架，三名炮手都在炮后左侧，炮口前空着。MZ 是原图里炮口的像素位置
  const MZ = [1582, 508];
  // 两个炮组在箭的南侧成梯次（北侧左上留给日期牌）；炮手站在台地边上，炮轮压在东沿坡口
  const GUNS = [[2.32, 0.72, 11.42], [2.29, 0.99, 11.48]];
  const SHOTS = [[0, 11.94, CUT, 0, 'blast-earth-a'], [1, 12.12, 12.47, -0.52, 'blast-earth-b'], [0, 12.61, 12.97, 0.48, 'blast-earth-a'], [1, 12.83, 13.20, 0.03, 'blast-shell'], [0, 13.12, 13.50, -0.42, 'blast-earth-b']];
  const recoil = (t, gi) => {
    let r = 0; for (const [g, f] of SHOTS) if (g === gi && t >= f) r = Math.max(r, 1 - (stepT(t - f, 12)) / 0.35);
    return r;
  };
  // 高度取炮手脚下与炮轮下地面的平均（不取整张纸片下的最低点，否则炮手的腿会埋进坡里）
  const guns = GUNS.map(([x, z, up], gi) => card('gun', 0.42, t => { const xx = x - 0.035 * recoil(t, gi); return { x: xx, y: (G0(xx - 0.17, z) + G0(xx + 0.12, z)) / 2 - 0.003, z, rise: rise(t, up, T4.down), yaw: 0.04 }; }));
  const muzzle0 = guns.map(g => { g.apply(11.93); const p = cardPt(g, MZ[0], MZ[1], 0.026); g.c.set({ rise: 0 }); return p; });
  // 落弹前拥成一路。首个落点把中间顶开，两端换东向纸片、错开向两侧跑。
  const ranks = [
    [-1, 'ruCol', 'ruRet', 0.27, 0.07, 0.20], [-1, 'au', 'auRet', 0.32, -0.21, 0.37],
    [-1, 'ru', 'ruRet', 0.29, 0.44, 0.26], [-1, 'ruCol', 'ruRet', 0.24, 0.36, 0.56],
    [-1, 'au', 'auRet', 0.34, 0.04, 0.65], [-1, 'ru', 'ruRet', 0.27, 0.52, 0.82],
    [1, 'ruCol', 'ruRet', 0.28, -0.10, 0.16], [1, 'au', 'auRet', 0.34, 0.21, 0.27],
    [1, 'ru', 'ruRet', 0.28, 0.58, 0.30], [1, 'au', 'auRet', 0.33, -0.24, 0.54],
    [1, 'ruCol', 'ruRet', 0.30, 0.28, 0.58], [1, 'au', 'auRet', 0.30, 0.57, 0.70],
  ];
  ranks.forEach(([sgn, advance, ret, h, dx, dz], i) => {
    const phase = ranksRand() * 0.12, scale = 0.92 + ranksRand() * 0.16, yaw = (ranksRand() - 0.5) * 0.25;
    const past = CUT + (i % 3) / 12;
    const zz = COL.cut + sgn * dz;
    const start = [COL.x + dx + 0.22, zz - 0.10], end = [COL.x + dx, zz];
    const a = card(advance, h, t => {
      if (t >= past) return null;
      const m = march(t + phase, 11.42 + phase, past + phase, start, end, { fps: 9 });
      return { ...m, rise: rise(t, 11.00 + (i % 4) * 0.06), yaw, scale };
    }, { follow: true, solid: false });
    const b = card(ret, h * (ret === 'auRet' ? 1.01 : 0.84), t => {
      if (t < past) return null;
      const p = march(t + phase, past + phase, 13.64 + phase, end, [end[0] + 0.32 + 0.05 * (i % 4), zz + sgn * (0.25 + dz * 0.14)], { fps: 9, run: true });
      return { ...p, rise: rise(t, 11.4, T4.down), yaw, scale };
    }, { follow: true, solid: false });
    if (i % 2 === 0) { a.c.front.color.setScalar(0.84); b.c.front.color.setScalar(0.87); }
  });
  [
    ['frRun', 'frFire', 0.43, [1.86, -0.42], [2.39, -0.41], 13.17],
    ['frCol', null, 0.51, [1.72, -1.18], [2.03, -1.20], null],
    ['frCol', null, 0.52, [1.66, 0.10], [1.99, 0.05], null],
    ['frCol', null, 0.54, [2.08, 1.42], [2.36, 1.38], null],
    ['frRun', null, 0.53, [1.67, 1.74], [1.96, 1.72], null],
    ['frCol', null, 0.40, [2.17, -0.18], [2.40, -0.17], null],
    ['frCol', null, 0.53, [1.82, 2.17], [2.32, 2.14], null],
  ].forEach(([k, fire, h, a, b, shot]) => rank(k, fire, h, a, b, 11.05, 12.37, 12.94, shot, T4.down));
  // 左翼纵队补在胸甲骑兵侧后方，留出炮口正前方。
  card('frCol', 0.46, t => {
    const m = march(t, 11.55, 12.45, [1.47, 1.14], [1.67, 1.19], { fps: 9 });
    return { ...m, rise: rise(t, 11.03, T4.down), yaw: 0.22 };
  }, { follow: true, solid: false });
  // 断口以外还在赶路的队，别把两翼挤回断口。
  for (const [k, h, x, z, dx, dz] of [
    ['ruCol', 0.48, 3.92, -1.64, 0.13, -0.05], ['auCol', 0.54, 4.32, -0.92, 0.18, -0.12],
    ['ruCol', 0.44, 4.70, -1.68, 0.13, -0.16], ['auCol', 0.59, 4.24, 1.09, 0.14, 0.20],
    ['ruCol', 0.41, 4.64, 0.53, 0.16, 0.15], ['auCol', 0.61, 4.06, 1.86, 0.11, 0.07],
    ['ruRet', 0.53, 3.61, 1.75, 0.26, 0.09],
  ]) rank(k, null, h, [x + dx, z + dz], [x, z], 11.03, 11.62, 12.22, null, T4.down, z < 0);
  // 东西对冲。俄骑在炮烟旁转向纵深退走，保留纸片正面的原朝向。
  for (const [k, h, a, meet, exit, delay] of [
    ['frHorse', 0.73, [1.90, 1.67], [2.89, 1.53], [3.72, 1.36], 0],
    ['ruHorse', 0.71, [4.55, 1.23], [3.74, 1.38], [4.15, -1.70], 0.04],
  ]) card(k, h, t => {
    const tt = stepT(t, 12), turn = 13.11 + delay, east = k === 'frHorse';
    const m = tt < turn ? march(t, 12.28 + delay, turn, a, meet, { fps: 10, bob: 0.043, run: true })
      : march(t, turn, east ? 13.87 : 14.32, meet, exit, { fps: 10, bob: 0.038, run: true });
    const yaw = east ? 0.11 : lerp(-0.14, -1.50, smooth(turn, turn + 0.32, tt));
    return { ...m, rise: rise(t, 11.97 + delay, T4.down), yaw };
  }, { solid: false });
  // 丢下的联军炮车（奥军赭黄炮架，整门侧翻、断轮）：沿高地北沿那条路排开，镜像、角度错开
  [[2.3, -0.98, 'wreck', 0.16, 0.12], [2.72, -1.02, 'wreckR', 0.15, -0.3], [3.12, -1.03, 'wreck', 0.155, 0.32]].forEach(([x, z, k, h, yaw], i) => card(k, h, still(x, z, 11.7 + i * 0.08, T4.down, { yaw })));
  // 东坡下的几棵果树（代替地图上的树林符号）
  [tree('orch', 0.36, 4.15, 1.1, 11.6, T4.down), tree('orchR', 0.32, 4.45, 0.5, 11.66, T4.down), tree('poplar', 0.7, 4.55, -0.45, 11.62, T4.down)].forEach(o => { o.c.mesh.castShadow = false; });
  // 炮弹沿同一条抛物线飞到换片的落点，第一发就是绿条断开的时刻。
  {
    const puffs = [], r = rng(404);
    SHOTS.forEach(([gi, t0, hit, dz, kind], i) => {
      const mz = () => cardPt(guns[gi], MZ[0], MZ[1], 0.03), m0 = muzzle0[gi];
      flash(t0, mz, 1, 0.33);
      const x = COL.x + (i ? 0.24 + r() * 0.27 : 0), z = COL.cut + dz + (i ? (r() - 0.5) * 0.10 : 0);
      const p = [x, G0(x, z) + (kind === 'blast-shell' ? 0.47 : 0.045), z];
      const life = hit - t0, arc = 0.29 + r() * 0.10;
      particles.push({ at: t0, life, a: m0, b: p, arc, tail: 0, kind: 2, size: 0.052, alpha: 1 });
      for (let q = 1; q <= 7; q++) {
        const lag = q * 0.019;
        particles.push({ at: t0 + lag, life: life - lag, a: m0, b: p, arc, tail: 0, kind: 3, size: 0.026 + q * 0.007, alpha: 0.64 - q * 0.058 });
      }
      blast(hit, p, i === 0 ? 0.47 : 0.33, kind);
      // 炮烟从原图炮口出，往东南飘。
      for (let q = 0; q < 3; q++) puffs.push({ t0: t0 + q * 0.047, life: 0.97, p: [m0[0] + 0.025 + q * 0.032, m0[1] + q * 0.009, m0[2] + q * 0.013], v: [0.08 + r() * 0.04, 0.065, 0.12], s0: 0.045, s1: 0.13 + r() * 0.025 });
    });
    const sm = world.paperSmoke(puffs);
    S.updaters.push((t, lp, cam, camera) => sm.set(t, camera, [1.0, 0.96, 0.9], 1 - smooth(13.72, 14.06, t)));
  }
  S.updaters.push(battleParticles(world, particles));

  // ── 镜头 5：12 月 4 日，烧毁的磨坊、驿路边的篝火；灰大衣的拿破仑向白军装的弗朗茨伸出手 ──
  for (const [k, h, x, z] of [['ruRet', 0.84, 4.89, 4.03], ['auRet', 0.82, 5.90, 3.52], ['ruRet', 0.74, 5.52, 4.90]]) {
    const o = rank(k, null, h, [x - 0.5, z - 0.24], [x, z], 13.47, 13.52, 14.83, null, 14.82, true);
    o.c.mesh.castShadow = false;
  }
  const T5 = 14.05;
  const millP = W5(0.3, -0.12);
  card('mill', 1.05, t => ({ x: millP[0], z: millP[1], rise: rise(t, T5, 99, 0.5), yaw: -0.08 }));
  for (const [k, lx, lz, h, up] of [['poplar', -1.7, -0.42, 0.95, 0.05], ['poplarR', 1.8, -0.55, 0.9, 0.1], ['orch', -1.05, -0.75, 0.44, 0.12], ['poplar', 2.25, 0.32, 0.78, 0.18], ['orchR', -2.15, 0.35, 0.42, 0.2], ['orch', 1.35, 0.35, 0.4, 0.22], ['orchR', -1.25, 1.75, 0.52, 0.3]]) {
    const p = W5(lx, lz); tree(k, h, p[0], p[1], T5 + up, 99);
  }
  { const p = W5(-1.95, -0.6); card('cottageR', 0.38, still(p[0], p[1], T5 + 0.15, 99, { yaw: 0.1 })); }
  const fireP = W5(-0.06, 0.78); S.fireAt = [fireP[0], 0.3, fireP[1]];
  card('logs', 0.11, still(fireP[0], fireP[1], T5 + 0.25, 99));
  puppetFire([fireP[0], G0(...fireP) + 0.04, fireP[1] - 0.015], { up: T5 + 0.4, h: 0.2, seed: 5, n: 3, spread: 0.05 });
  {
    const puffs = []; const r = rng(505);
    for (let i = 0; i < 9; i++) puffs.push({ t0: T5 + 0.5 + i * 0.34, life: 2.3, p: [fireP[0] + (r() - 0.5) * 0.04, 0.28, fireP[1] - 0.04], v: [0.04, 0.2, -0.05], s0: 0.04, s1: 0.13 + r() * 0.04 });
    const sm = world.paperSmoke(puffs, { tone: 'grey' }); S.updaters.push((t, lp, cam, camera) => sm.set(t, camera, [0.92, 0.91, 0.9], 1));
    const mp = []; for (let i = 0; i < 8; i++) mp.push({ t0: T5 + 0.2 + i * 0.4, life: 3.0, p: [millP[0] - 0.12 + (r() - 0.5) * 0.2, 0.8, millP[1]], v: [0.07, 0.17, -0.02], s0: 0.08, s1: 0.28 + r() * 0.06 });
    const sm2 = world.paperSmoke(mp, { tone: 'grey' }); S.updaters.push((t, lp, cam, camera) => sm2.set(t, camera, [0.9, 0.9, 0.9], 1));
  }
  const napA = W5(-1.12, 0.98), napB = W5(-0.39, 0.95), frzA = W5(1.1, 1.02), frzB = W5(0.27, 0.98);
  card('napHorse', 0.99, t => {
    if (stepT(t, 12) >= 15.92) return null;
    const m = march(t, 15.03, 15.92, W5(-2.63, 1.08), napA, { fps: 8, bob: 0.036 });
    return { ...m, rise: rise(t, 14.75), yaw: 0.08 };
  }, { solid: false });
  const nap5 = card('napG', 0.80, t => { if (stepT(t, 12) < 15.92) return null; const m = march(t, 15.95, 16.95, napA, napB, { fps: 8 }); return { ...m, rise: 1, yaw: 0.08 }; });
  const frz5 = card('frzG', 0.8, t => { const m = march(t, 16.05, 16.95, frzA, frzB, { fps: 8 }); const bow = smooth(16.95, 17.3, stepT(t, 12)) * 0.05; return { x: m.x, z: m.z, dy: m.dy, lean: m.lean + bow * 0.4, tilt: bow, rise: rise(t, 15.72, 99), yaw: -0.08 }; });
  S.nap5 = nap5; S.frz5 = frz5; S.millP = millP;
  { const a = edgeSpot(17.5, -1, 0.42, 1.04), b = edgeSpot(17.5, 1, 0.36, 0.95);
    tree('poplarR', 1.0, a[0], a[1], T5 + 0.1, 99); card('wall2', 0.2, still(b[0], b[1], T5 + 0.2, 99, { yaw: -0.4 })); }
  // 随员留在驿路两端，篝火前的会面只留两位君主。
  for (const [k, lx, lz, h] of [
    ['staff', -1.60, 1.45, 0.78], ['frCol', -1.82, -0.25, 0.53],
    ['auCol', 1.76, 0.13, 0.61], ['au', 1.37, 1.69, 0.47],
  ]) { const [x, z] = W5(lx, lz); card(k, h, still(x, z, T5 + 0.15, 99, { yaw: -0.08 }), { solid: false }); }
  const greyFog = [world.fogSheet({ w: 7, h: 1.2, rep: [2, 1], near: 0.6 })]; const gf = W5(0.2, -1.1); greyFog[0].mesh.position.set(gf[0], 0.45, gf[1]);
  S.updaters.push(t => greyFog[0].set(t, 0.28 * smooth(15.0, 15.8, t), [0.85, 0.86, 0.88], 0.01));

  // 红线：主图东南角的一枚红钉 → 桌面 → 小纸上的红钉（磨坊在主图之外的另一处）
  {
    const red = 0xa3221a;
    const A = [6.42, 5.2], B = W5(-2.82, 0.15);
    for (const [x, z] of [A, B]) { const g = world.pin(red, null); g.scale.setScalar(1.35); g.position.set(x, G0(x, z), z); }
    const lerp2 = (u) => [lerp(A[0], B[0], u), lerp(A[1], B[1], u)];
    const pts = [[A[0], G0(...A) + 0.07, A[1]]];
    for (const u of [0.1, 0.22, 0.34, 0.48, 0.62, 0.76, 0.9]) { const [x, z] = lerp2(u); pts.push([x, G0(x, z) + 0.012, z]); }
    pts.push([B[0], G0(...B) + 0.07, B[1]]);
    world.thread(pts, { radius: 0.02 });
  }

  world.S = S;
  return S;
}

// 世界点 → 屏幕点（随镜头走）
function pin3(world, fn) { return t => { const p = typeof fn === 'function' ? fn(t) : fn; const s = world.project(camAt(t), p); return { x: s.x, y: s.y }; }; }
function cardTop(world, obj, k = 1.02) { return t => { const p = obj.pose(t); const y = world.groundY(p.x, p.z) + obj.c.height * k; return [p.x, y, p.z]; }; }

// ───────────── 牌子时间表 ─────────────
// 同一时刻最多两三块：先地名，后字卡；名牌只在人物纸片够大时出现
function platesSpec(world) {
  const S = world.S;
  const A = fn => pin3(world, fn);
  return {
    date: [
      { at: 0, year: '1805', date: '12月1日', sub: '夜' },
      { at: 4.0, year: '1805', date: '12月2日', sub: '拂晓' },
      { at: 8.25, year: '1805', date: '12月2日', sub: '上午' },
      { at: 11.4, year: '1805', date: '12月2日', sub: '午后' },
      { at: 14.6, year: '1805', date: '12月4日' },
    ],
    cards: [
      { id: 'c1', from: 2.0, to: 3.45, text: '放空高地', side: 'a', anchor: A(t => { const c = S.frPinEnd; return [c[0], 0.25, c[1] + 0.35]; }), place: 'below' },
      { id: 'c2', from: 5.0, to: 7.05, text: '死守右翼', side: 'a', anchor: A(t => [-0.74, world.groundY(-0.74, 2.94) + 0.36, 2.94]), place: 'right' },
      { id: 'c3', from: 9.0, to: 10.2, text: '雾散出击', side: 'a', anchor: A(t => { const p = S.lead.pose(t); const x = p.x + 0.11; return [x, world.groundY(x, p.z) + S.lead.c.height * 0.7, p.z]; }), place: 'above' }, // 钉在排头兵的帽顶，牌子让开远处的拿破仑
      { id: 'c4', from: 12.27, to: 13.65, text: '断成两截', side: 'b', anchor: A(t => S.wedgeTail(t)), place: 'left' },
      { id: 'c5', from: 15.95, to: 17.04, text: '烧毁磨坊', anchor: A([S.millP[0] + 0.05, 0.93, S.millP[1]]), place: 'above' },
    ],
    names: [
      { id: 'n-nap1', from: 0.5, to: 1.45, text: '拿破仑', side: 'a', anchor: A(cardTop(world, S.napZ, 0.9)), place: 'right' },
      { id: 'n-nap3', from: 8.25, to: 8.84, text: '拿破仑', side: 'a', anchor: A(t => { const [x, y, z] = cardTop(world, S.napFar, 0.99)(t); return [x + 0.24, y, z]; }), place: 'right' },
      { id: 'n-soult', from: 9.6, to: 10.95, text: '苏尔特', side: 'a', anchor: A(t => { const p = S.lead.pose(t); return [p.x + 0.05, world.groundY(p.x, p.z) + 0.02, p.z]; }), place: 'below' },
      { id: 'n-nap5', from: 17.04, to: 18.5, text: '拿破仑', side: 'a', anchor: A(cardTop(world, S.nap5, 0.96)), place: 'above' },
      { id: 'n-franz', from: 17.05, to: 18.5, text: '弗朗茨二世', side: 'b', anchor: A(cardTop(world, S.frz5, 0.97)), place: 'right' },
    ],
    labels: [
      { id: 'l-zuran', from: 0.1, to: 1.45, text: '茹拉尼', anchor: A([PLACE.zuran[0] - 0.62, 0.06, PLACE.zuran[1] + 0.05]) },
      { id: 'l-pratzen', from: 1.75, to: 3.35, text: '普拉岑高地', anchor: A([PLACE.summit[0] + 0.45, 0.4, PLACE.summit[1] - 0.25]) },
      { id: 'l-telnitz', from: 4.4, to: 5.95, text: '特尔尼茨', anchor: A([-1.3, 0.3, 2.34]) },
    ],
  };
}
