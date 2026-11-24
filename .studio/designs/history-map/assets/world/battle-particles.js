// 画面上的弹雨、炮弹和溅起的纸屑。轨迹只供定格小景使用。
import { lerp, clamp, smooth } from './util.js';

export function battleParticles(world, items) {
  const { THREE } = world;
  const quad = new THREE.PlaneGeometry(1, 1);
  const geo = new THREE.InstancedBufferGeometry();
  geo.index = quad.index;
  geo.setAttribute('position', quad.attributes.position);
  geo.setAttribute('uv', quad.attributes.uv);
  const attrs = ['head', 'tail', 'style'].map((name, i) => {
    const attr = new THREE.InstancedBufferAttribute(new Float32Array(items.length * (i === 2 ? 4 : 3)), i === 2 ? 4 : 3);
    attr.setUsage(THREE.DynamicDrawUsage);
    geo.setAttribute(name, attr);
    return attr;
  });
  const material = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { warm: { value: new THREE.Color() }, dust: { value: new THREE.Color() } },
    vertexShader: `attribute vec3 head, tail;
      attribute vec4 style;
      varying vec2 vUv;
      varying vec2 ink;
      void main() {
        vec4 a = modelViewMatrix * vec4(tail, 1.0);
        vec4 b = modelViewMatrix * vec4(head, 1.0);
        vec2 d = b.xy - a.xy;
        vec2 along = length(d) > 0.0001 ? normalize(d) : vec2(1.0, 0.0);
        vec4 p = mix(a, b, uv.x);
        p.xy += vec2(-along.y, along.x) * position.y * style.x;
        if (style.z > 0.5) p.xy += along * position.x * style.x;
        gl_Position = projectionMatrix * p;
        vUv = uv;
        ink = style.yz;
      }`,
    fragmentShader: `uniform vec3 warm, dust;
      varying vec2 vUv;
      varying vec2 ink;
      void main() {
        float a;
        vec3 c;
        if (ink.y < 0.5) {
          a = smoothstep(0., 0.9, vUv.x) * (1. - smoothstep(.85, 1., vUv.x)) * (1. - smoothstep(.1, .5, abs(vUv.y - .5)));
          c = warm;
        } else {
          vec2 xy = (vUv - .5) * 2.;
          a = 1. - smoothstep(.60, 1., ink.y < 1.5 ? abs(xy.x) + .7 * abs(xy.y) : length(xy));
          c = ink.y < 1.5 ? dust : (ink.y < 2.5 ? vec3(.047, .034, .026) : dust * .83);
        }
        gl_FragColor = vec4(c, a * ink.x);
      }`,
  });
  const mesh = new THREE.InstancedMesh(geo, material, items.length);
  mesh.frustumCulled = false; mesh.renderOrder = 7;
  world.scene.add(mesh);
  const [head, tail, style] = attrs;
  return (t, lp) => {
    let n = 0;
    for (const p of items) {
      const age = t - p.at;
      if (age < 0 || age >= p.life) continue;
      const u = age / p.life, v = Math.max(0, u - p.tail);
      const { a, b, arc, kind, size } = p;
      const x = lerp(a[0], b[0], u), y = lerp(a[1], b[1], u) + 4 * arc * u * (1 - u), z = lerp(a[2], b[2], u);
      head.setXYZ(n, x, y, z);
      if (kind === 0) tail.setXYZ(n, lerp(a[0], b[0], v), lerp(a[1], b[1], v), lerp(a[2], b[2], v));
      else tail.setXYZ(n, x, y, z);
      const opacity = (1 - smooth(kind === 0 ? 0.58 : 0.29, 1, u)) * p.alpha;
      style.setXYZW(n++, size * (kind === 3 ? lerp(0.55, 1.45, u) : 1), clamp(opacity), kind, 0);
    }
    mesh.visible = n > 0; mesh.count = n;
    if (!n) return;
    for (const attr of attrs) attr.needsUpdate = true;
    material.uniforms.warm.value.setRGB(2.1 - 0.12 * lp.sunI, 1.28 + 0.37 * lp.sunC[1], 0.65 + 0.55 * lp.sunC[2]);
    material.uniforms.dust.value.setRGB(0.48 + 0.10 * lp.hemi, 0.37 + 0.09 * lp.hemi, 0.30 + 0.09 * lp.hemi);
  };
}
