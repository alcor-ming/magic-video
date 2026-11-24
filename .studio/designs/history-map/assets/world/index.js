// 作战地图桌世界：可复用，不写死哪一仗。片子传入地图数据、纸片、镜头和光的时间表。
import { clamp, lerp, mix3, canvas, loadImage, noise1 } from './util.js';
import { diecut, setGrain } from './diecut.js';
import { makeCard, makePin, makeRibbon, makeThread } from './card.js';
import { makeSheet, makeRelief, reliefEdgeMaterial, makeTable, makeCandle, chaikin, pip } from './table.js';
import { createPost } from './post.js';
import { makeFogSheet, makeSparks, makeRays, makePaperSmoke, paperPuffCanvas } from './atmo.js';
import { createCardBatches } from './batches.js';
import * as sprites from './sprites.js';

export { chaikin, sprites };
export { battleParticles } from './battle-particles.js';

// 光的预设（线性色）。sun: [方位角(北=0,东=90), 高度角]
export const LIGHTS = {
  night: { hemi: 0.42, sky: [0.2, 0.25, 0.42], ground: [0.07, 0.05, 0.04], sunI: 0.32, sunC: [0.55, 0.66, 1.0], sun: [35, 50], candle: 1, soft: 3, fogC: [0.015, 0.014, 0.022], fogD: 0.01, env: 0.35, exposure: 1.0, sat: 0.9, contrast: 1.05, lift: [0.012, 0.016, 0.032], gain: [1.0, 0.97, 0.92], vig: 0.62, bloom: 0.55, grain: 0.03, bg: [0.01, 0.01, 0.015] },
  // 拂晓：冷的天光打底，东南低处一道暖色的初阳斜扫（纸片的正面和近处地面带一点暖边）
  dawn: { hemi: 0.95, sky: [0.5, 0.6, 0.84], ground: [0.22, 0.2, 0.2], sunI: 1.55, sunC: [1.0, 0.68, 0.42], sun: [118, 10], candle: 0, soft: 5, fogC: [0.46, 0.5, 0.58], fogD: 0.075, env: 0.3, exposure: 1.1, sat: 0.86, contrast: 1.0, lift: [0.04, 0.05, 0.075], gain: [1.0, 0.98, 1.0], vig: 0.46, bloom: 0.38, grain: 0.028, bg: [0.3, 0.33, 0.4] },
  sun: { hemi: 1.05, sky: [0.55, 0.66, 0.9], ground: [0.3, 0.24, 0.16], sunI: 3.4, sunC: [1.0, 0.82, 0.58], sun: [128, 13], candle: 0, soft: 2.2, fogC: [0.62, 0.6, 0.58], fogD: 0.06, env: 0.6, exposure: 1.0, sat: 1.0, contrast: 1.04, lift: [0.03, 0.03, 0.05], gain: [1.03, 0.99, 0.93], vig: 0.42, bloom: 0.5, grain: 0.025, bg: [0.4, 0.42, 0.48] },
  // 午后：太阳抬高、减弱，影子短而淡（低太阳的长影会在高地北面拖出一大片来历不明的暗影）
  noon: { hemi: 1.5, sky: [0.6, 0.66, 0.8], ground: [0.32, 0.26, 0.18], sunI: 2.3, sunC: [1.0, 0.86, 0.66], sun: [196, 34], candle: 0, soft: 2.5, fogC: [0.6, 0.54, 0.46], fogD: 0.07, env: 0.6, exposure: 1.0, sat: 0.95, contrast: 1.03, lift: [0.035, 0.03, 0.03], gain: [1.04, 0.98, 0.9], vig: 0.45, bloom: 0.45, grain: 0.027, bg: [0.4, 0.38, 0.36] },
  overcast: { hemi: 1.75, sky: [0.78, 0.8, 0.84], ground: [0.36, 0.34, 0.32], sunI: 0.55, sunC: [0.92, 0.94, 1.0], sun: [210, 52], candle: 0, soft: 7, fogC: [0.7, 0.71, 0.72], fogD: 0.05, env: 0.5, exposure: 1.06, sat: 0.66, contrast: 0.95, lift: [0.07, 0.07, 0.08], gain: [0.98, 0.99, 1.0], vig: 0.4, bloom: 0.25, grain: 0.03, bg: [0.55, 0.56, 0.58] },
};
export function mixLight(a, b, u) {
  const o = {};
  for (const k of Object.keys(a)) { const va = a[k], vb = b[k] ?? va; o[k] = Array.isArray(va) ? (k === 'sun' ? [lerp(va[0], vb[0], u), lerp(va[1], vb[1], u)] : mix3(va, vb, u)) : lerp(va, vb, u); }
  return o;
}

