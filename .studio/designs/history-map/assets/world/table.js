// 桌面世界：木桌、纸地图（折痕、翘边）、硬纸板叠成的高地、烛台、另一张小纸。
import { canvas, clamp, noise1 } from './util.js';
import { planMap, drawMapView, pip, polyDist, slopeW } from './mapdraw.js';

const T = () => window.THREE;

export function chaikin(pts, it = 3, closed = true) {
  let p = pts;
  for (let k = 0; k < it; k++) {
    const q = []; const n = p.length;
    for (let i = 0; i < (closed ? n : n - 1); i++) { const a = p[i], b = p[(i + 1) % n]; q.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25], [a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]); }
    if (!closed) { q.unshift(p[0]); q.push(p[n - 1]); }
    p = q;
  }
  return p;
}

// 世界 xz → 纹理 uv 的仿射（两行）。rect 是纸面局部坐标 [x0, z0(北), x1, z1(南)]，纸绕 center 转 rot。
function affine(rect, rot = 0, center = [0, 0]) {
  const [x0, z0, x1, z1] = rect, C = Math.cos(rot), S = Math.sin(rot), [cx, cz] = center;
  const sx = 1 / (x1 - x0), sz = 1 / (z1 - z0);
  return [[C * sx, -S * sx, (-C * cx + S * cz - x0) * sx], [-S * sz, -C * sz, 1 + (S * cx + C * cz + z0) * sz]];
}

export function mapMaterial({ base, A, details = [], grain, grainScale = 0.85, alphaTest = 0 }) {
  const THREE = T();
  const mat = new THREE.MeshStandardMaterial({ roughness: 0.92, metalness: 0, alphaTest });
  const V3 = a => new THREE.Vector3(...a);
  const d0 = details[0], d1 = details[1];
  mat.userData.uniforms = {
    uBase: { value: base }, uA0: { value: V3(A[0]) }, uA1: { value: V3(A[1]) },
    uDet0: { value: d0 ? d0.tex : base }, uD0a: { value: V3(d0 ? d0.A[0] : [0, 0, -9]) }, uD0b: { value: V3(d0 ? d0.A[1] : [0, 0, -9]) },
    uDet1: { value: d1 ? d1.tex : base }, uD1a: { value: V3(d1 ? d1.A[0] : [0, 0, -9]) }, uD1b: { value: V3(d1 ? d1.A[1] : [0, 0, -9]) },
    uGrain: { value: grain }, uGS: { value: grainScale },
  };
  mat.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, mat.userData.uniforms);
    sh.vertexShader = 'varying vec2 vWXZ;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n  vWXZ = (modelMatrix * vec4(transformed, 1.0)).xz;');
    sh.fragmentShader = `varying vec2 vWXZ; uniform sampler2D uBase, uDet0, uDet1, uGrain; uniform vec3 uA0, uA1, uD0a, uD0b, uD1a, uD1b; uniform float uGS;
vec4 detailMix(vec4 c, sampler2D tx, vec3 a, vec3 b){ vec3 p = vec3(vWXZ, 1.); vec2 uv = vec2(dot(a, p), dot(b, p)); vec2 e = min(uv, 1. - uv); float w = smoothstep(0., 0.05, min(e.x, e.y)); vec4 d = texture2D(tx, clamp(uv, 0., 1.)); return mix(c, d, w * step(0.0001, d.a)); }
` + sh.fragmentShader.replace('#include <map_fragment>', `
  vec3 pw = vec3(vWXZ, 1.);
  vec4 mc = texture2D(uBase, vec2(dot(uA0, pw), dot(uA1, pw)));
  mc = detailMix(mc, uDet0, uD0a, uD0b);
  mc = detailMix(mc, uDet1, uD1a, uD1b);
  float gr = texture2D(uGrain, vWXZ * uGS).r;
  mc.rgb *= 1.0 + (gr - 0.5) * 0.28;
  diffuseColor *= mc;`);
  };
  mat.customProgramCacheKey = () => 'mapmat';
  return mat;
}

function canvasTex(c, aniso = 8) {
  const THREE = T(); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = aniso; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; return t;
}

/**
 * 一张纸（地图或小纸），axis-aligned 的数据坐标，可整体平移旋转。
 * opts: { data, center:[x,z], rot, pxPerUnit, details:[{rect:[x0,z0,x1,z1], ppu}], grain, assets, curl, creases }
 * data 的坐标是纸面局部坐标（纸中心为原点）。
 */
