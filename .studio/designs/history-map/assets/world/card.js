// 纸片：有厚度的模切立牌（正面图、背面素纸、侧边纸芯），接触阴影，铰链立起。
// 另含图钉小旗、纸条箭头。依赖全局 THREE。
import { canvas, clamp } from './util.js';

const T = () => window.THREE;
function blobTex(resources) {
  if (resources.blob) return resources.blob;
  const c = canvas(128, 128), x = c.getContext('2d');
  const g = x.createRadialGradient(64, 64, 2, 64, 64, 63);
  g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(0.35, 'rgba(0,0,0,.72)'); g.addColorStop(0.7, 'rgba(0,0,0,.22)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  resources.blob = new (T().CanvasTexture)(c);
  return resources.blob;
}

function triangulate(poly) {
  const THREE = T();
  const pts = poly.map(p => new THREE.Vector2(p[0], p[1]));
  return THREE.ShapeUtils.triangulateShape(pts, []);
}

// 由模切轮廓建实体几何：paperFace 标记正面、背面和纸芯，供同一次绘制着色。
export function cardGeometry(dc, height, thick) {
  const THREE = T();
  const width = height * dc.aspect;
  const P = [], N = [], U = [], I = [], face = [];
  const groups = [[], [], []];
  const X = u => (u - 0.5) * width, Y = v => (v - dc.floorV) * height;
  for (const poly0 of dc.polys) {
    let area = 0; for (let i = 0; i < poly0.length; i++) { const a = poly0[i], b = poly0[(i + 1) % poly0.length]; area += a[0] * b[1] - b[0] * a[1]; }
    const poly = area < 0 ? poly0.slice().reverse() : poly0; // 统一成逆时针
    const tris = triangulate(poly);
    for (const side of [0, 1]) {
      const z = side === 0 ? thick / 2 : -thick / 2, nz = side === 0 ? 1 : -1;
      const base = P.length / 3;
      for (const p of poly) { P.push(X(p[0]), Y(p[1]), z); N.push(0, 0, nz); U.push(side === 0 ? p[0] : 1 - p[0], p[1]); face.push(side); }
      for (const tr of tris) {
        let [a, b, c] = tr; const pa = poly[a], pb = poly[b], pc = poly[c];
        const cr = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]);
        if ((cr < 0) === (side === 0)) [b, c] = [c, b];
        groups[side].push(base + a, base + b, base + c);
      }
    }
    // 侧边：顶点法线取相邻两边的平均
    const n = poly.length, en = [];
    for (let i = 0; i < n; i++) { const a = poly[i], b = poly[(i + 1) % n]; const dx = X(b[0]) - X(a[0]), dy = Y(b[1]) - Y(a[1]); const l = Math.hypot(dx, dy) || 1; en.push([dy / l, -dx / l]); }
    let per = 0;
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n, a = poly[i], b = poly[j];
      const na = [(en[i][0] + en[(i - 1 + n) % n][0]), (en[i][1] + en[(i - 1 + n) % n][1])], nb = [(en[i][0] + en[j][0]), (en[i][1] + en[j][1])];
      const la = Math.hypot(...na) || 1, lb = Math.hypot(...nb) || 1;
      const base = P.length / 3; const seg = Math.hypot(X(b[0]) - X(a[0]), Y(b[1]) - Y(a[1]));
      P.push(X(a[0]), Y(a[1]), thick / 2, X(b[0]), Y(b[1]), thick / 2, X(b[0]), Y(b[1]), -thick / 2, X(a[0]), Y(a[1]), -thick / 2);
      N.push(na[0] / la, na[1] / la, 0, nb[0] / lb, nb[1] / lb, 0, nb[0] / lb, nb[1] / lb, 0, na[0] / la, na[1] / la, 0);
      U.push(per, 1, per + seg, 1, per + seg, 0, per, 0); per += seg;
      groups[2].push(base, base + 3, base + 1, base + 1, base + 3, base + 2);
      face.push(2, 2, 2, 2);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(N, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(U, 2));
  g.setAttribute('paperFace', new THREE.Float32BufferAttribute(face, 1));
  for (const indices of groups) I.push(...indices);
  g.setIndex(I);
  return { geometry: g, width, height };
}

