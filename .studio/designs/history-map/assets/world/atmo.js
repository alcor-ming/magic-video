// 氛围：雾片、炮烟/枪烟团、炮口火光、刺刀反光、光柱。全部由 t 决定（出生时刻、位置都在数据里）。
import { canvas, clamp, ease, smooth } from './util.js';

const T = () => window.THREE;

const FOG_VS = `varying vec2 vUv; varying float vFogDepth; void main(){ vUv = uv; vec4 mv = modelViewMatrix * vec4(position, 1.); vFogDepth = -mv.z; gl_Position = projectionMatrix * mv; }`;
const FOG_FS = `precision highp float; varying vec2 vUv; varying float vFogDepth; uniform sampler2D map; uniform float uOff; uniform float uOff2; uniform float uOp; uniform vec3 uCol; uniform vec2 uRep; uniform float uNear;
void main(){
  float a = texture2D(map, vUv * uRep + vec2(uOff, 0.)).r * 0.65 + texture2D(map, vUv * uRep * 0.55 + vec2(-uOff2, 0.37)).r * 0.55;
  float e = smoothstep(0., .22, vUv.x) * smoothstep(1., .78, vUv.x) * smoothstep(0., .3, vUv.y) * smoothstep(1., .35, vUv.y);
  float nearFade = smoothstep(uNear, uNear * 2.2, vFogDepth);
  gl_FragColor = vec4(uCol, clamp(a, 0., 1.) * e * uOp * nearFade);
}`;

export function makeFogSheet(tex, { w = 4, h = 1, rep = [2, 1], horizontal = false, near = 0.6 } = {}) {
  const THREE = T();
  const t = tex.clone(); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({ vertexShader: FOG_VS, fragmentShader: FOG_FS, transparent: true, depthWrite: false,
    uniforms: { map: { value: t }, uOff: { value: 0 }, uOff2: { value: 0 }, uOp: { value: 0.5 }, uCol: { value: new THREE.Color(1, 1, 1) }, uRep: { value: new THREE.Vector2(...rep) }, uNear: { value: near } } });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  if (horizontal) m.rotation.x = -Math.PI / 2;
  m.renderOrder = 5;
  return {
    mesh: m,
    set(t, op, col, speed = 0.02) { m.visible = op > 0.003; mat.uniforms.uOp.value = op; mat.uniforms.uOff.value = t * speed; mat.uniforms.uOff2.value = t * speed * 0.6; if (col) mat.uniforms.uCol.value.setRGB(col[0], col[1], col[2]); },
  };
}

function glowTex(kind) {
  const c = canvas(128, 128), x = c.getContext('2d');
  if (kind === 'star') {
    const g = x.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.12, 'rgba(255,250,230,.8)'); g.addColorStop(0.4, 'rgba(255,240,200,.12)'); g.addColorStop(1, 'rgba(255,240,200,0)');
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
    x.globalCompositeOperation = 'lighter';
    for (const [w, h] of [[128, 5], [5, 128], [70, 3], [3, 70]]) { const gg = x.createLinearGradient(64 - w / 2, 64 - h / 2, 64 + w / 2, 64 + h / 2); gg.addColorStop(0, 'rgba(255,255,255,0)'); gg.addColorStop(0.5, 'rgba(255,255,250,.95)'); gg.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = gg; x.fillRect(64 - w / 2, 64 - h / 2, w, h); }
  } else {
    const g = x.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,230,1)'); g.addColorStop(0.2, 'rgba(255,200,110,.9)'); g.addColorStop(0.55, 'rgba(255,120,40,.3)'); g.addColorStop(1, 'rgba(255,80,20,0)');
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  }
  const t = new (T().CanvasTexture)(c); t.colorSpace = T().SRGBColorSpace; return t;
}