function envTexture(renderer) {
  const THREE = window.THREE;
  const c = canvas(512, 256), x = c.getContext('2d');
  const g = x.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, '#1c1a1a'); g.addColorStop(0.45, '#3a3430'); g.addColorStop(0.55, '#5a4a3a'); g.addColorStop(1, '#241c16');
  x.fillStyle = g; x.fillRect(0, 0, 512, 256);
  const w = x.createRadialGradient(130, 80, 4, 130, 80, 70); w.addColorStop(0, 'rgba(255,240,220,1)'); w.addColorStop(1, 'rgba(255,240,220,0)'); x.fillStyle = w; x.fillRect(0, 0, 512, 256);
  const w2 = x.createRadialGradient(380, 110, 2, 380, 110, 40); w2.addColorStop(0, 'rgba(255,190,120,1)'); w2.addColorStop(1, 'rgba(255,190,120,0)'); x.fillStyle = w2; x.fillRect(0, 0, 512, 256);
  const t = new THREE.CanvasTexture(c); t.mapping = THREE.EquirectangularReflectionMapping; t.colorSpace = THREE.SRGBColorSpace;
  const pm = new THREE.PMREMGenerator(renderer); const rt = pm.fromEquirectangular(t); pm.dispose(); t.dispose();
  return rt;
}

