// PLAYWRIGHT_PACKAGE=/path/to/playwright CHROME_PATH=/path/to/chromium node tests/motion-browser.mjs
// Isolated, runnable four-slot example. No production assets, Studio acceptance, or video export.
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
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-motion-'));
const build = spawnSync('python3', ['-c', `
import copy, json, os, pathlib, shutil, sys
sys.path.insert(0,str(pathlib.Path(sys.argv[1])/'.studio'))
import asset_store as store, appearance
root=pathlib.Path(sys.argv[2]); harness=root/'harness'; harness.mkdir()
shutil.copyfile(pathlib.Path(sys.argv[1])/'windows-runtime.lock.json',harness/'windows-runtime.lock.json')
os.environ.update(HYPERFRAMES_AI_ASSET_CONFIG=str(root/'config.json'),HYPERFRAMES_AI_ROOT=str(harness),HYPERFRAMES_AI_ASSET_ROOT='')
assets=root/'store'; store.configure_asset_store(harness,assets)
slots={
 'reveal':{'effect':'short-rise','duration':1,'easing':'linear','opacity_from':0,'opacity_to':1,'y':20,'hide_before':True},
 'exit':{'effect':'fade-out','duration':1,'easing':'linear','opacity_from':1,'opacity_to':0,'x':20},
 'emphasis':{'effect':'focus-restore','duration':0.5,'restore_duration':0.5,'easing':'linear','color_token':'colors.accent','outline_width':4},
 'transition':{'effect':'crossfade','duration':1,'easing':'linear'}}
reduced=copy.deepcopy(slots)
reduced['reveal'].update(y=0,duration=0.1)
reduced['exit'].update(x=0,duration=0.1)
reduced['emphasis'].update(duration=0,restore_duration=0)
reduced['transition'].update(effect='cut',duration=0)
refs={}
for name in ('theme','second','background','motion','fade-cut'):
 source=root/name; source.mkdir(); kind='theme' if name=='second' else 'motion' if name=='fade-cut' else name
 dependencies=[]; parameters={}
 if kind=='theme':
  payload={'tokens':{'typography':{'body':'"Fixture Chinese", serif'},'colors':{'text':'#17272c','accent':'#c12655' if name=='theme' else '#167340'},'surface':{'color':'#ffffff'}}}
  shutil.copyfile(sys.argv[3],source/'local.otf'); shutil.copyfile(sys.argv[4],source/'LICENSE.txt')
  dependencies=['local.otf','LICENSE.txt']; payload['fonts']=[{'family':'Fixture Chinese','path':'local.otf','license':'LICENSE.txt','style':'normal','weight':400}]
 elif kind=='background': payload={'renderer':'solid','parameters':{'color':'#e0e8ec'}}
 else:
  payload={'capability_version':2,'slots':slots,'reduced_motion':reduced}
  parameters={key:{'type':typ,'default':value} for key,typ,value in [('slots.reveal.duration','number',1),('slots.reveal.hide_before','boolean',True),('reduced_motion.reveal.duration','number',0.1),('reduced_motion.reveal.hide_before','boolean',True)]}
  if name=='fade-cut':
   payload=copy.deepcopy(payload)
   for group in ('slots','reduced_motion'):
    payload[group]['reveal'].update(effect='fade'); payload[group]['reveal'].pop('y')
    payload[group]['transition'].update(effect='cut',duration=0)
 (source/'asset.json').write_text(json.dumps({'schema_version':2,'id':name,'version':1,'kind':kind,'entry':'entry.json','contract_version':2 if kind=='motion' else 1,'parameters':parameters,'compatibility':{},'dependencies':dependencies}))
 (source/'entry.json').write_text(json.dumps(payload))
 candidate=store.pack_source(assets,source)
 store.accept_component(assets,candidate['component_ref'],candidate['package_sha256'],'Isolated four-slot browser fixture',runtime_root=harness)
 refs[name]={'ref':candidate['component_ref'],'kind':kind,'package_sha256':candidate['package_sha256']}
for name in ('normal','zero','second','disabled','fade-cut'):
 project=root/('project-'+name); project.mkdir()
 account={'id':'fixture','revision':1,'theme':refs['second' if name=='second' else 'theme'],'background':refs['background'],'ratio':'16:9'}
 legacy={slot:{'asset':refs['fade-cut' if name=='fade-cut' else 'motion'],'entry':slot} for slot in slots}
 overrides={}
 if name=='zero': overrides={'parameters':{'motion':{'reveal':{'slots.reveal.duration':0,'slots.reveal.hide_before':False,'reduced_motion.reveal.duration':0,'reduced_motion.reveal.hide_before':False}}}}
 if name=='disabled': overrides={'motion':dict.fromkeys(slots)}
 lock=appearance.resolve(harness,account,overrides,legacy_motion=legacy); appearance.materialize(harness,project,lock); appearance.verify(project,lock)
shutil.rmtree(assets)
`, repo, output, process.env.TEST_CHINESE_FONT || '/usr/share/fonts/opentype/unifont/unifont.otf', process.env.TEST_CHINESE_FONT_LICENSE || '/usr/share/doc/fonts-unifont/copyright'], { encoding: 'utf8' });
assert.equal(build.status, 0, build.stderr);
const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>*{box-sizing:border-box}body{margin:0}main{min-height:100vh;padding:32px;display:grid;align-content:center;gap:32px;font-family:var(--appearance-typography-body)}h1{font-size:28px;margin:0}.examples{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:32px}.item,.scene{height:120px;padding:20px;background:#fff;border:1px solid #50626a;border-radius:4px;font-size:24px;opacity:.6;transform:translateX(8px) scale(.95);outline:1px solid rgb(20,40,60)}.handoff{position:relative;height:120px}.scene{position:absolute;inset:0;transform:none}#incoming{background:#b9ddca}#outgoing{background:#f1c6d1}p{margin:12px 0 0;font-size:18px}@media(max-width:600px){main{padding:24px}.examples{grid-template-columns:1fr;gap:24px}.item,.scene{height:100px}.handoff{height:100px}}</style>
<main id="stage"><h1 data-appearance-text>Motion / &#21160;&#25928;</h1><div class="examples"><article class="item" id="reveal">Reveal<p>01</p></article><article class="item" id="emphasis">Emphasis<p>02</p></article><article class="item" id="exit">Exit<p>03</p></article><div class="handoff"><article class="scene" id="outgoing">Outgoing</article><article class="scene" id="incoming">Incoming</article></div></div></main>
<script src="runtime/appearance.js"></script><script>
const target=id=>document.getElementById(id);
window.ready=HarnessAppearance.load().then(value=>{HarnessAppearance.apply(target('stage'),value);window.appearance=value;return value});
window.bindExample=async reducedMotion=>{const a=await ready;window.bindings=[HarnessAppearance.bindMotion(target('reveal'),a,'reveal',{cue:2,reducedMotion}),HarnessAppearance.bindMotion(target('emphasis'),a,'emphasis',{cue:2,restoreCue:4,reducedMotion}),HarnessAppearance.bindMotion(target('exit'),a,'exit',{cue:2,reducedMotion}),HarnessAppearance.bindMotion({outgoing:target('outgoing'),incoming:target('incoming')},a,'transition',{cue:2,endCue:3,overlap:[2,3],reducedMotion})];};
window.seekExample=time=>bindings.forEach(binding=>binding.seek(time));
window.readExample=()=>Object.fromEntries(['reveal','emphasis','exit','outgoing','incoming'].map(id=>{const style=getComputedStyle(target(id));return[id,{opacity:Number(style.opacity),transform:style.transform,visibility:style.visibility,outlineColor:style.outlineColor,outlineWidth:style.outlineWidth,box:target(id).getBoundingClientRect().toJSON()}]}));
</script>`;
for (const name of ['normal', 'zero', 'second', 'disabled', 'fade-cut']) await fs.writeFile(path.join(output, `project-${name}`, 'index.html'), html);
const server = http.createServer(async (request, response) => {
  try {
    const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).slice(1);
    assert(relative && !relative.split('/').includes('..'));
    const data = await fs.readFile(path.join(output, relative));
    response.setHeader('Content-Type', relative.endsWith('.js') ? 'application/javascript' : relative.endsWith('.json') ? 'application/json' : relative.endsWith('.otf') ? 'font/otf' : 'text/html');
    response.end(data);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
const near = (actual, expected, message) => assert(Math.abs(actual - expected) < 0.001, `${message}: ${actual} != ${expected}`);
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const page = await browser.newPage();
  const errors = []; const evidence = [];
  page.on('pageerror', error => errors.push(error.message));
  const visit = async (name = 'normal') => {
    await page.goto(`http://127.0.0.1:${server.address().port}/project-${name}/index.html`);
    await page.evaluate(() => ready);
  };
  for (const viewport of [{ width: 1280, height: 720 }, { width: 960, height: 720 }, { width: 450, height: 800 }]) {
    await page.setViewportSize(viewport);
    for (const reduced of [false, true]) {
      await visit();
      const base = await page.evaluate(() => readExample());
      const fontState = await page.evaluate(() => ({ faces: [...document.fonts].map(face => face.status), family: getComputedStyle(target('stage')).fontFamily, width: target('stage').getBoundingClientRect().width }));
      assert(fontState.faces.length && fontState.faces.every(status => status === 'loaded'));
      assert(fontState.family.includes('HarnessFont_'));
      await page.evaluate(mode => bindExample(mode), reduced);
      const states = await page.evaluate(async () => {
        const times = [1, 2, 2.05, 2.25, 2.5, 3, 4, 4.25, 4.5, 5, 2.5, 1, 2.5];
        const result = times.map(time => {seekExample(time); return {time, state:readExample()};});
        const animations = document.getAnimations().map(a=>a.playState);
        await new Promise(resolve=>setTimeout(resolve,80));
        return {result, animations, still:readExample(), width:target('stage').getBoundingClientRect().width};
      });
      assert(states.animations.length && states.animations.every(state => state === 'paused'));
      assert.equal(states.width, fontState.width);
      assert.deepEqual(states.result[4].state, states.result[10].state);
      assert.deepEqual(states.result[4].state, states.result[12].state);
      assert.deepEqual(states.still, states.result[4].state, 'No independent animation clock');
      const at = time => states.result.find(row => row.time === time).state;
      assert.equal(at(1).reveal.visibility, 'hidden');
      assert.equal(at(1).incoming.visibility, 'hidden');
      near(at(1).exit.opacity, 0.6, 'Exit preserves base before cue');
      near(at(2).reveal.opacity, 0, 'Reveal cue');
      near(at(3).reveal.opacity, 0.6, 'Reveal restores base opacity');
      assert.equal(at(3).reveal.transform, base.reveal.transform);
      assert.equal(at(3).exit.visibility, 'hidden');
      assert.equal(at(3).outgoing.visibility, 'hidden');
      assert.equal(at(3).incoming.visibility, 'visible');
      near(at(3).incoming.opacity, 0.6, 'Incoming preserves base opacity');
      assert.equal(at(3).emphasis.outlineColor, 'rgb(193, 38, 85)');
      assert.equal(at(3).emphasis.outlineWidth, '4px');
      assert.equal(at(4.5).emphasis.outlineColor, base.emphasis.outlineColor);
      assert.equal(at(4.5).emphasis.outlineWidth, base.emphasis.outlineWidth);
      if (reduced) {
        assert.equal(at(2.05).reveal.transform, base.reveal.transform);
        assert.equal(at(2).emphasis.outlineColor, 'rgb(193, 38, 85)');
        assert.equal(at(4).emphasis.outlineColor, base.emphasis.outlineColor);
        assert.equal(at(2).outgoing.visibility, 'hidden', 'Reduced cut occurs at start, not end');
        near(at(2).incoming.opacity, 0.6, 'Reduced incoming at start');
      } else {
        near(at(2.5).reveal.opacity, 0.3, 'Reveal midpoint');
        assert.notEqual(at(2.5).reveal.transform, base.reveal.transform);
        near(at(2.5).exit.opacity, 0.3, 'Exit midpoint');
        near(at(2.5).outgoing.opacity, 0.3, 'Outgoing midpoint');
        near(at(2.5).incoming.opacity, 0.3, 'Incoming midpoint');
        assert.notEqual(at(2.25).emphasis.outlineColor, base.emphasis.outlineColor);
        assert.notEqual(at(4.25).emphasis.outlineColor, base.emphasis.outlineColor);
      }
      for (const item of Object.values(states.still)) assert(item.box.x >= 0 && item.box.right <= viewport.width && item.box.y >= 0 && item.box.bottom <= viewport.height, 'Example remains inside viewport');
      const screenshot = path.join(output, `${viewport.width}-${reduced ? 'reduced' : 'regular'}-2.5.png`);
      await page.screenshot({ path: screenshot });
      const pixels = spawnSync('python3', ['-c', 'from PIL import Image; import sys; im=Image.open(sys.argv[1]).convert("RGB"); assert len(set(im.getdata())) > 40; assert im.getpixel((0,0)) == (224,232,236)', screenshot]);
      assert.equal(pixels.status, 0, pixels.stderr.toString());
      evidence.push({viewport,reduced,states,screenshot,fontState});
      const disposed = await page.evaluate(() => {
        target('reveal').style.color='rgb(7, 8, 9)';
        bindings.forEach(b=>{b.dispose();b.dispose();});
        return {state:readExample(),color:getComputedStyle(target('reveal')).color,animations:document.getAnimations().length};
      });
      assert.deepEqual(disposed.state, base);
      assert.equal(disposed.color, 'rgb(7, 8, 9)');
      assert.equal(disposed.animations, 0);
      await page.evaluate(async mode => {await bindExample(mode);seekExample(2.5);}, reduced);
      assert.deepEqual(await page.evaluate(() => readExample()), states.result[4].state, 'Fresh direct seek matches sequential playback');
      await page.evaluate(() => bindings.forEach(binding => binding.dispose()));
    }
  }
  await visit('zero');
  const zero = await page.evaluate(() => {
    const binding=HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal',{cue:2,reducedMotion:false});
    const states=[1,2,3,1,2].map(t=>{binding.seek(t);return readExample().reveal;});binding.dispose();return states;
  });
  assert.equal(zero[0].visibility, 'visible', 'False override survives frozen resolution');
  near(zero[1].opacity, 0.6, 'Zero duration snaps at cue');
  assert.deepEqual(zero[1], zero[4]);
  assert.deepEqual(zero[0], zero[3]);
  await visit('fade-cut');
  const fadeCut = await page.evaluate(() => {
    const base=readExample();
    const fade=HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal',{cue:2,reducedMotion:false});
    const cut=HarnessAppearance.bindMotion({outgoing:target('outgoing'),incoming:target('incoming')},appearance,'transition',{cue:2,endCue:2,reducedMotion:false});
    const states=[1,2,2.5,3,1,2].map(time=>{fade.seek(time);cut.seek(time);return readExample();});
    fade.dispose();cut.dispose();return {base,states};
  });
  near(fadeCut.states[2].reveal.opacity, 0.3, 'Fade midpoint');
  assert.equal(fadeCut.states[2].reveal.transform, fadeCut.base.reveal.transform);
  assert.equal(fadeCut.states[0].incoming.visibility, 'hidden');
  assert.equal(fadeCut.states[1].incoming.visibility, 'visible');
  assert.equal(fadeCut.states[1].outgoing.visibility, 'hidden');
  assert.deepEqual(fadeCut.states[0], fadeCut.states[4]);
  assert.deepEqual(fadeCut.states[1], fadeCut.states[5]);
  await visit('disabled');
  assert.equal(await page.evaluate(() => {const before=target('reveal').outerHTML;const b=HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal');b.seek(5);b.dispose();return before===target('reveal').outerHTML && !document.getAnimations().length;}), true);
  await visit();
  const isolation = await page.evaluate(async () => {
    const first=HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal',{cue:2,reducedMotion:false});
    const emphasis=HarnessAppearance.bindMotion(target('reveal'),appearance,'emphasis',{cue:2,restoreCue:4,reducedMotion:false});
    first.seek(2.5);emphasis.seek(3);
    const composed=readExample().reveal;
    const other=await HarnessAppearance.load('../project-second/');
    const second=HarnessAppearance.bindMotion(target('emphasis'),other,'emphasis',{cue:2,restoreCue:4,reducedMotion:false});
    second.seek(3);const color=getComputedStyle(target('emphasis')).outlineColor;
    first.dispose();emphasis.dispose();appearance.dispose();
    second.seek(3);const after=getComputedStyle(target('emphasis')).outlineColor;
    second.dispose();other.dispose();return {composed,color,after,animations:document.getAnimations().length};
  });
  near(isolation.composed.opacity, 0.3, 'Disjoint-property composition');
  assert.equal(isolation.composed.outlineColor, 'rgb(193, 38, 85)');
  assert.equal(isolation.color, 'rgb(22, 115, 64)');
  assert.equal(isolation.after, isolation.color);
  assert.equal(isolation.animations, 0);
  await visit();
  const invalid = await page.evaluate(() => {
    const a=appearance, r=target('reveal'), out=target('outgoing'), incoming=target('incoming');
    const cases=[
      ()=>HarnessAppearance.bindMotion(null,a,'reveal',{cue:2}),
      ()=>HarnessAppearance.bindMotion(r,a,'reveal',{cue:NaN}),
      ()=>HarnessAppearance.bindMotion(r,a,'emphasis',{cue:2,restoreCue:1}),
      ()=>HarnessAppearance.bindMotion({outgoing:out,incoming:out},a,'transition',{cue:2,endCue:3,overlap:[2,3]}),
      ()=>HarnessAppearance.bindMotion({outgoing:out,incoming},a,'transition',{cue:2,endCue:3}),
      ()=>HarnessAppearance.bindMotion({outgoing:out,incoming},a,'transition',{cue:2,endCue:3,overlap:[2.5,3]}),
      ()=>HarnessAppearance.bindMotion({outgoing:out,incoming},a,'transition',{cue:2,endCue:4,overlap:[2,4]}),
      ()=>HarnessAppearance.bindMotion(document.createElement('div'),a,'reveal',{cue:2}),
      ()=>{incoming.style.display='none';try{return HarnessAppearance.bindMotion({outgoing:out,incoming},a,'transition',{cue:2,endCue:3,overlap:[2,3]});}finally{incoming.style.display='';}},
      ()=>HarnessAppearance.bindMotion({outgoing:out.parentElement,incoming},a,'transition',{cue:2,endCue:3,overlap:[2,3]}),
      ()=>{incoming.parentElement.style.opacity='0';try{return HarnessAppearance.bindMotion({outgoing:out,incoming},a,'transition',{cue:2,endCue:3,overlap:[2,3]});}finally{incoming.parentElement.style.opacity='';}},
    ];
    const results=cases.map(fn=>{const before=document.getAnimations().length;try{fn();return false;}catch{return document.getAnimations().length===before;}});
    const binding=HarnessAppearance.bindMotion(r,a,'reveal',{cue:2});
    const before=document.getAnimations().length;let conflict=false;
    try{HarnessAppearance.bindMotion(r,a,'exit',{cue:4});}catch{conflict=document.getAnimations().length===before;}
    binding.dispose();
    const external=r.animate([{opacity:.2},{opacity:.5}],{duration:1000,fill:'both'});external.pause();
    let externalConflict=false;try{HarnessAppearance.bindMotion(r,a,'reveal',{cue:2});}catch{externalConflict=document.getAnimations().length===1;}
    external.cancel();return {results,conflict,externalConflict,remaining:document.getAnimations().length};
  });
  assert(invalid.results.every(Boolean), JSON.stringify(invalid));
  assert.equal(invalid.conflict, true);
  assert.equal(invalid.externalConflict, true);
  assert.equal(invalid.remaining, 0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await visit();
  await page.evaluate(() => {window.fixed=HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal',{cue:2});fixed.seek(2.05);window.beforeMode=readExample().reveal;});
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  assert.equal(await page.evaluate(() => {fixed.seek(2.05);const unchanged=JSON.stringify(readExample().reveal)===JSON.stringify(beforeMode);fixed.dispose();return unchanged;}), true, 'Reduced mode fixed at preparation');
  const declaration = path.join(output, 'project-normal/vendor/components/motion/v1/entry.json');
  const original = await fs.readFile(declaration, 'utf8');
  const loadFailures = [];
  for (const mutate of [
    value => { value.slots.reveal.unknown = 1; },
    value => { value.slots.exit.opacity_from = 2; },
    value => { value.slots.emphasis.color_token = 'colors.missing'; },
    value => { value.capability_version = 3; },
    value => { delete value.slots.reveal; },
    value => { delete value.reduced_motion.emphasis; },
  ]) {
    const changed = JSON.parse(original); mutate(changed);
    await fs.writeFile(declaration, JSON.stringify(changed));
    loadFailures.push(await page.evaluate(async () => {
      const fonts=document.fonts.size, animations=document.getAnimations().length;
      try {await HarnessAppearance.load();return false;} catch {return fonts===document.fonts.size && animations===document.getAnimations().length;}
    }));
  }
  await fs.writeFile(declaration, original);
  assert(loadFailures.every(Boolean), 'Invalid frozen declarations must fail before font/effect preparation');
  await page.route('**/local.otf', route => route.abort());
  const fontFailure = await page.evaluate(async () => {
    const before=document.fonts.size;
    try {await HarnessAppearance.load();return false;} catch {return document.fonts.size===before && document.getAnimations().length===0;}
  });
  await page.unroute('**/local.otf');
  assert.equal(fontFailure, true, 'Missing font must not produce a ready Motion instance');
  assert.deepEqual(errors, []);
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify({evidence,zero,fadeCut,isolation,invalid,loadFailures,fontFailure}, null, 2));
  console.log(output);
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