/** 烟团系统。puffs: [{ t0, life, p:[x,y,z], v:[vx,vy,vz], s0, s1, a }]。 */
export function makeSmoke(puffTex, puffs) {
  const THREE = T();
  const grp = new THREE.Group();
  const sprites = puffs.map((p, i) => {
    const m = new THREE.SpriteMaterial({ map: puffTex, transparent: true, depthWrite: false, color: 0xffffff, opacity: 0, rotation: (i * 2.4) % 6.28 });
    const s = new THREE.Sprite(m); s.renderOrder = 6; grp.add(s); return s;
  });
  return {
    group: grp, puffs,
    set(t, col, k = 1) {
      puffs.forEach((p, i) => {
        const s = sprites[i]; const age = t - p.t0;
        if (age < 0 || age > p.life || k <= 0) { s.visible = false; return; }
        const u = age / p.life; s.visible = true;
        const e = ease.out(u);
        s.position.set(p.p[0] + p.v[0] * e * p.life, p.p[1] + p.v[1] * e * p.life, p.p[2] + p.v[2] * e * p.life);
        const sc = p.s0 + (p.s1 - p.s0) * ease.out(Math.min(1, u * 1.3)); s.scale.set(sc, sc, 1);
        s.material.opacity = (p.a ?? 0.7) * k * smooth(0, 0.08, u) * (1 - smooth(0.35, 1, u));
        s.material.rotation = (i * 2.4 + age * 0.25) % 6.28;
        if (col) s.material.color.setRGB(col[0], col[1], col[2]);
      });
    },
  };
}

// 纸烟团：几瓣圆弧叠成的云朵，撕边白纸 + 下沿淡灰 + 稀疏墨线。alpha 里存「离边多深」（0.52…1），
// 消散时把 alphaTest 从 0.5 抬到 1，烟团从边缘往里一点点被溶掉，不做半透明淡出。
export function paperPuffCanvas(seed = 1, { S = 256, tone = [247, 244, 236], shade = [196, 192, 186], ink = 'rgba(92,80,66,.55)' } = {}) {
  let a = (seed * 2654435761) >>> 0 || 1; const r = () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const c = canvas(S, S), x = c.getContext('2d');
  // 瓣：底部一排大瓣，上面两三瓣
  const lobes = []; const n = 5 + Math.floor(r() * 3);
  for (let i = 0; i < n; i++) {
    const top = i >= 3; const u = top ? 0.32 + r() * 0.36 : 0.22 + (i / 2) * 0.28 + (r() - 0.5) * 0.08;
    lobes.push([S * u, S * (top ? 0.38 + r() * 0.12 : 0.58 + r() * 0.08), S * (top ? 0.15 + r() * 0.06 : 0.17 + r() * 0.05)]);
  }
  const shape = (grow, jit) => { // 外形：各瓣圆周上加手撕抖动
    x.beginPath();
    for (const [cx, cy, rr] of lobes) { const m = 28; for (let k = 0; k <= m; k++) { const t = k / m * Math.PI * 2; const R = rr * grow + (r() - 0.5) * jit; k ? x.lineTo(cx + Math.cos(t) * R, cy + Math.sin(t) * R) : x.moveTo(cx + Math.cos(t) * R, cy + Math.sin(t) * R); } x.closePath(); }
  };
  // 1. 撕边纸底（略大一圈，偏冷白）
  x.fillStyle = 'rgb(252,251,247)'; shape(1.12, S * 0.03); x.fill();
  // 2. 每瓣：上亮下暗
  for (const [cx, cy, rr] of lobes) {
    const g = x.createLinearGradient(0, cy - rr, 0, cy + rr); g.addColorStop(0, `rgb(${tone})`); g.addColorStop(0.55, `rgb(${tone})`); g.addColorStop(1, `rgb(${shade})`);
    x.fillStyle = g; x.beginPath(); x.arc(cx, cy, rr, 0, Math.PI * 2); x.fill();
  }
  // 3. 墨线：每瓣上半一道弧，内部一两个小卷
  x.strokeStyle = ink; x.lineWidth = S * 0.012; x.lineCap = 'round';
  for (const [cx, cy, rr] of lobes) { x.beginPath(); x.arc(cx, cy, rr * 0.98, Math.PI * (1.05 + r() * 0.1), Math.PI * (1.85 + r() * 0.1)); x.stroke(); }
  for (let k = 0; k < 2; k++) { const [cx, cy, rr] = lobes[Math.floor(r() * lobes.length)]; x.beginPath(); x.arc(cx + rr * 0.1, cy + rr * 0.15, rr * 0.38, Math.PI * 0.9, Math.PI * 1.9); x.stroke(); }
  // 4. alpha：形内按离边深度 0.52…1，加噪声，让溶边是碎的
  const img = x.getImageData(0, 0, S, S), d = img.data; const N = S * S;
  const inside = new Uint8Array(N); for (let i = 0; i < N; i++) inside[i] = d[i * 4 + 3] > 200 ? 1 : 0;
  // 粗略的离边距离：多次 3x3 腐蚀计数
  const depth = new Float32Array(N); let cur = inside.slice();
  for (let it = 0; it < 18; it++) { const nx = new Uint8Array(N); for (let yy = 1; yy < S - 1; yy++) for (let xx = 1; xx < S - 1; xx++) { const i = yy * S + xx; nx[i] = cur[i] & cur[i - 1] & cur[i + 1] & cur[i - S] & cur[i + S]; if (cur[i]) depth[i] += 1; } cur = nx; }
  // 值噪声（两层随机格子双线性插值）：溶掉时是一块块不规则的缺口，不是规则的斜纹
  const grid = (g) => { const v = new Float32Array((g + 1) * (g + 1)); for (let k = 0; k < v.length; k++) v[k] = r(); return (px, py) => { const fx = px / S * g, fy = py / S * g, ix = Math.min(g - 1, fx | 0), iy = Math.min(g - 1, fy | 0), u = fx - ix, w = fy - iy, a0 = v[iy * (g + 1) + ix], a1 = v[iy * (g + 1) + ix + 1], b0 = v[(iy + 1) * (g + 1) + ix], b1 = v[(iy + 1) * (g + 1) + ix + 1]; const su = u * u * (3 - 2 * u), sw = w * w * (3 - 2 * w); return (a0 * (1 - su) + a1 * su) * (1 - sw) + (b0 * (1 - su) + b1 * su) * sw; }; };
  const n1 = grid(6), n2 = grid(17);
  for (let i = 0; i < N; i++) {
    if (!inside[i]) { d[i * 4 + 3] = 0; continue; }
    const xx = i % S, yy = (i / S) | 0; const nz = 0.65 * n1(xx, yy) + 0.35 * n2(xx, yy);
    d[i * 4 + 3] = Math.round(255 * (0.53 + 0.46 * Math.min(1, (depth[i] / 18) * 0.75 + nz * 0.35)));
  }
  x.putImageData(img, 0, 0);
  return c;
}