export async function createWorld({ canvas: cv, quality = 'medium' }) {
  const THREE = globalThis.THREE;
  if (THREE?.REVISION !== '160') throw new Error('世界需要宿主提供的 r160 三维运行库');
  const hi = quality === 'high';
  const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: false, preserveDrawingBuffer: true, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(1); renderer.setSize(1920, 1080, false);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x000000, 0.01);
  scene.background = new THREE.Color(0, 0, 0);
  const camera = new THREE.PerspectiveCamera(35, 1920 / 1080, 0.05, 120);
  const projCam = camera.clone();
  const post = createPost(renderer, { quality });
  const environment = envTexture(renderer);
  const env = environment.texture;
  const batches = createCardBatches(THREE, scene);
  const resources = { textures: new Set(), cards: new WeakMap() };
  let disposed = false;

  const L = {};
  L.hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1); scene.add(L.hemi);
  L.sun = new THREE.DirectionalLight(0xffffff, 1); L.sun.castShadow = true;
  const sm = hi ? 4096 : 2048; L.sun.shadow.mapSize.set(sm, sm); L.sun.shadow.bias = -0.0004; L.sun.shadow.normalBias = 0.012;
  L.sun.shadow.camera.near = 0.5; L.sun.shadow.camera.far = 60;
  scene.add(L.sun); scene.add(L.sun.target);
  L.candle = new THREE.SpotLight(0xffc48a, 0, 0, 1.15, 1.0, 1.2); L.candle.castShadow = true;
  L.candle.shadow.mapSize.set(sm, sm); L.candle.shadow.bias = -0.0006; L.candle.shadow.normalBias = 0.015; L.candle.shadow.camera.near = 0.3; L.candle.shadow.camera.far = 40;
  scene.add(L.candle); scene.add(L.candle.target);
  L.fill = new THREE.PointLight(0xff9a50, 0, 0, 1.6); scene.add(L.fill); // 火堆等局部暖光

  const tex = {};
  const textureURL = name => new URL(`./textures/${name}.webp`, import.meta.url);
  let grainTex, woodTex, fogTex, grainImg;
  try {
    [grainTex, woodTex, fogTex] = await Promise.all(['paper-grain', 'wood', 'fog'].map(async name => {
      const image = await loadImage(textureURL(name).href);
      const texture = new THREE.Texture(image);
      texture.needsUpdate = true;
      resources.textures.add(texture);
      return texture;
    }));
    grainImg = grainTex.image;
  } catch (error) {
    environment.dispose();
    post.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    throw error;
  }
  setGrain(grainImg);
  grainTex.wrapS = grainTex.wrapT = THREE.RepeatWrapping; grainTex.colorSpace = THREE.NoColorSpace; grainTex.repeat.set(3, 3);
  Object.assign(tex, { grain: grainTex, wood: woodTex, fog: fogTex });

  const table = makeTable(woodTex); scene.add(table);
  table.material.envMap = env;
  const glossy = [table.material];
  const edgeMat = reliefEdgeMaterial();

  const sheets = []; const reliefs = []; const paperTex = {};
  const world = {
    THREE, renderer, scene, camera, lights: L, tex, env, sheets, reliefs, quality,
    async image(url) { return loadImage(new URL(url, import.meta.url).href); },
    ownTexture(texture) { resources.textures.add(texture); return texture; },
    texts() { return []; },
    diecut, makeCard(dc, options = {}) {
      const c = makeCard(dc, { grainTex, ...options }, resources);
      scene.add(c.root);
      return options.batch ? batches.add(c, options.solid === false) : c;
    },
    sheet(opts) { const s = makeSheet({ grain: grainTex, ...opts }); scene.add(s.group); sheets.push(s); return s; },
    relief(sheet, layers, step = 0.055) { const r = makeRelief(layers, { sheet, step, edgeMat }); scene.add(r.group); reliefs.push(r); return r; },
    candle() { const c = makeCandle(); scene.add(c.group); c.group.traverse(o => { if (o.material && o.material.metalness === 1) { o.material.envMap = env; glossy.push(o.material); } }); return c; },
    pin(color, flag, o) { const p = makePin(color, flag, o, resources); scene.add(p); p.traverse(o => { if (o.material && (o.material.metalness === 1 || o.material.clearcoat)) { o.material.envMap = env; glossy.push(o.material); } }); return p; },
    ribbon(path, o) { const r = makeRibbon(path, { groundY: world.groundSmooth, ...o }); scene.add(r.root); return r; },
    fogSheet(o) { const f = makeFogSheet(fogTex, o); scene.add(f.mesh); return f; },
    // 纸烟团：tone 'white'（枪炮烟）或 'grey'（焚烧的烟）
    paperSmoke(puffs, { tone = 'white' } = {}) {
      if (!paperTex[tone]) paperTex[tone] = [11, 23, 37, 51].map(sd => { const t = new THREE.CanvasTexture(paperPuffCanvas(sd + (tone === 'grey' ? 100 : 0), tone === 'grey' ? { tone: [214, 210, 204], shade: [142, 138, 134], ink: 'rgba(70,60,52,.6)' } : {})); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t; });
      const s = makePaperSmoke(paperTex[tone], puffs); scene.add(s.group); return s;
    },
    thread(points, o) { const m = makeThread(points, o); scene.add(m); return m; },
    sparks(items) { const s = makeSparks(items); scene.add(s.group); return s; },
    rays(n) { const r = makeRays(n); scene.add(r.group); return r; },
    // 地面高度：叠层高地顶 > 纸面 > 桌面
    groundY(x, z) {
      for (const r of reliefs) for (let i = r.tops.length - 1; i >= 0; i--) if (pip([x, z], r.tops[i].poly)) return r.tops[i].y;
      for (let i = sheets.length - 1; i >= 0; i--) { const s = sheets[i]; if (s.inside(x, z)) { const [lx, lz] = s.toLocal(x, z); return s.height(lx, lz); } }
      return 0;
    },
    // 平滑过的地面（纸条盖在台阶上的样子）
    groundSmooth(x, z) { let s = 0, n = 0; for (const [dx, dz] of [[0, 0], [0.09, 0], [-0.09, 0], [0, 0.09], [0, -0.09], [0.06, 0.06], [-0.06, -0.06], [0.06, -0.06], [-0.06, 0.06]]) { s += world.groundY(x + dx, z + dz); n++; } return Math.max(world.groundY(x, z), s / n); },
    setCamera(c) {
      camera.position.set(...c.pos); camera.fov = c.fov || 35; camera.near = c.near || 0.05; camera.far = 120;
      camera.up.set(0, 1, 0); camera.lookAt(...c.tgt); if (c.roll) camera.rotateZ(c.roll); camera.updateProjectionMatrix(); camera.updateMatrixWorld();
    },
    // 纯函数投影：给牌子的 anchor 用，不依赖当前渲染状态
    project(c, p) {
      projCam.position.set(...c.pos); projCam.fov = c.fov || 35; projCam.near = c.near || 0.05; projCam.up.set(0, 1, 0); projCam.lookAt(...c.tgt); if (c.roll) projCam.rotateZ(c.roll);
      projCam.updateProjectionMatrix(); projCam.updateMatrixWorld();
      const v = new THREE.Vector3(...p).project(projCam);
      return { x: (v.x * 0.5 + 0.5) * 1920, y: (1 - (v.y * 0.5 + 0.5)) * 1080, behind: v.z > 1 };
    },
    setLight(lp, focusPt, span, t) {
      L.hemi.color.setRGB(...lp.sky); L.hemi.groundColor.setRGB(...lp.ground); L.hemi.intensity = lp.hemi;
      const az = lp.sun[0] * Math.PI / 180, el = lp.sun[1] * Math.PI / 180;
      const d = [Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)];
      L.sun.color.setRGB(...lp.sunC); L.sun.intensity = lp.sunI; L.sun.visible = lp.sunI > 0.001; L.sun.castShadow = lp.sunI > 0.5;
      L.sun.target.position.set(...focusPt); L.sun.position.set(focusPt[0] + d[0] * 30, focusPt[1] + d[1] * 30, focusPt[2] + d[2] * 30);
      const sc = L.sun.shadow.camera; const h = span; sc.left = -h; sc.right = h; sc.top = h; sc.bottom = -h; sc.updateProjectionMatrix();
      L.sun.shadow.radius = lp.soft; L.candle.shadow.radius = Math.max(2, lp.soft);
      L.sun.target.updateMatrixWorld();
      scene.fog.color.setRGB(...lp.fogC); scene.fog.density = lp.fogD;
      scene.background.setRGB(...lp.bg);
      for (const m of glossy) m.envMapIntensity = lp.env;
    },
    render(p) {
      batches.update(camera);
      post.render(scene, camera, p);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      batches.dispose();
      const geometries = new Set();
      const materials = new Set([edgeMat]);
      scene.traverse(object => {
        if (object.geometry && !object.isSprite) geometries.add(object.geometry);
        for (const material of [object.material, object.customDepthMaterial, object.customDistanceMaterial].flat()) {
          if (material) materials.add(material);
        }
      });
      for (const material of materials) {
        for (const value of Object.values(material)) {
          if (value?.isTexture && value !== env) resources.textures.add(value);
        }
        for (const uniform of Object.values(material.uniforms || {})) {
          if (uniform.value?.isTexture) resources.textures.add(uniform.value);
        }
        material.dispose();
      }
      for (const geometry of geometries) geometry.dispose();
      for (const texture of resources.textures) texture.dispose();
      for (const light of [L.sun, L.candle]) light.shadow.dispose();
      environment.dispose();
      post.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      scene.clear();
    },
  };
  return world;
}