export function makeSheet(opts) {
  const THREE = T();
  const { data, center = [0, 0], rot = 0, ppu = 280, details = [], grain, assets = {}, curl = 1, creases = { x: [], z: [] }, seed = 7, lift = 0 } = opts;
  const [W, H] = data.size;
  const plan = planMap(data, seed);
  const draw = (rect, ppuX) => { const c = canvas(Math.round((rect[2] - rect[0]) * ppuX), Math.round((rect[3] - rect[1]) * ppuX)); drawMapView(plan, c.getContext('2d'), { x0: rect[0], z0: rect[1], x1: rect[2], z1: rect[3], W: c.width, H: c.height }, assets); return c; };
  const baseRect = [-W / 2, -H / 2, W / 2, H / 2];
  const baseC = draw(baseRect, ppu);
  const base = canvasTex(baseC);
    const dets = details.map(d => ({ tex: canvasTex(draw(d.rect, d.ppu)), A: affine(d.rect, rot, center) }));
  const mat = mapMaterial({ base, A: affine(baseRect, rot, center), details: dets, grain, alphaTest: 0.5 });
  // 纸面高度：地形（纸蒙在缓坡上）+ 折痕 + 轻微起伏 + 四边翘起
  const hills = (data.hills || []).filter(h => h.h > 0);
  const terrain = (lx, lz) => {
    let h = 0;
    for (const hl of hills) {
      const bb = hl.bb || (hl.bb = [Math.min(...hl.pts.map(p => p[0])), Math.min(...hl.pts.map(p => p[1])), Math.max(...hl.pts.map(p => p[0])), Math.max(...hl.pts.map(p => p[1]))]);
      if (lx < bb[0] || lx > bb[2] || lz < bb[1] || lz > bb[3]) continue;
      const { d } = polyDist([lx, lz], hl.pts); if (d <= 0) continue;
      const u = clamp(d / slopeW(hl, lx)); const sm = u * u * (3 - 2 * u);
      h = Math.max(h, hl.h * sm * (1 + 0.05 * Math.sin(lx * 3.1 + lz * 2.3) * u));
    }
    return h;
  };
  const surf = (lx, lz) => {
    let h = 0.004 + lift + terrain(lx, lz);
    for (const cx of creases.x) { const d = Math.abs(lx - cx); if (d < 0.2) h += 0.011 * (1 - d / 0.2) ** 2; }
    for (const cz of creases.z) { const d = Math.abs(lz - cz); if (d < 0.2) h -= 0.006 * (1 - d / 0.2) ** 2; }
    h += 0.0035 * Math.sin(lx * 0.9 + lz * 0.4 + seed) * Math.sin(lz * 1.1 - lx * 0.3);
    const ex = W / 2 - Math.abs(lx), ez = H / 2 - Math.abs(lz);
    const cxf = Math.max(0, 1 - ex / 0.8), czf = Math.max(0, 1 - ez / 0.8);
    h += curl * (0.035 * cxf * cxf + 0.03 * czf * czf + 0.11 * Math.pow(cxf * czf, 1.4));
    return Math.max(0.0015, h);
  };
  const sx = Math.round(W / 0.05), sz = Math.round(H / 0.05);
  const grid = new Float32Array((sx + 1) * (sz + 1));
  for (let j = 0; j <= sz; j++) for (let i = 0; i <= sx; i++) grid[j * (sx + 1) + i] = surf(-W / 2 + i * W / sx, -H / 2 + j * H / sz);
  // 与网格一致的双线性取高（立在地上的纸片用它）
  const height = (lx, lz) => {
    const fx = clamp((lx + W / 2) / W * sx, 0, sx - 1e-6), fz = clamp((lz + H / 2) / H * sz, 0, sz - 1e-6);
    const i = Math.floor(fx), j = Math.floor(fz), u = fx - i, v = fz - j, r = sx + 1;
    const a = grid[j * r + i], b = grid[j * r + i + 1], c = grid[(j + 1) * r + i], d = grid[(j + 1) * r + i + 1];
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v;
  };
  const geo = new THREE.PlaneGeometry(W, H, sx, sz); geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, grid[i]);
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, mat); mesh.receiveShadow = true; mesh.castShadow = true;
  mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking });
  const grp = new THREE.Group(); grp.add(mesh); grp.position.set(center[0], 0, center[1]); grp.rotation.y = rot;
  // 世界坐标 → 纸面局部坐标
  const c = Math.cos(rot), s = Math.sin(rot);
  const toLocal = (x, z) => { const dx = x - center[0], dz = z - center[1]; return [c * dx - s * dz, s * dx + c * dz]; };
  const toWorld = (lx, lz) => [center[0] + c * lx + s * lz, center[1] - s * lx + c * lz];
  const inside = (x, z) => { const [lx, lz] = toLocal(x, z); return Math.abs(lx) < W / 2 - 0.02 && Math.abs(lz) < H / 2 - 0.02; };
  return { group: grp, mesh, mat, plan, height, toLocal, toWorld, inside, W, H, center, rot, data };
}