/**
 * 纸烟团。puffs: [{ t0, life, p:[x,y,z], v:[vx,vy,vz], s0, s1, kind? }]。
 * 每团两片纸（前白后灰，错开一点）面向镜头；尺寸按定格 fps 一跳一跳地长；寿命末段被溶掉。
 */
export function makePaperSmoke(texs, puffs, { fps = 12 } = {}) {
  const THREE = T();
  const grp = new THREE.Group();
  const geo = new THREE.PlaneGeometry(1, 1);
  const items = puffs.map((p, i) => {
    const tex = texs[(p.kind ?? i) % texs.length];
    const mk = (k) => {
      const m = new THREE.MeshStandardMaterial({ map: tex, alphaTest: 0.5, roughness: 1, metalness: 0, side: THREE.DoubleSide, emissive: new THREE.Color(1, 1, 1), emissiveMap: tex, emissiveIntensity: 0.42 });
      const mesh = new THREE.Mesh(geo, m); mesh.renderOrder = 6; mesh.castShadow = false; mesh.receiveShadow = false; grp.add(mesh); return mesh;
    };
    return { back: mk(1), front: mk(0) };
  });
  const tmp = new THREE.Vector3(), right = new THREE.Vector3(), up = new THREE.Vector3(), fwd = new THREE.Vector3();
  return {
    group: grp, puffs,
    set(t, cam, col = [1, 1, 1], k = 1) {
      const tt = Math.floor(t * fps + 1e-6) / fps;
      if (cam) { cam.updateMatrixWorld(); right.setFromMatrixColumn(cam.matrixWorld, 0); up.setFromMatrixColumn(cam.matrixWorld, 1); fwd.setFromMatrixColumn(cam.matrixWorld, 2); }
      puffs.forEach((p, i) => {
        const it = items[i]; const age = tt - p.t0;
        if (age < 0 || age > p.life || k <= 0) { it.front.visible = it.back.visible = false; return; }
        const u = age / p.life; const e = ease.out(u);
        const sc = (p.s0 + (p.s1 - p.s0) * ease.out(Math.min(1, u * 1.5))) * (0.85 + 0.15 * k);
        const dis = 0.5 + 0.5 * smooth(0.55, 1, u) + 0.5 * (1 - k); // alphaTest：0.5 完整，→1 溶尽
        const px = p.p[0] + p.v[0] * e * p.life, py = p.p[1] + p.v[1] * e * p.life, pz = p.p[2] + p.v[2] * e * p.life;
        for (const [m, off, s2, sh] of [[it.back, -1, 0.82, 0.86], [it.front, 1, 1, 1]]) {
          m.visible = dis < 0.995;
          if (!m.visible) continue;
          tmp.set(px, py, pz);
          if (cam) { tmp.addScaledVector(right, off < 0 ? sc * 0.16 : 0).addScaledVector(up, off < 0 ? sc * 0.1 : 0).addScaledVector(fwd, off < 0 ? -sc * 0.06 : 0); m.quaternion.copy(cam.quaternion); }
          m.position.copy(tmp); m.scale.set(sc * s2, sc * s2, 1);
          m.material.alphaTest = Math.min(0.995, dis + (off < 0 ? 0.04 : 0));
          m.material.color.setRGB(col[0] * sh, col[1] * sh, col[2] * sh); m.material.emissive.setRGB(col[0] * sh, col[1] * sh, col[2] * sh);
        }
      });
    },
  };
}