// 三面共用一次提交，仍分别保留正面裁切、背纸凹凸和纸芯颜色。
function paperFaceShader(shader) {
  shader.vertexShader = 'attribute float paperFace; varying float vPaperFace;\n' +
    shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvPaperFace = paperFace;');
  shader.fragmentShader = 'varying float vPaperFace;\n' + shader.fragmentShader;
}
function paperSurface(shader) {
  const THREE = T();
  paperFaceShader(shader);
  shader.uniforms.paperBack = { value: new THREE.Color(0xc9bfac) };
  shader.uniforms.paperEdge = { value: new THREE.Color(0xe6dfcf) };
  shader.fragmentShader = 'uniform vec3 paperBack, paperEdge;\n' + shader.fragmentShader
    .replace('#include <map_fragment>', `
      #include <map_fragment>
      if (vPaperFace > 0.5) diffuseColor = vec4(vPaperFace < 1.5 ? paperBack : paperEdge, 1.0);
    `)
    .replace('#include <roughnessmap_fragment>', `
      #include <roughnessmap_fragment>
      if (vPaperFace > 0.5) roughnessFactor = vPaperFace < 1.5 ? 0.96 : 0.95;
    `)
    .replace('#include <normal_fragment_maps>', `
      #ifdef USE_BUMPMAP
        vec2 paperSlope = dHdxy_fwd() * (vPaperFace > 0.5 ? 0.6 / 0.35 : 1.0);
        vec3 paperNormal = perturbNormalArb(-vViewPosition, normal, paperSlope, faceDirection);
        if (vPaperFace < 1.5) normal = paperNormal;
      #else
        #include <normal_fragment_maps>
      #endif
    `);
}
function paperShadow(shader) {
  paperFaceShader(shader);
  shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
    #include <map_fragment>
    if (vPaperFace > 0.5) diffuseColor.a = 1.0;
  `);
}

/**
 * 立牌。dc 来自 diecut()。opts: { height, thick, grainTex, solid(默认 true) }
 * 返回 { root, set({x,y,z,yaw,rise,lean,tilt,scale}) , width, height }
 */
export function makeCard(dc, opts, resources) {
  const THREE = T();
  const { height = 1, thick = 0.012, grainTex = null, solid = true, blob = 1, rough = 0.86, pivot = 'foot' } = opts;
  let tex = resources.cards.get(dc.canvas);
  if (!tex) {
    tex = new THREE.CanvasTexture(dc.canvas);
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
    tex.generateMipmaps = true; tex.minFilter = THREE.LinearMipmapLinearFilter;
    resources.cards.set(dc.canvas, tex);
  }
  const front = new THREE.MeshStandardMaterial({ map: tex, alphaTest: 0.5, roughness: rough, metalness: 0, alphaToCoverage: true });
  if (grainTex) { front.bumpMap = grainTex; front.bumpScale = 0.35; }
  const root = new THREE.Group(), hinge = new THREE.Group(); root.add(hinge);
  let mesh, width;
  if (solid) {
    const g = cardGeometry(dc, height, thick); width = g.width;
    front.onBeforeCompile = paperSurface;
    mesh = new THREE.Mesh(g.geometry, front);
    mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking });
    mesh.customDepthMaterial.onBeforeCompile = paperShadow;
    mesh.customDistanceMaterial = new THREE.MeshDistanceMaterial();
    mesh.customDistanceMaterial.onBeforeCompile = paperShadow;
  } else {
    width = height * dc.aspect;
    const geo = new THREE.PlaneGeometry(width, height); geo.translate(0, height * (0.5 - dc.floorV), 0);
    front.side = THREE.DoubleSide;
    mesh = new THREE.Mesh(geo, front);
    mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: tex, alphaTest: 0.5 });
  }
  mesh.castShadow = true; mesh.receiveShadow = true;
  if (pivot === 'center') mesh.position.y = -height * (1 - dc.floorV) / 2; // 平放的地图纸片：以中心为轴
  hinge.add(mesh);
  // 接触阴影：脚下一团柔和的暗
  const fu0 = dc.foot ? dc.foot[0] : 0.1, fu1 = dc.foot ? dc.foot[1] : 0.9;
  const bw = Math.max(0.05, (fu1 - fu0) * width) * 1.15 + height * 0.06;
  const bmat = new THREE.MeshBasicMaterial({ map: blobTex(resources), transparent: true, depthWrite: false, color: 0x000000, opacity: 0.5, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const bl = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), bmat);
  bl.rotation.x = -Math.PI / 2; bl.scale.set(bw, Math.max(0.06, height * 0.16), 1);
  bl.position.set(((fu0 + fu1) / 2 - 0.5) * width, 0.003, 0); bl.renderOrder = 1;
  root.add(bl);
  const card = {
    root, hinge, mesh, width, height, floorV: dc.floorV, front, tex, blob: bl, blobBase: 0.5 * blob,
    set({ x = 0, y = 0, z = 0, yaw = 0, rise = 1, lean = 0, tilt = 0, scale = 1, shadow = 1, flat = -1, pitch = 0, roll = 0 } = {}) {
      root.visible = rise > 0.001;
      if (!root.visible) return;
      root.position.set(x, y, z); root.rotation.set(pitch, yaw, roll, 'YXZ'); root.scale.setScalar(scale);
      // 立起：沿底边从平躺（正面朝上，顶端朝远处）转到竖直
      hinge.rotation.set(flat * (1 - rise) * Math.PI / 2 + tilt, 0, lean);
      bmat.opacity = card.blobBase * clamp(rise * 1.4 - 0.2) * shadow;
      bl.visible = !card.batched && bmat.opacity > 0;
    },
  };
  return card;
}

// 图钉：金属针 + 漆珠 + 纸小旗
export function makePin(color, flagColor, opts = {}, resources) {
  const THREE = T();
  const g = new THREE.Group();
  const h = opts.height || 0.46;
  const needle = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.003, h, 8), new THREE.MeshStandardMaterial({ color: 0xb8b2a8, metalness: 1, roughness: 0.3 }));
  needle.position.y = h / 2; needle.castShadow = true; g.add(needle);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.058, 20, 14), new THREE.MeshPhysicalMaterial({ color, roughness: 0.25, clearcoat: 1, clearcoatRoughness: 0.15 }));
  head.position.y = h; head.castShadow = true; g.add(head);
  if (flagColor) {
    const fc = canvas(128, 80), fx = fc.getContext('2d');
    fx.fillStyle = '#f3eee2'; fx.fillRect(0, 0, 128, 80);
    fx.fillStyle = flagColor; fx.fillRect(6, 6, 116, 68);
    fx.strokeStyle = 'rgba(255,255,255,.55)'; fx.lineWidth = 3; fx.strokeRect(14, 14, 100, 52);
    const ft = new THREE.CanvasTexture(fc); ft.colorSpace = THREE.SRGBColorSpace;
    const flag = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.138, 0.005), new THREE.MeshStandardMaterial({ map: ft, roughness: 0.9 }));
    flag.position.set(0.112, h - 0.13, 0); flag.castShadow = true; g.add(flag);
  }
  const bl = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.16), new THREE.MeshBasicMaterial({ map: blobTex(resources), transparent: true, depthWrite: false, color: 0, opacity: 0.45, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  bl.rotation.x = -Math.PI / 2; bl.position.y = 0.003; g.add(bl);
  g.userData.headY = h;
  return g;
}

// 细绳：穿过几个控制点的圆管（两头系在图钉上，中间垂到桌面）
export function makeThread(points, { radius = 0.012, color = 0x9a1f18 } = {}) {
  const THREE = T();
  const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)), false, 'catmullrom', 0.4);
  const geo = new THREE.TubeGeometry(curve, Math.max(24, points.length * 24), radius, 8, false);
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color, roughness: 0.78, metalness: 0 }));
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

// 纸条箭头：沿路径的扁纸带（白边），露出长度由 reveal(0..1) 控制，头部是单独的三角纸片
export function makeRibbon(path, opts = {}) {
  const THREE = T();
  const { width = 0.22, color = '#2f4f9e', head = true, groundY = () => 0, lift = 0.012, tear = null, seed = 1 } = opts;
  // 路径等距重采样
  const pts = []; for (let i = 0; i < path.length - 1; i++) { const [ax, az] = path[i], [bx, bz] = path[i + 1]; const L = Math.hypot(bx - ax, bz - az); const n = Math.max(1, Math.ceil(L / 0.04)); for (let k = 0; k < n; k++) pts.push([ax + (bx - ax) * k / n, az + (bz - az) * k / n]); }
  pts.push(path[path.length - 1]);
  // 平滑一下
  for (let it = 0; it < 6; it++) for (let i = 1; i < pts.length - 1; i++) pts[i] = [(pts[i - 1][0] + 2 * pts[i][0] + pts[i + 1][0]) / 4, (pts[i - 1][1] + 2 * pts[i][1] + pts[i + 1][1]) / 4];
  const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const total = cum[cum.length - 1];
  const tc = canvas(64, 256), tx = tc.getContext('2d');
  tx.fillStyle = '#f4efe3'; tx.fillRect(0, 0, 64, 256);
  tx.fillStyle = color; tx.fillRect(9, 0, 46, 256);
  tx.fillStyle = 'rgba(255,255,255,.12)'; tx.fillRect(14, 0, 4, 256);
  const tex = new THREE.CanvasTexture(tc); tex.colorSpace = THREE.SRGBColorSpace; tex.wrapT = THREE.RepeatWrapping;
  const P = [], U = [], I = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    let dx = b[0] - a[0], dz = b[1] - a[1]; const l = Math.hypot(dx, dz) || 1; dx /= l; dz /= l;
    const nx = -dz, nz = dx; const [x, z] = pts[i];
    const y0 = groundY(x + nx * width / 2, z + nz * width / 2) + lift, y1 = groundY(x - nx * width / 2, z - nz * width / 2) + lift;
    P.push(x + nx * width / 2, y0, z + nz * width / 2, x - nx * width / 2, y1, z - nz * width / 2);
    U.push(0, cum[i] / width * 0.25, 1, cum[i] / width * 0.25);
    if (i < pts.length - 1) { const k = i * 2; I.push(k, k + 2, k + 1, k + 1, k + 2, k + 3); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(U, 2));
  g.setIndex(I); g.computeVertexNormals();
  // 用 drawRange 控制露出长度
  const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 });
  const mesh = new THREE.Mesh(g, mat); mesh.receiveShadow = true; mesh.castShadow = true;
  const grp = new THREE.Group(); grp.add(mesh);
  let hd = null;
  if (head) {
    const hs = new THREE.Shape(); const w = width * 1.9, L = width * 1.6;
    hs.moveTo(0, L); hs.lineTo(-w / 2, 0); hs.lineTo(-width / 2, 0.0); hs.lineTo(width / 2, 0); hs.lineTo(w / 2, 0); hs.lineTo(0, L);
    const hc = canvas(64, 64), hx = hc.getContext('2d'); hx.fillStyle = color; hx.fillRect(0, 0, 64, 64);
    const htex = new THREE.CanvasTexture(hc); htex.colorSpace = THREE.SRGBColorSpace;
    const hg = new THREE.ExtrudeGeometry(hs, { depth: 0.008, bevelEnabled: false });
    hg.rotateX(Math.PI / 2);
    hd = new THREE.Mesh(hg, [new THREE.MeshStandardMaterial({ color, roughness: 0.9 }), new THREE.MeshStandardMaterial({ color: 0xf1ebdd, roughness: 0.9 })]);
    // 白边：略大的一片垫在下面
    const edge = new THREE.Mesh(new THREE.ShapeGeometry(hs), new THREE.MeshStandardMaterial({ color: 0xf4efe3, roughness: 0.9, side: THREE.DoubleSide }));
    edge.rotation.x = Math.PI / 2; edge.scale.set(1.18, 1.18, 1); edge.position.set(0, -0.001, -0.02);
    const hg2 = new THREE.Group(); hg2.add(hd); hg2.add(edge);
    hd.castShadow = true; grp.add(hg2); hd = hg2;
  }
  const at = s => { // 路径上弧长 s 处的点和朝向
    s = clamp(s, 0, total); let i = 0; while (i < cum.length - 2 && cum[i + 1] < s) i++;
    const u = (s - cum[i]) / ((cum[i + 1] - cum[i]) || 1); const a = pts[i], b = pts[i + 1];
    return { x: a[0] + (b[0] - a[0]) * u, z: a[1] + (b[1] - a[1]) * u, ang: Math.atan2(b[0] - a[0], b[1] - a[1]) };
  };
  return {
    root: grp, total, at,
    set(reveal = 1, from = 0) {
      grp.visible = reveal > from + 0.001;
      if (!grp.visible) return;
      const i0 = Math.floor(from * (pts.length - 1)), i1 = Math.max(i0 + 1, Math.floor(reveal * (pts.length - 1)));
      g.setDrawRange(i0 * 6, (i1 - i0) * 6);
      if (hd) {
        const p = at(reveal * total);
        hd.position.set(p.x, groundY(p.x, p.z) + lift + 0.004, p.z); hd.rotation.set(0, p.ang, 0);
        hd.visible = true;
      }
    },
  };
}