/** 硬纸板叠层高地：layers 为世界坐标多边形（由低到高），step 每层厚。top 面印地图。 */
export function makeRelief(layers, { sheet, step = 0.055, edgeMat }) {
  const THREE = T();
  const grp = new THREE.Group(); const tops = [];
  layers.forEach((poly, li) => {
    let area = 0; for (let i = 0; i < poly.length; i++) { const a = poly[i], b = poly[(i + 1) % poly.length]; area += a[0] * b[1] - b[0] * a[1]; }
    const p = area < 0 ? poly.slice().reverse() : poly; // 统一方向
    let hmax = 0; for (const q of p) { const [lx, lz] = sheet.toLocal(q[0], q[1]); hmax = Math.max(hmax, sheet.height(lx, lz)); }
    const yTop = hmax + step * (li + 1), yBot = hmax + step * li - 0.012;
    const P = [], N = [], U = [], I0 = [], I1 = [];
    const tris = THREE.ShapeUtils.triangulateShape(p.map(q => new THREE.Vector2(q[0], q[1])), []);
    for (const q of p) { P.push(q[0], yTop, q[1]); N.push(0, 1, 0); U.push(0, 0); }
    for (let [a, b, c] of tris) { const A = p[a], B = p[b], C = p[c]; const cy = (B[1] - A[1]) * (C[0] - A[0]) - (B[0] - A[0]) * (C[1] - A[1]); if (cy < 0) [b, c] = [c, b]; I0.push(a, b, c); }
    let per = 0; const n = p.length;
    for (let i = 0; i < n; i++) {
      const a = p[i], b = p[(i + 1) % n]; const dx = b[0] - a[0], dz = b[1] - a[1], L = Math.hypot(dx, dz) || 1;
      // 逆时针（x 右 z 下的屏幕系里 area>0）时外法线为 (dz, -dx)
      const nx = dz / L, nz = -dx / L; const k = P.length / 3;
      P.push(a[0], yTop, a[1], b[0], yTop, b[1], b[0], yBot, b[1], a[0], yBot, a[1]);
      for (let j = 0; j < 4; j++) N.push(nx, 0, nz);
      U.push(per, 1, per + L, 1, per + L, 0, per, 0); per += L;
      I1.push(k, k + 2, k + 1, k, k + 3, k + 2);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(N, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(U, 2));
    g.setIndex(I0.concat(I1)); g.addGroup(0, I0.length, 0); g.addGroup(I0.length, I1.length, 1);
    const m = new THREE.Mesh(g, [sheet.mat, edgeMat]); m.castShadow = true; m.receiveShadow = true;
    m.customDepthMaterial = sheet.mesh.customDepthMaterial;
    grp.add(m); tops.push({ poly: p, y: yTop });
  });
  return { group: grp, tops };
}

export function reliefEdgeMaterial() {
  const THREE = T();
  const c = canvas(64, 64), x = c.getContext('2d');
  x.fillStyle = '#ece3d0'; x.fillRect(0, 0, 64, 64);
  x.fillStyle = '#d4c7ad'; x.fillRect(0, 20, 64, 2); x.fillRect(0, 42, 64, 2);
  x.fillStyle = '#f7f1e4'; x.fillRect(0, 0, 64, 4);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping;
  return new THREE.MeshStandardMaterial({ map: t, roughness: 0.95 });
}

export function makeTable(woodTex) {
  const THREE = T();
  woodTex.wrapS = woodTex.wrapT = THREE.RepeatWrapping; woodTex.repeat.set(3, 2.6); woodTex.colorSpace = THREE.SRGBColorSpace; woodTex.anisotropy = 8;
  const mat = new THREE.MeshPhysicalMaterial({ map: woodTex, roughness: 0.5, clearcoat: 0.55, clearcoatRoughness: 0.32, metalness: 0 });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(60, 52), mat); m.rotation.x = -Math.PI / 2; m.receiveShadow = true;
  return m;
}