/** 闪光（炮口火、刺刀反光）。items: [{ t0, dur, p:[x,y,z] 或 fn(t), size, kind:'flash'|'star', a }] */
export function makeSparks(items) {
  const THREE = T();
  const tex = { flash: glowTex('flash'), star: glowTex('star') };
  const grp = new THREE.Group();
  const sp = items.map(it => { const m = new THREE.SpriteMaterial({ map: tex[it.kind || 'flash'], transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: new THREE.Color(...(it.color || [4, 3, 2])) }); const s = new THREE.Sprite(m); s.renderOrder = 7; grp.add(s); return s; });
  return {
    group: grp,
    set(t, k = 1) {
      items.forEach((it, i) => {
        const s = sp[i]; const age = t - it.t0;
        if (age < 0 || age > it.dur || k <= 0) { s.visible = false; return; }
        const u = age / it.dur; s.visible = true;
        const p = typeof it.p === 'function' ? it.p(t) : it.p; if (!p) { s.visible = false; return; }
        s.position.set(p[0], p[1], p[2]);
        const env = it.kind === 'star' ? Math.sin(Math.PI * u) : (1 - u) * (1 - u);
        const sz = it.size * (it.kind === 'star' ? 0.6 + 0.4 * env : 1 + 0.6 * u); s.scale.set(sz, sz, 1);
        s.material.opacity = env * (it.a ?? 1) * k;
        s.material.rotation = it.kind === 'star' ? u * 0.8 : 0;
      });
    },
  };
}

// 光柱：几片加色混合的长条，朝着光源方向
export function makeRays(n = 5, seed = 3) {
  const THREE = T();
  const c = canvas(64, 512), x = c.getContext('2d');
  const g = x.createLinearGradient(0, 0, 0, 512); g.addColorStop(0, 'rgba(255,240,210,0)'); g.addColorStop(0.25, 'rgba(255,240,210,.55)'); g.addColorStop(1, 'rgba(255,240,210,0)');
  x.fillStyle = g; x.fillRect(0, 0, 64, 512);
  const h = x.createLinearGradient(0, 0, 64, 0); h.addColorStop(0, 'rgba(0,0,0,1)'); h.addColorStop(0.5, 'rgba(0,0,0,0)'); h.addColorStop(1, 'rgba(0,0,0,1)');
  x.globalCompositeOperation = 'destination-out'; x.fillStyle = h; x.fillRect(0, 0, 64, 512);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const grp = new THREE.Group(); const ms = [];
  for (let i = 0; i < n; i++) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(0.35 + (i % 3) * 0.18, 5), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, color: new THREE.Color(1, 0.9, 0.75), opacity: 0 }));
    m.position.set((i - n / 2) * 0.55 + ((i * 37) % 7) * 0.04, 0, (i % 2) * 0.3); m.renderOrder = 8; grp.add(m); ms.push(m);
  }
  return { group: grp, set(t, k) { grp.visible = k > 0.003; ms.forEach((m, i) => { m.material.opacity = k * (0.55 + 0.45 * Math.sin(t * 0.9 + i * 1.7)) * (0.5 + (i % 3) * 0.25); }); } };
}
