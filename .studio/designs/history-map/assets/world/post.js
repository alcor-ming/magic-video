// 后期：场景（MSAA + 深度）→ 景深 → 泛光 → 调色、暗角、颗粒 → 画布。颗粒的种子来自 t。
const VS = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }`;

const DOF_FS = (N) => `
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform sampler2D tDepth;
uniform float near; uniform float far; uniform float focus; uniform float aperture; uniform float maxBlur; uniform vec2 res;
float linZ(float d){ float z = d * 2. - 1.; return 2. * near * far / (far + near - z * (far - near)); }
float coc(float z){ return clamp(aperture * abs(z - focus) / z, 0., 1.) * maxBlur; }
void main(){
  float zc = linZ(texture2D(tDepth, vUv).x); float cc = coc(zc);
  vec3 col = texture2D(tColor, vUv).rgb; vec3 acc = col; float tot = 1.;
  for (int i = 0; i < ${N}; i++) {
    float fi = float(i) + 0.5;
    float r = sqrt(fi / float(${N})) * maxBlur;
    float a = fi * 2.39996323;
    vec2 o = vec2(cos(a), sin(a)) * r / res;
    vec2 uv2 = vUv + o;
    float zs = linZ(texture2D(tDepth, uv2).x); float cs = coc(zs);
    if (zs > zc) cs = min(cs, cc * 2.);
    float m = smoothstep(r - 0.75, r + 0.75, cs);
    acc += mix(acc / tot, texture2D(tColor, uv2).rgb, m); tot += 1.;
  }
  gl_FragColor = vec4(acc / tot, 1.);
}`;

const BRIGHT_FS = `
precision highp float; varying vec2 vUv; uniform sampler2D tColor; uniform float thr;
void main(){ vec3 c = texture2D(tColor, vUv).rgb; float l = max(c.r, max(c.g, c.b)); float k = smoothstep(thr, thr * 2.2, l); gl_FragColor = vec4(c * k, 1.); }`;
const BLUR_FS = `
precision highp float; varying vec2 vUv; uniform sampler2D tColor; uniform vec2 dir;
void main(){ vec3 s = texture2D(tColor, vUv).rgb * 0.2270270270;
  s += (texture2D(tColor, vUv + dir * 1.3846153846).rgb + texture2D(tColor, vUv - dir * 1.3846153846).rgb) * 0.3162162162;
  s += (texture2D(tColor, vUv + dir * 3.2307692308).rgb + texture2D(tColor, vUv - dir * 3.2307692308).rgb) * 0.0702702703;
  gl_FragColor = vec4(s, 1.); }`;

const FINAL_FS = `
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform sampler2D tBloom; uniform sampler2D tBloom2;
uniform float exposure; uniform float bloom; uniform float sat; uniform float contrast;
uniform vec3 lift; uniform vec3 gain; uniform float vig; uniform float grain; uniform float seed; uniform vec2 res; uniform float fade; uniform vec3 fadeColor;
vec3 aces(vec3 x){ const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14; return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0., 1.); }
float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233)) + seed * 17.13) * 43758.5453); }
vec3 srgb(vec3 c){ return mix(c * 12.92, 1.055 * pow(c, vec3(1. / 2.4)) - 0.055, step(0.0031308, c)); }
void main(){
  vec3 c = texture2D(tColor, vUv).rgb + (texture2D(tBloom, vUv).rgb * 0.6 + texture2D(tBloom2, vUv).rgb * 0.8) * bloom;
  c *= exposure;
  c = aces(c);
  c = srgb(c);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, sat);
  c = (c - 0.5) * contrast + 0.5;
  c = lift + c * (gain - lift);
  vec2 q = (vUv - 0.5) * vec2(res.x / res.y, 1.);
  float v = smoothstep(1.15, 0.25, length(q) * 1.05);
  c *= mix(1. - vig, 1., v);
  c = mix(c, fadeColor, fade);
  float n = h(floor(vUv * res)) + h(floor(vUv * res) + 7.31) - 1.;
  c += n * grain;
  gl_FragColor = vec4(clamp(c, 0., 1.), 1.);
}`;

export function createPost(renderer, { quality = 'medium', width = 1920, height = 1080 } = {}) {
  const THREE = window.THREE;
  const hi = quality === 'high';
  const W = width, H = height;
  const depthTexture = new THREE.DepthTexture(W, H, THREE.UnsignedIntType);
  const rtScene = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4, depthTexture, depthBuffer: true });
  const rtDof = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, depthBuffer: false });
  const bw = W >> 2, bh = H >> 2;
  const rtB1 = new THREE.WebGLRenderTarget(bw, bh, { type: THREE.HalfFloatType, depthBuffer: false });
  const rtB2 = new THREE.WebGLRenderTarget(bw, bh, { type: THREE.HalfFloatType, depthBuffer: false });
  const rtC1 = new THREE.WebGLRenderTarget(bw >> 1, bh >> 1, { type: THREE.HalfFloatType, depthBuffer: false });
  const rtC2 = new THREE.WebGLRenderTarget(bw >> 1, bh >> 1, { type: THREE.HalfFloatType, depthBuffer: false });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
  const qScene = new THREE.Scene(); qScene.add(quad);
  const qCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const mk = (fs, uniforms) => new THREE.ShaderMaterial({ vertexShader: VS, fragmentShader: fs, uniforms, depthTest: false, depthWrite: false });
  const dof = mk(DOF_FS(hi ? 72 : 44), { tColor: { value: rtScene.texture }, tDepth: { value: depthTexture }, near: { value: 0.1 }, far: { value: 100 }, focus: { value: 5 }, aperture: { value: 0.5 }, maxBlur: { value: hi ? 18 : 14 }, res: { value: new THREE.Vector2(W, H) } });
  const bright = mk(BRIGHT_FS, { tColor: { value: rtDof.texture }, thr: { value: 1.2 } });
  const blur = mk(BLUR_FS, { tColor: { value: null }, dir: { value: new THREE.Vector2() } });
  const fin = mk(FINAL_FS, {
    tColor: { value: rtDof.texture }, tBloom: { value: rtB2.texture }, tBloom2: { value: rtC2.texture }, exposure: { value: 1 }, bloom: { value: 0.4 }, sat: { value: 1 }, contrast: { value: 1 },
    lift: { value: new THREE.Vector3(0, 0, 0) }, gain: { value: new THREE.Vector3(1, 1, 1) }, vig: { value: 0.45 }, grain: { value: 0.03 }, seed: { value: 0 }, res: { value: new THREE.Vector2(W, H) },
    fade: { value: 0 }, fadeColor: { value: new THREE.Vector3(0, 0, 0) },
  });
  const pass = (mat, target) => { quad.material = mat; renderer.setRenderTarget(target); renderer.render(qScene, qCam); };
  return {
    render(scene, camera, p) {
      renderer.setRenderTarget(rtScene); renderer.render(scene, camera);
      const u = dof.uniforms; u.near.value = camera.near; u.far.value = camera.far; u.focus.value = p.focus; u.aperture.value = p.aperture;
      pass(dof, rtDof);
      bright.uniforms.thr.value = p.bloomThr ?? 1.1;
      pass(bright, rtB1);
      blur.uniforms.tColor.value = rtB1.texture; blur.uniforms.dir.value.set(1.6 / bw, 0); pass(blur, rtB2);
      blur.uniforms.tColor.value = rtB2.texture; blur.uniforms.dir.value.set(0, 1.6 / bh); pass(blur, rtB1);
      blur.uniforms.tColor.value = rtB1.texture; blur.uniforms.dir.value.set(1.6 / bw, 0); pass(blur, rtB2);
      blur.uniforms.tColor.value = rtB2.texture; blur.uniforms.dir.value.set(0, 1.6 / bh); pass(blur, rtB1);
      // 第二级更宽的光晕
      blur.uniforms.tColor.value = rtB1.texture; blur.uniforms.dir.value.set(2.5 / (bw >> 1), 0); pass(blur, rtC1);
      blur.uniforms.tColor.value = rtC1.texture; blur.uniforms.dir.value.set(0, 2.5 / (bh >> 1)); pass(blur, rtC2);
      blur.uniforms.tColor.value = rtC2.texture; blur.uniforms.dir.value.set(2.5 / (bw >> 1), 0); pass(blur, rtC1);
      blur.uniforms.tColor.value = rtC1.texture; blur.uniforms.dir.value.set(0, 2.5 / (bh >> 1)); pass(blur, rtC2);
      fin.uniforms.tBloom.value = rtB1.texture;
      const f = fin.uniforms;
      f.exposure.value = p.exposure; f.bloom.value = p.bloom; f.sat.value = p.sat; f.contrast.value = p.contrast;
      f.lift.value.set(...p.lift); f.gain.value.set(...p.gain); f.vig.value = p.vig; f.grain.value = p.grain; f.seed.value = p.seed;
      f.fade.value = p.fade || 0; f.fadeColor.value.set(...(p.fadeColor || [0, 0, 0]));
      pass(fin, null);
    },
    dispose() {
      for (const target of [rtScene, rtDof, rtB1, rtB2, rtC1, rtC2]) target.dispose();
      for (const material of [dof, bright, blur, fin]) material.dispose();
      quad.geometry.dispose();
    },
  };
}
