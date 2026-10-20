// CHROME_PATH=/usr/bin/chromium node tests/stage-backdrop-browser.mjs
import assert from 'node:assert/strict';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const card = path.join(repo, '.studio/designs/stage-full/assets');
const {chromium} = createRequire(path.join(repo, '.studio/parser/package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox']});
try {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
  await page.setContent('<style>body{margin:0}main{position:relative;width:1920px;height:1080px;overflow:hidden}section{position:absolute;inset:0}</style>' +
    '<main><section data-hf-layer="background" id="bg"></section></main>');
  for (const file of ['stage-rig/stage-rig.js', 'stage-kit/stage-kit.js', 'stage-kit/blocks/disc-scene.js'])
    await page.addScriptTag({path: path.join(card, file)});

  const backdrop = await page.evaluate(() => {
    const R = window.HarnessStageRig, bg = document.getElementById('bg');
    const skins = {warm: {wall: ['#f7ecd8', '#e6cfa8'], floor: ['#dcbd8e', '#c49a63']}, cool: {wall: ['#e4eff7', '#b4cde0'], floor: ['#b9d3e6', '#8fb2cd']}};
    const bd = R.createBackdrop({mount: bg, horizon: 700, skins});
    bd.unfold({at: 0.2}).refold({at: 5, skin: 'cool'}).fold({at: 10});
    const nodes = [...bd.root.querySelectorAll('.hf-rig-wall, .hf-rig-floor')];
    const snap = t => { bd.apply(t); return [bd.root.dataset.hfSkin, ...nodes.map(n => n.style.transform)]; };
    const times = [0, 0.5, 1.2, 3, 5.6, 6.5, 7.6, 9, 10.5, 12];
    const forward = times.map(snap), backward = times.slice().reverse().map(snap).reverse();
    const hits = t => { bd.apply(t); return [[10, 10], [1910, 10], [10, 1070], [1910, 1070], [960, 690], [960, 710], [300, 300]]
      .map(([x, y]) => (document.elementFromPoint(x, y)?.className || '').match(/hf-rig-(wall|floor)/)?.[1] || 'none'); };
    const open = hits(3), shut = hits(0), closed = hits(12);
    const skin = [6.4, 6.6].map(t => { bd.apply(t); return bd.root.dataset.hfSkin; });
    const errors = {};
    const attempt = (name, fn) => { try { fn(); errors[name] = 'none'; } catch (error) { errors[name] = error.constructor.name; } };
    const fresh = () => R.createBackdrop({mount: bg, skins});
    attempt('refoldWhileShut', () => fresh().unfold({at: 1}).fold({at: 4}).refold({at: 6, skin: 'cool'}));
    attempt('foldTwice', () => fresh().fold({at: 1}).fold({at: 4}));
    attempt('overlap', () => fresh().unfold({at: 1}).refold({at: 2, skin: 'cool'}));
    attempt('unknownSkin', () => fresh().unfold({at: 1}).refold({at: 5, skin: 'night'}));
    attempt('unknownOption', () => fresh().unfold({at: 1, ease: 'out'}));
    attempt('badHorizon', () => R.createBackdrop({mount: bg, horizon: 1200}));
    [...bg.querySelectorAll('.hf-rig-backdrop')].slice(1).forEach(n => n.remove());
    bd.dispose();
    return {forward, backward, open, shut, closed, skin, errors, marked: nodes.every(n => n.closest('[data-hf-set]'))};
  });
  assert.deepEqual(backdrop.forward, backdrop.backward, 'backdrop apply(t) is a pure function of t');
  assert.deepEqual(backdrop.open, ['wall', 'wall', 'floor', 'floor', 'wall', 'floor', 'wall'], 'open set covers the whole frame: ' + backdrop.open);
  assert.equal(backdrop.shut[6], 'none', 'before unfolding the frame is not covered');
  assert.equal(backdrop.closed[6], 'none', 'after fold the set is put away');
  assert.deepEqual(backdrop.skin, ['warm', 'cool'], 'skin switches while the set is shut');
  assert(backdrop.marked, 'backdrop pieces are scenery (data-hf-set)');
  assert.deepEqual(Object.values(backdrop.errors), Array(6).fill('TypeError'), JSON.stringify(backdrop.errors));

  // stage-light 用两块背板的同一套背景动作，展开后同样铺满全屏。
  const light = await page.evaluate(() => {
    const bg = document.getElementById('bg');
    const bd = window.HarnessStageRig.createBackdrop({mount: bg, panels: 2, skins: {warm: {wall: ['#eee', '#ddd'], floor: ['#ccc', '#bbb']}}});
    bd.unfold({at: 0.2}).fold({at: 6});
    bd.apply(3);
    const open = [[10, 10], [1910, 10], [10, 1070], [1910, 1070], [960, 690], [960, 710]]
      .map(([x, y]) => (document.elementFromPoint(x, y)?.className || '').match(/hf-rig-(wall|floor)/)?.[1] || 'none');
    const walls = bd.root.querySelectorAll('.hf-rig-wall').length;
    bd.dispose();
    return {open, walls};
  });
  assert.equal(light.walls, 2, 'stage-light backdrop has two wall panels');
  assert.deepEqual(light.open, ['wall', 'wall', 'floor', 'floor', 'wall', 'floor'], 'two-panel set covers the whole frame: ' + light.open);

  const disc = await page.evaluate(() => {
    const kit = window.HarnessStageKit, bg = document.getElementById('bg');
    bg.innerHTML = '';
    const dot = encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>');
    const options = () => ({
      mount: bg, base: 'data:image/svg+xml;charset=utf-8,',
      scenes: [
        {id: 'a', color: '#111', board: {wall: ['#eee', '#ddd'], floor: ['#ccc', '#bbb']},
          pieces: [{id: 'sun', kind: 'sky', x: 100, y: 80, w: 100, h: 100, file: dot}, {id: 'box', kind: 'prop', x: 900, y: 600, w: 120, h: 120, file: dot}]},
        {id: 'b', color: '#111', board: {wall: ['#234', '#123'], floor: ['#345', '#234']},
          pieces: [{id: 'moon', kind: 'sky', x: 1500, y: 80, w: 100, h: 100, file: dot}]}
      ],
      entries: [{scene: 'a', turnAt: null, buildAt: 0.2, buildDur: 4}, {scene: 'b', turnAt: 6, buildAt: 8.2, buildDur: 4}]
    });
    const block = kit.create('disc.scene', options());
    const planes = [...block.root.querySelectorAll('.hf-kit-disc-scene-scene-plane')];
    const watched = [...block.root.querySelectorAll('.hf-rig-wall, .hf-rig-floor, .hf-kit-disc-scene-piece, .hf-kit-disc-scene-disc')];
    const snap = t => { block.apply(t); return watched.map(n => n.style.transform + '|' + n.style.visibility); };
    const times = [0, 0.6, 1.9, 3, 5, 7, 8.5, 10, 13];
    const forward = times.map(snap), backward = times.slice().reverse().map(snap).reverse();
    const sun = block.piece(0, 'sun').parentNode;
    const at = t => { block.apply(t); return sun.style.visibility; };
    const pieceTimes = [at(1.75), at(1.85)];
    block.apply(3);
    // 圆盘根节点不吃命中测试；只为本次几何检查临时打开。
    const probe = document.head.appendChild(Object.assign(document.createElement('style'), {textContent: '#bg *{pointer-events:auto!important}'}));
    const covered = [[10, 10], [1910, 1070], [960, 900]].map(([x, y]) => (document.elementFromPoint(x, y)?.className || '').match(/hf-rig-(wall|floor)|piece/)?.[0] || 'none');
    probe.remove();
    let tooShort = 'none';
    try { const o = options(); o.entries[0].buildDur = 2; kit.create('disc.scene', o); } catch (error) { tooShort = error.constructor.name; }
    block.dispose();
    return {boards: planes.map(p => !!p.querySelector('.hf-rig-full')), forward, backward, pieceTimes, covered, tooShort};
  });
  assert.deepEqual(disc.boards, [true, true], 'each disc scene carries its own full-screen board');
  assert.deepEqual(disc.forward, disc.backward, 'disc with boards is a pure function of t');
  assert.deepEqual(disc.pieceTimes, ['hidden', 'visible'], 'small pieces stack only after the board has unfolded (0.2 + 1.6 s)');
  assert.deepEqual(disc.covered, ['hf-rig-wall', 'hf-rig-floor', 'hf-rig-floor'], 'the unfolded board fills the frame: ' + disc.covered);
  assert.equal(disc.tooShort, 'TypeError', 'buildDur must leave time for pieces after the board');
  console.log('stage backdrop browser checks passed');
} finally {
  await browser.close();
}
