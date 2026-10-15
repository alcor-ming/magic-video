// CHROME_PATH=/usr/bin/chromium node tests/stage-kit-browser.mjs
import assert from 'node:assert/strict';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {inspectFrame} from '../.studio/visual_probe.mjs';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const card = path.join(repo, '.studio/designs/stage-full/assets');
const {chromium} = createRequire(path.join(repo, '.studio/parser/package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox']});
try {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
  await page.setContent('<style>body{margin:0}main{position:relative;width:1920px;height:1080px}section{position:absolute;inset:0}</style>' +
    '<main data-width="1920" data-height="1080"><section data-hf-layer="stage" id="stage"><div id="rig"></div></section></main>');
  for (const file of ['stage-rig/stage-rig.js', 'stage-kit/stage-kit.js', 'stage-kit/blocks/prop-states.js'])
    await page.addScriptTag({path: path.join(card, file)});

  const result = await page.evaluate(() => {
    const kit = window.HarnessStageKit, stage = document.getElementById('stage');
    const options = () => ({
      mount: stage, box: {x: 300, y: 300, w: 900, h: 500},
      parts: [
        {id: 'door', box: {x: 0, y: 0, w: 400, h: 500}, origin: '50% 0', look: {kind: 'paper', color: '#c96'}},
        {id: 'tag', box: {x: 450, y: 0, w: 200, h: 60}, look: {kind: 'label', text: '文案门'}},
        {id: 'pic', box: {x: 450, y: 100, w: 400, h: 300}, look: {kind: 'svg', markup: '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"/>'}}
      ],
      states: {hidden: {door: {y: 200, o: 0}, tag: {o: 0}, pic: {o: 0}}, up: {door: {y: 0, o: 1}, pic: {o: 1}},
               tagged: {tag: {o: 1}}, open: {door: {rx: -70}}},
      start: 'hidden',
      steps: [{at: 1, to: 'up', dur: 0.5, stagger: 0.2}, {at: 2, to: 'tagged', dur: 0.3}, {at: 3, to: 'open', dur: 0.6, ease: 'backOut'}]
    });
    const block = kit.create('prop.states', options());
    const parts = [...block.root.children];
    const snap = t => { block.apply(t); return parts.map(node => [node.style.transform, node.style.opacity, node.style.visibility]); };
    const forward = [0, 1.2, 1.6, 2.4, 3.3, 5].map(snap);
    const backward = [5, 3.3, 2.4, 1.6, 1.2, 0].map(snap).reverse();
    block.apply(1.1);
    const midStagger = parts.map(node => +node.style.opacity);
    block.apply(4);
    const computed = parts.map(node => getComputedStyle(node).position + ':' + getComputedStyle(node).visibility);
    const errors = {};
    const attempt = (name, mutate) => { const o = options(); mutate(o); try { kit.create('prop.states', o).dispose(); errors[name] = 'none'; } catch (error) { errors[name] = error.constructor.name; } };
    attempt('overlap', o => { o.steps[1].at = 1.4; });
    attempt('unknownPart', o => { o.states.up.ghost = {o: 1}; });
    attempt('unknownAxis', o => { o.states.up.door.z = 1; });
    attempt('imgWithoutAlpha', o => { o.parts[2].look = {kind: 'img', src: 'x.png'}; });
    attempt('longLabel', o => { o.parts[1].look.text = '一二三四五六七八九'; });
    attempt('badStart', o => { o.start = 'nope'; });
    attempt('outsideStage', o => { o.mount = document.body; });
    return {forward, backward, midStagger, computed, errors, classes: parts.map(node => node.className)};
  });
  assert.deepEqual(result.forward, result.backward, 'apply(t) is a pure function of t');
  assert.equal(result.forward[0][0][2], 'hidden', 'start state hides the door');
  assert(result.midStagger[0] > 0 && result.midStagger[2] === 0, 'stagger delays the second changed part');
  assert.deepEqual(result.computed, ['absolute:visible', 'absolute:visible', 'absolute:visible']);
  assert.deepEqual(Object.values(result.errors), Array(7).fill('TypeError'), JSON.stringify(result.errors));
  assert(result.classes[1].includes('hf-kit-prop-states-label'));

  // Foreground coverage counts the prop but not rig scenery marked data-hf-set.
  await page.evaluate(() => {
    const rig = window.HarnessStageRig.createPaperStage({mount: document.getElementById('rig')});
    rig.apply({inner: 1, outer: 1, floor: 1, prop: 1});
    for (const node of rig.root.querySelectorAll('.hf-rig-wall, .hf-rig-floor')) node.style.background = '#eee';
  });
  const marked = await page.evaluate(() => [...document.querySelectorAll('.hf-rig-wall-inner-left, .hf-rig-wall-inner-right, .hf-rig-floor')]
    .every(node => node.hasAttribute('data-hf-set')));
  assert(marked, 'rig walls and floor are marked as scenery');
  const info = await page.evaluate(`(${inspectFrame})([], 4)`);
  assert(info.stage_visible > 3, 'scenery still counts as painted stage content');
  assert(info.stage_coverage > 0.05 && info.stage_coverage < 0.2, 'coverage reflects only the prop: ' + info.stage_coverage);
  console.log('stage kit prop.states and coverage checks passed');
} finally {
  await browser.close();
}