// 烛台：黄铜车削件 + 蜡烛 + 火苗（精灵）
export function makeCandle() {
  const THREE = T();
  const g = new THREE.Group();
  const prof = [[0, 0], [0.62, 0], [0.66, 0.025], [0.64, 0.07], [0.5, 0.1], [0.22, 0.15], [0.13, 0.22], [0.11, 0.38], [0.16, 0.44], [0.1, 0.5], [0.085, 0.9], [0.13, 0.96], [0.09, 1.02], [0.1, 1.1], [0.28, 1.17], [0.31, 1.21], [0.26, 1.23], [0.15, 1.25], [0, 1.25]].map(p => new THREE.Vector2(p[0], p[1]));
  const brass = new THREE.MeshStandardMaterial({ color: 0xc9a062, metalness: 1, roughness: 0.28 });
  const stick = new THREE.Mesh(new THREE.LatheGeometry(prof, 48), brass); stick.castShadow = true; stick.receiveShadow = true; g.add(stick);
  // 蜡：顶部略凹，带几道蜡泪
  const wax = new THREE.MeshStandardMaterial({ color: 0xf1e8d3, roughness: 0.6, emissive: 0xffa040, emissiveIntensity: 0 });
  const cyl = new THREE.Mesh(new THREE.CylinderGeometry(0.125, 0.13, 0.95, 32), wax); cyl.position.y = 1.25 + 0.475; cyl.castShadow = true; g.add(cyl);
  for (let i = 0; i < 4; i++) { const d = new THREE.Mesh(new THREE.CapsuleGeometry(0.022, 0.18 + i * 0.07, 4, 8), wax); const a = i * 1.7 + 0.3; d.position.set(Math.cos(a) * 0.125, 2.1 - i * 0.05 - (0.09 + i * 0.035), Math.sin(a) * 0.125); g.add(d); }
  const wick = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.07, 6), new THREE.MeshStandardMaterial({ color: 0x1a1410 })); wick.position.y = 2.235; g.add(wick);
  const fc = canvas(128, 256), fx = fc.getContext('2d');
  const gr = fx.createRadialGradient(64, 170, 4, 64, 150, 110);
  gr.addColorStop(0, 'rgba(255,255,240,1)'); gr.addColorStop(0.18, 'rgba(255,236,170,1)'); gr.addColorStop(0.45, 'rgba(255,160,60,.85)'); gr.addColorStop(1, 'rgba(255,90,20,0)');
  fx.fillStyle = gr; fx.beginPath(); fx.moveTo(64, 6); fx.bezierCurveTo(100, 90, 104, 170, 64, 236); fx.bezierCurveTo(24, 170, 28, 90, 64, 6); fx.fill();
  const ft = new THREE.CanvasTexture(fc); ft.colorSpace = THREE.SRGBColorSpace;
  const flame = new THREE.Mesh(new THREE.PlaneGeometry(0.11, 0.24), new THREE.MeshBasicMaterial({ map: ft, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: new THREE.Color(5, 4, 3) }));
  flame.position.y = 2.33; g.add(flame);
  const hc = canvas(128, 128), hx = hc.getContext('2d'); const hg = hx.createRadialGradient(64, 64, 0, 64, 64, 64);
  hg.addColorStop(0, 'rgba(255,190,110,.9)'); hg.addColorStop(0.25, 'rgba(255,150,70,.35)'); hg.addColorStop(1, 'rgba(255,120,40,0)'); hx.fillStyle = hg; hx.fillRect(0, 0, 128, 128);
  const halo = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.1), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(hc), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: new THREE.Color(1.4, 1.2, 1) }));
  halo.position.y = 2.32; g.add(halo);
  g.scale.setScalar(1.25);
  return {
    group: g, flame, halo, wax, flameY: 2.33 * 1.25,
    set(t, on, cam) {
      flame.visible = halo.visible = on > 0.01;
      const f = 1 + 0.12 * noise1(t * 9, 3) + 0.06 * noise1(t * 23, 4);
      flame.scale.set(on * (1 - 0.06 * noise1(t * 11, 5)), on * f, 1);
      flame.position.x = 0.012 * noise1(t * 5, 6);
      halo.material.opacity = 0.8 * on * (0.92 + 0.08 * f);
      wax.emissiveIntensity = 0.18 * on;
      if (cam) { flame.quaternion.copy(cam.quaternion); halo.quaternion.copy(cam.quaternion); }
      return f;
    },
  };
}

export { pip };
