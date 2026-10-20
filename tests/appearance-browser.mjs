// PLAYWRIGHT_PACKAGE=/path/to/playwright node tests/appearance-browser.mjs
// Synthetic browser evidence only, not native Studio or production acceptance.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(process.env.PLAYWRIGHT_PACKAGE ? path.join(process.env.PLAYWRIGHT_PACKAGE, 'package.json') : import.meta.url);
const { chromium } = require('playwright');
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-appearance-'));
const build = spawnSync('python3', ['-c', `
import json, os, pathlib, shutil, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / '.studio'))
import asset_store as store, appearance
root = pathlib.Path(sys.argv[2]); harness = root / 'harness'; harness.mkdir()
shutil.copyfile(pathlib.Path(sys.argv[1]) / 'windows-runtime.lock.json', harness / 'windows-runtime.lock.json')
os.environ.update(HYPERFRAMES_AI_ASSET_CONFIG=str(root/'config.json'), HYPERFRAMES_AI_ROOT=str(harness), HYPERFRAMES_AI_ASSET_ROOT='')
assets = root / 'store'; store.configure_asset_store(harness, assets)
refs = {}
for name, kind, payload in [
 ('paper','theme',{'tokens':{'colors':{'text':'#000000'},'surface':{'color':'#ffffff'}}}),
 ('light','background',{'renderer':'solid','parameters':{'color':'#d9e9e3'}}),
 ('dark','background',{'renderer':'solid','parameters':{'color':'#24332e'}}),
 ('clear','background',{'renderer':'transparent','parameters':{}}),
 ('gentle','motion',{'slots':{'reveal':{'duration':1,'easing':'linear','x':40},'emphasis':{'duration':1,'easing':'power2.out','stagger':0.1}},'reduced_motion':{'reveal':{'duration':0.1,'easing':'power2.out'}}})]:
 source = root/name; source.mkdir()
 parameters = {'tokens.colors.text':{'type':'string','default':'#000000'}} if kind == 'theme' else {'slots.reveal.duration':{'type':'number','minimum':0,'default':1}} if kind == 'motion' else {}
 (source/'asset.json').write_text(json.dumps({'schema_version':2,'id':name,'version':1,'kind':kind,'entry':'entry.json','contract_version':1,'parameters':parameters,'compatibility':{}}))
 (source/'entry.json').write_text(json.dumps(payload))
 candidate = store.pack_source(assets, source)
 store.accept_component(assets,candidate['component_ref'],candidate['package_sha256'],'Synthetic browser fixture',runtime_root=harness)
 refs[name] = {'ref':candidate['component_ref'],'kind':kind,'package_sha256':candidate['package_sha256']}
for name in ('light','dark','clear','moving'):
 project = root/('project-'+name); project.mkdir()
 account = {'id':'fixture','revision':1,'theme':refs['paper'],'background':refs['light' if name == 'moving' else name],'mode':'explainer','ratio':'16:9','motion':{'reveal':None,'emphasis':None,'exit':None,'transition':None}}
 account['overrides'] = {'theme':{'tokens.colors.text':'#19352b'}}
 legacy = None
 if name == 'moving':
  legacy = {'reveal':{'asset':refs['gentle'],'entry':'reveal'}}
  account['overrides']['motion'] = {'reveal':{'slots.reveal.duration':2}}
 lock = appearance.resolve(harness, account, legacy_motion=legacy)
 appearance.materialize(harness,project,lock)
free = root/'project-free'; free.mkdir()
appearance.materialize(harness,free,appearance.resolve(harness,{},{'mode':'showcase','submodule':'pdoom'}))
shutil.rmtree(assets)
appearance.verify(free,json.loads((free/'appearance-lock.json').read_text()))
for name in ('light','dark','clear','moving'):
 project = root/('project-'+name)
 appearance.verify(project,json.loads((project/'appearance-lock.json').read_text()))
`, repo, output], { encoding: 'utf8' });
assert.equal(build.status, 0, build.stderr);
const html = `<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><style>
*{box-sizing:border-box}body{margin:0;font:20px system-ui;background:#b6b9bc}main{min-height:100vh;padding:48px 24px;display:grid;align-content:center;justify-items:center}article{padding:28px;max-width:520px;width:100%;border:1px solid #89998f;border-radius:6px}h1{font-size:32px;margin:0 0 16px}p{line-height:1.5;margin:0}
</style><main id="stage"><article data-appearance-card><h1 data-appearance-text>Three Clear Choices</h1><p data-appearance-text>Theme controls the foreground. The background is selected independently.</p></article></main><script src="runtime/appearance.js"></script><script>window.ready=HarnessAppearance.load().then(value=>HarnessAppearance.apply(document.querySelector('main'),value));</script>`;
for (const name of ['light', 'dark', 'clear', 'moving', 'free']) await fs.writeFile(path.join(output, `project-${name}`, 'index.html'), html);
const server = http.createServer(async (request, response) => {
  try {
    const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).slice(1);
    assert(relative && !relative.split('/').includes('..'));
    const data = await fs.readFile(path.join(output, relative));
    response.setHeader('Content-Type', relative.endsWith('.js') ? 'application/javascript' : relative.endsWith('.json') ? 'application/json' : 'text/html');
    response.end(data);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const evidence = [];
  for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const readings = [];
    for (const name of ['light', 'dark', 'clear']) {
      await page.goto(`http://127.0.0.1:${server.address().port}/project-${name}/index.html`);
      await page.evaluate(() => ready);
      const reading = await page.evaluate(() => ({
        background: getComputedStyle(document.querySelector('main')).backgroundColor,
        foreground: getComputedStyle(document.querySelector('h1')).color,
        surface: getComputedStyle(document.querySelector('article')).backgroundColor,
        text: document.querySelector('article').textContent,
        box: document.querySelector('article').getBoundingClientRect().toJSON(),
        overflow: document.documentElement.scrollWidth > innerWidth,
        motion: document.querySelector('article').getAnimations().length,
      }));
      assert.equal(reading.foreground, 'rgb(25, 53, 43)');
      assert.equal(reading.surface, 'rgb(255, 255, 255)');
      assert.equal(reading.background, { light: 'rgb(217, 233, 227)', dark: 'rgb(36, 51, 46)', clear: 'rgba(0, 0, 0, 0)' }[name]);
      assert.equal(reading.overflow, false);
      assert.equal(reading.motion, 0);
      await page.evaluate(async () => {
        const appearance = await ready;
        const card = document.querySelector('article');
        const before = card.getAttribute('style');
        const motion = HarnessAppearance.bindMotion(card, appearance, 'reveal');
        motion.seek(4);
        motion.dispose();
        if (card.getAttribute('style') !== before || card.getAnimations().length) throw Error('Disabled Motion changed the element');
      });
      assert(reading.box.x >= 0 && reading.box.right <= viewport.width && reading.box.bottom <= viewport.height);
      const screenshot = path.join(output, `${name}-${viewport.width}.png`);
      await page.screenshot({ path: screenshot });
      const pixels = spawnSync('python3', ['-c', 'from PIL import Image; import sys; im=Image.open(sys.argv[1]).convert("RGB"); assert len(set(im.getdata())) > 30; assert im.getpixel((1,1)) != (255,255,255)', screenshot]);
      assert.equal(pixels.status, 0, pixels.stderr.toString());
      readings.push(reading);
      evidence.push({ viewport, name, ...reading, screenshot });
    }
    const { background, ...baseline } = readings[0];
    assert.deepEqual(readings.map(({ background, ...rest }) => rest), Array(3).fill(baseline));
  }
  await page.goto(`http://127.0.0.1:${server.address().port}/project-moving/index.html`);
  await page.evaluate(() => ready);
  const motion = await page.evaluate(async () => {
    const card = document.querySelector('article');
    const binding = HarnessAppearance.bindMotion(card, await ready, 'reveal', { cue: 2 });
    const frames = [];
    for (const time of [2.5, 2, 3, 2.5]) {
      binding.seek(time);
      frames.push(getComputedStyle(card).transform);
    }
    await new Promise(resolve => setTimeout(resolve, 80));
    const still = getComputedStyle(card).transform;
    binding.dispose();
    let unsupportedReduced = false;
    try { HarnessAppearance.bindMotion(card, await ready, 'reveal', { cue: 2, reducedMotion: true }); }
    catch { unsupportedReduced = card.getAnimations().length === 0; }
    return { frames, still, unsupportedReduced, animations: card.getAnimations().length };
  });
  assert.equal(motion.frames[0], motion.frames[3]);
  assert.equal(motion.frames[0], 'matrix(1, 0, 0, 1, 30, 0)', 'Frozen dot-path Motion override must apply');
  assert.equal(motion.frames[0], motion.still, 'Motion must not run its own clock');
  assert.notEqual(motion.frames[0], motion.frames[1]);
  assert.notEqual(motion.frames[0], motion.frames[2]);
  assert.equal(motion.animations, 0);
  assert.equal(motion.unsupportedReduced, true, 'Legacy unsupported presets fail only when selected, without effects');
  await page.goto(`http://127.0.0.1:${server.address().port}/project-free/index.html`);
  const free = await page.evaluate(async () => {
    const appearance = await ready;
    const stage = document.querySelector('main'), card = document.querySelector('article');
    const background = await HarnessAppearance.mountBackground(stage, appearance, { find() {} });
    background.renderAt(1);
    const motion = HarnessAppearance.bindMotion(card, appearance, 'reveal');
    motion.seek(1);
    motion.dispose();
    background.dispose();
    return { theme: appearance.theme, background: appearance.background, stage: stage.getAttribute('style'),
             foreground: getComputedStyle(document.querySelector('h1')).color, card: card.getAttribute('style') };
  });
  assert.deepEqual(free, { theme: null, background: null, stage: null, foreground: 'rgb(0, 0, 0)', card: null },
                   'Showcase without selected appearance must leave the host look untouched');
  assert.deepEqual(errors, []);
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify({ static: evidence, motion, free }, null, 2));
  console.log(output);
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
