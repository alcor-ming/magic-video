// PLAYWRIGHT_PACKAGE=/path/to/playwright CHROME_PATH=/path/to/chromium node tests/motion-v3-browser.mjs
// Isolated, runnable Motion v3 example. No production assets, Studio acceptance, or video export.
// Runs once the Python coordinator's v3 contract/resolver landed; skips cleanly without a browser.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {inspectRhythmFrame} from '../.studio/visual_probe.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const require = createRequire(process.env.PLAYWRIGHT_PACKAGE ? path.join(process.env.PLAYWRIGHT_PACKAGE, 'package.json') : import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); }
catch (error) {
  console.error(`motion-v3-browser: SKIPPED, playwright/browser is unavailable (${error.message}); install it and set PLAYWRIGHT_PACKAGE to run.`);
  process.exit(3);
}

const output = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-motion-v3-'));
const build = spawnSync('python3', ['-c', `
import copy, json, os, pathlib, shutil, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / '.studio'))
import asset_store as store, appearance
root = pathlib.Path(sys.argv[2]); harness = root / 'harness'; harness.mkdir()
shutil.copyfile(pathlib.Path(sys.argv[1]) / 'windows-runtime.lock.json', harness / 'windows-runtime.lock.json')
os.environ.update(HYPERFRAMES_AI_ASSET_CONFIG=str(root / 'config.json'), HYPERFRAMES_AI_ROOT=str(harness), HYPERFRAMES_AI_ASSET_ROOT='')
assets = root / 'store'; store.configure_asset_store(harness, assets)
SLOTS = ('reveal', 'emphasis', 'exit', 'transition')
refs = {}

def make(name, kind, payload, contract_version):
    source = root / name; source.mkdir()
    (source / 'asset.json').write_text(json.dumps({'schema_version':2,'id':name,'version':1,'kind':kind,'entry':'entry.json','contract_version':contract_version,'parameters':{},'compatibility':{},'dependencies':[]}))
    (source / 'entry.json').write_text(json.dumps(payload))
    candidate = store.pack_source(assets, source)
    store.accept_component(assets, candidate['component_ref'], candidate['package_sha256'], 'Motion v3 isolated fixture', runtime_root=harness)
    refs[name] = {'ref': candidate['component_ref'], 'kind': kind, 'package_sha256': candidate['package_sha256']}

theme_a = {'tokens': {'typography': {'body': 'sans-serif'}, 'colors': {'text': '#17272c', 'accent': '#c12655'}, 'surface': {'color': '#ffffff'}}}
theme_b = {'tokens': {'typography': {'body': 'sans-serif'}, 'colors': {'text': '#17272c', 'accent': '#167340'}, 'surface': {'color': '#ffffff'}}}
background = {'renderer': 'solid', 'parameters': {'color': '#e0e8ec'}}
make('theme', 'theme', theme_a, 1)
make('theme2', 'theme', theme_b, 1)
make('background', 'background', background, 1)

def reduced_emphasis(effect):
    base = {'effect': effect, 'duration': 0, 'easing': 'linear'}
    if effect == 'focus-restore':
        base.update(restore_duration=0, color_token='colors.accent', outline_width=4)
    elif effect == 'glow':
        base['color_token'] = 'colors.accent'
    elif effect == 'pulse':
        base['scale'] = 1.12
    elif effect == 'shake':
        base.update(x=0, y=0)
    elif effect == 'wobble':
        base['rotate'] = 0
    return base

def v3(reveal, emphasis, exit_slot, transition):
    return {'capability_version': 3,
            'slots': {'reveal': reveal, 'emphasis': emphasis, 'exit': exit_slot, 'transition': transition},
            'reduced_motion': {
                'reveal': {'effect': 'fade', 'duration': 0.1, 'easing': 'linear', 'opacity_from': 0, 'opacity_to': 1, 'hide_before': True},
                'emphasis': reduced_emphasis(emphasis['effect']),
                'exit': {'effect': 'fade-out', 'duration': 0.1, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0},
                'transition': {'effect': 'cut', 'duration': 0, 'easing': 'linear'}}}

reveal_pop = {'effect': 'pop', 'duration': 0.6, 'easing': 'back-out', 'opacity_from': 0, 'opacity_to': 1, 'scale': 0.6, 'hide_before': True}
reveal_stamp = {'effect': 'stamp', 'duration': 0.6, 'easing': 'spring', 'opacity_from': 0, 'opacity_to': 1, 'scale': 1.4, 'rotate': -12, 'hide_before': True}
reveal_wipe = {'effect': 'wipe', 'duration': 0.6, 'easing': 'ease-out', 'opacity_from': 0, 'opacity_to': 1, 'direction': 'left', 'hide_before': True}
reveal_glitch = {'effect': 'glitch-in', 'duration': 0.6, 'easing': 'linear', 'opacity_from': 0, 'opacity_to': 1, 'x': 16, 'y': 0, 'hide_before': True}
reveal_fade = {'effect': 'fade', 'duration': 0.3, 'easing': 'linear', 'opacity_from': 0, 'opacity_to': 1, 'hold_fps': 12, 'hide_before': True}
emphasis_pulse = {'effect': 'pulse', 'duration': 0.5, 'easing': 'linear', 'scale': 1.12}
emphasis_shake = {'effect': 'shake', 'duration': 0.5, 'easing': 'linear', 'x': 6, 'y': 0}
emphasis_wobble = {'effect': 'wobble', 'duration': 0.5, 'easing': 'linear', 'rotate': 8}
emphasis_glow = {'effect': 'glow', 'duration': 0.5, 'easing': 'linear', 'color_token': 'colors.accent', 'blur': 16}
emphasis_focus = {'effect': 'focus-restore', 'duration': 0.5, 'restore_duration': 0.5, 'easing': 'linear', 'color_token': 'colors.accent', 'outline_width': 4}
exit_pop = {'effect': 'pop-out', 'duration': 0.6, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0, 'scale': 0.75}
exit_wipe = {'effect': 'wipe-out', 'duration': 0.6, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0, 'direction': 'right'}
exit_glitch = {'effect': 'glitch-out', 'duration': 0.6, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0, 'x': 16, 'y': 0}
exit_fade = {'effect': 'fade-out', 'duration': 0.6, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0}
transition_wipe = {'effect': 'wipe', 'duration': 1, 'easing': 'linear', 'direction': 'left'}
transition_push = {'effect': 'push', 'duration': 1, 'easing': 'linear', 'direction': 'up'}
transition_glitch = {'effect': 'glitch-cut', 'duration': 1, 'easing': 'linear'}
transition_cut = {'effect': 'cut', 'duration': 0, 'easing': 'linear'}
transition_cross = {'effect': 'crossfade', 'duration': 1, 'easing': 'linear', 'hold_fps': 12}

make('v3-1', 'motion', v3(reveal_pop, emphasis_pulse, exit_pop, transition_wipe), 3)
make('v3-2', 'motion', v3(reveal_stamp, emphasis_shake, exit_wipe, transition_push), 3)
make('v3-3', 'motion', v3(reveal_wipe, emphasis_wobble, exit_glitch, transition_glitch), 3)
make('v3-4', 'motion', v3(reveal_glitch, emphasis_glow, exit_fade, transition_cut), 3)
make('v3-5', 'motion', v3(reveal_fade, emphasis_focus, exit_fade, transition_cross), 3)

m2 = {'capability_version': 2,
      'slots': {'reveal': {'effect': 'short-rise', 'duration': 1, 'easing': 'linear', 'opacity_from': 0, 'opacity_to': 1, 'y': 20, 'hide_before': True},
                'emphasis': {'effect': 'focus-restore', 'duration': 0.5, 'restore_duration': 0.5, 'easing': 'linear', 'color_token': 'colors.accent', 'outline_width': 4},
                'exit': {'effect': 'fade-out', 'duration': 1, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0, 'x': 20},
                'transition': {'effect': 'crossfade', 'duration': 1, 'easing': 'linear'}},
      'reduced_motion': {'reveal': {'effect': 'short-rise', 'duration': 0.1, 'easing': 'linear', 'opacity_from': 0, 'opacity_to': 1, 'y': 0, 'hide_before': True},
                         'emphasis': {'effect': 'focus-restore', 'duration': 0, 'restore_duration': 0, 'easing': 'linear', 'color_token': 'colors.accent', 'outline_width': 4},
                         'exit': {'effect': 'fade-out', 'duration': 0.1, 'easing': 'linear', 'opacity_from': 1, 'opacity_to': 0, 'x': 0},
                         'transition': {'effect': 'cut', 'duration': 0, 'easing': 'linear'}}}
make('m2', 'motion', m2, 2)

def sel(name):
    return {'asset': refs[name], 'entry': None}

def four(name):
    return {slot: {'asset': refs[name], 'entry': slot} for slot in SLOTS}

def project(name, theme, motion):
    target = root / ('project-' + name); target.mkdir()
    account = {'id': 'fixture-' + name, 'revision': 1, 'theme': refs[theme], 'background': refs['background'], 'ratio': '16:9'}
    lock = appearance.resolve(harness, account, {}, legacy_motion=motion)
    appearance.materialize(harness, target, lock)
    appearance.verify(target, lock)

project('v3-1', 'theme', four('v3-1'))
project('v3-2', 'theme', four('v3-2'))
project('v3-3', 'theme', four('v3-3'))
project('v3-4', 'theme', four('v3-4'))
project('v3-5', 'theme', four('v3-5'))
project('v3-4b', 'theme2', four('v3-4'))
project('mixed', 'theme', {'reveal': {'asset': refs['m2'], 'entry': 'reveal'},
                           'emphasis': {'asset': refs['v3-2'], 'entry': 'emphasis'},
                           'exit': {'asset': refs['v3-3'], 'entry': 'exit'},
                           'transition': {'asset': refs['v3-4'], 'entry': 'transition'}})
shutil.rmtree(assets)
`, repo, output], { encoding: 'utf8' });
assert.equal(build.status, 0, `fixture build failed: ${build.stderr || build.stdout}`);

const specs = {
  'v3-1':  { endCue: 3, conflict: true, effects: { reveal: 'pop', emphasis: 'pulse', exit: 'pop-out', transition: 'wipe' } },
  'v3-2':  { endCue: 3, conflict: true, effects: { reveal: 'stamp', emphasis: 'shake', exit: 'wipe-out', transition: 'push' } },
  'v3-3':  { endCue: 3, conflict: false, effects: { reveal: 'wipe', emphasis: 'wobble', exit: 'glitch-out', transition: 'glitch-cut' } },
  'v3-4':  { endCue: 2, conflict: false, effects: { reveal: 'glitch-in', emphasis: 'glow', exit: 'fade-out', transition: 'cut' } },
  'v3-5':  { endCue: 3, conflict: false, effects: { reveal: 'fade', emphasis: 'focus-restore', exit: 'fade-out', transition: 'crossfade' } },
  'v3-4b': { endCue: 2, conflict: false, effects: { reveal: 'glitch-in', emphasis: 'glow', exit: 'fade-out', transition: 'cut' } },
  'mixed': { endCue: 2, conflict: true, effects: { reveal: 'short-rise', emphasis: 'shake', exit: 'glitch-out', transition: 'cut' } },
};
const durations = { pop: 0.6, stamp: 0.6, wipe: 0.6, 'glitch-in': 0.6, fade: 0.3, 'short-rise': 1, pulse: 0.5, shake: 0.5, wobble: 0.5, glow: 0.5, 'focus-restore': 0.5, 'pop-out': 0.6, 'wipe-out': 0.6, 'glitch-out': 0.6, 'fade-out': 0.6 };
const transitionDurations = { wipe: 1, push: 1, 'glitch-cut': 1, cut: 0, crossfade: 1 };

const html = spec => `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>*{box-sizing:border-box}body{margin:0}main{min-height:100vh;padding:32px;display:grid;align-content:center;gap:32px;font-family:var(--appearance-typography-body)}h1{font-size:28px;margin:0}.examples{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:32px}.item,.scene{height:120px;padding:20px;background:#fff;border:1px solid #50626a;border-radius:4px;font-size:24px;opacity:.6;transform:translateX(8px) scale(.95);outline:1px solid rgb(20,40,60)}.handoff{position:relative;height:120px}.scene{position:absolute;inset:0;transform:none}#incoming{background:#b9ddca}#outgoing{background:#f1c6d1}@media(max-width:600px){main{padding:24px}.examples{grid-template-columns:1fr;gap:24px}.item,.scene{height:100px}.handoff{height:100px}}</style>
<main id="stage" data-hf-layer="stage"><h1 data-appearance-text>Motion v3</h1><div class="examples"><article class="item" id="reveal">Reveal</article><article class="item" id="emphasis">Emphasis</article><article class="item" id="exit">Exit</article><div class="handoff"><article class="scene" id="outgoing">Outgoing</article><article class="scene" id="incoming">Incoming</article></div></div></main>
<script src="runtime/appearance.js"></script><script>
const target=id=>document.getElementById(id);
window.ready=HarnessAppearance.load().then(value=>{HarnessAppearance.apply(target('stage'),value);window.appearance=value;return value});
window.bindExample=async reducedMotion=>{const a=await ready;window.bindings=[
  HarnessAppearance.bindMotion(target('reveal'),a,'reveal',{cue:2,reducedMotion}),
  HarnessAppearance.bindMotion(target('emphasis'),a,'emphasis',{cue:2,restoreCue:4,reducedMotion}),
  HarnessAppearance.bindMotion(target('exit'),a,'exit',{cue:2,reducedMotion}),
  HarnessAppearance.bindMotion({outgoing:target('outgoing'),incoming:target('incoming')},a,'transition',{cue:2,endCue:${spec.endCue},overlap:[2,${spec.endCue}],reducedMotion})
];};
window.seekExample=time=>bindings.forEach(binding=>binding.seek(time));
window.readState=()=>Object.fromEntries(['reveal','emphasis','exit','outgoing','incoming'].map(id=>{const s=getComputedStyle(target(id));return[id,{opacity:Number(s.opacity),transform:s.transform,visibility:s.visibility,clipPath:s.clipPath,boxShadow:s.boxShadow,outlineColor:s.outlineColor,outlineWidth:s.outlineWidth}]}));
window.conflictTest=async reducedMotion=>{const a=await ready;const reveal=HarnessAppearance.bindMotion(target('reveal'),a,'reveal',{cue:2,reducedMotion});let threw=false,emphasis;try{emphasis=HarnessAppearance.bindMotion(target('reveal'),a,'emphasis',{cue:2,restoreCue:4,reducedMotion});}catch{threw=true;}emphasis?.dispose();reveal.dispose();return{threw,animations:document.getAnimations().length};};
window.rhythmTest=async reducedMotion=>{const a=await ready;const before=(window.__hfRhythmSources||new Set()).size;const bindings=[HarnessAppearance.bindMotion(target('reveal'),a,'reveal',{cue:2,reducedMotion}),HarnessAppearance.bindMotion(target('emphasis'),a,'emphasis',{cue:2,restoreCue:4,reducedMotion}),HarnessAppearance.bindMotion(target('exit'),a,'exit',{cue:2,reducedMotion}),HarnessAppearance.bindMotion({outgoing:target('outgoing'),incoming:target('incoming')},a,'transition',{cue:2,endCue:${spec.endCue},overlap:[2,${spec.endCue}],reducedMotion})];const sources=[...(window.__hfRhythmSources||[])].filter(fn=>typeof fn==='function');const events=sources.flatMap(fn=>fn()).map(e=>({time:e.time,kind:e.kind,duration:e.duration,id:e.target&&e.target.id}));bindings.forEach(b=>{b.dispose();b.dispose();});return{before,after:(window.__hfRhythmSources||new Set()).size,events};};
</script>`;
for (const name of Object.keys(specs)) await fs.writeFile(path.join(output, `project-${name}`, 'index.html'), html(specs[name]));

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

const near = (actual, expected, message) => assert(Math.abs(actual - expected) < 0.01, `${message}: ${actual} != ${expected}`);
const times = [1, 2, 2.05, 2.2, 2.25, 2.29, 2.3, 2.5, 2.6, 3, 4, 4.5, 5];
const diagnose = samples => {
  const result = spawnSync('python3', ['-c', `import json,sys
sys.path.insert(0,sys.argv[1]+'/.studio')
from visual_diagnostics import rhythm_diagnostics
print(json.dumps(rhythm_diagnostics(json.load(sys.stdin),[dict(id='S01',start=0,duration=5)])))`, repo], {input:JSON.stringify(samples),encoding:'utf8'});
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
};
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const visit = async name => {
    await page.goto(`http://127.0.0.1:${server.address().port}/project-${name}/index.html`);
    await page.evaluate(() => ready);
  };
  const lockVersions = {};
  const glowShadows = {};
  for (const name of Object.keys(specs)) {
    lockVersions[name] = JSON.parse(await fs.readFile(path.join(output, `project-${name}`, 'appearance-lock.json'), 'utf8')).schema_version;
  }
  assert.equal(lockVersions['mixed'], 3, 'Mixed v2/v3 closure freezes lock contract 3');
  assert(Object.values(lockVersions).every(version => version === 3), 'Every v3 project freezes lock contract 3');

  for (const viewport of [{ width: 1280, height: 720 }, { width: 960, height: 720 }, { width: 450, height: 800 }]) {
    await page.setViewportSize(viewport);
    for (const reduced of [false, true]) {
      for (const name of Object.keys(specs)) {
        const spec = specs[name];
        await visit(name);
        const base = await page.evaluate(() => readState());
        const layout = await page.evaluate(() => Object.fromEntries(['reveal', 'emphasis', 'exit', 'outgoing', 'incoming'].map(id => { const rect = target(id).getBoundingClientRect(); return [id, { x: rect.x, right: rect.right, y: rect.y, bottom: rect.bottom }]; })));
        await page.evaluate(mode => bindExample(mode), reduced);
        const forward = await page.evaluate(list => list.map(time => { seekExample(time); return { time, state: readState() }; }), times);
        const backward = await page.evaluate(list => { const out = []; for (const time of [...list].reverse()) { seekExample(time); out.push({ time, state: readState() }); } return out.reverse(); }, times);
        const paused = await page.evaluate(() => document.getAnimations().every(animation => animation.playState === 'paused'));
        await page.evaluate(() => seekExample(2.5));
        const beforeWait = await page.evaluate(() => readState());
        await new Promise(resolve => setTimeout(resolve, 80));
        const still = await page.evaluate(() => readState());
        const disposed = await page.evaluate(() => {
          bindings.forEach(binding => { binding.dispose(); binding.dispose(); });
          return { state: readState(), animations: document.getAnimations().length };
        });
        await page.evaluate(mode => bindExample(mode), reduced);
        const direct = await page.evaluate(() => { seekExample(2.25); return readState(); });
        await page.evaluate(() => bindings.forEach(binding => binding.dispose()));

        assert.equal(paused, true, `${name}/${reduced}: every animation stays paused`);
        assert.deepEqual(still, beforeWait, `${name}/${reduced}: no independent animation clock`);
        assert.deepEqual(forward, backward, `${name}/${reduced}: forward and backward seek agree`);
        assert.deepEqual(direct, forward.find(row => row.time === 2.25).state, `${name}/${reduced}: fresh direct seek agrees with sequential playback`);
        assert.deepEqual(disposed.state, base, `${name}/${reduced}: dispose restores sampled base styles`);
        assert.equal(disposed.animations, 0, `${name}/${reduced}: dispose cancels every animation`);
        for (const item of Object.values(layout)) assert(item.x >= 0 && item.right <= viewport.width && item.y >= 0 && item.bottom <= viewport.height, `${name}/${reduced}: example stays inside the viewport`);

        const at = time => forward.find(row => row.time === time).state;
        const endCue = spec.endCue;
        if (reduced) {
          assert.equal(at(1).reveal.visibility, 'hidden', `${name}: reduced reveal still hidden before cue`);
          assert.equal(at(2.5).reveal.transform, base.reveal.transform, `${name}: reduced reveal has no transform`);
          assert.equal(at(1).outgoing.visibility, base.outgoing.visibility, `${name}: reduced transition is not pre-hidden`);
          assert.equal(at(endCue).incoming.visibility, 'visible', `${name}: reduced transition cuts at cue`);
          if (spec.effects.emphasis === 'focus-restore') {
            assert.equal(at(2.25).emphasis.outlineColor, name === 'v3-4b' ? 'rgb(22, 115, 64)' : 'rgb(193, 38, 85)', `${name}: reduced focus-restore stays valid`);
            assert.equal(at(4.5).emphasis.outlineColor, base.emphasis.outlineColor, `${name}: reduced focus-restore restores`);
          } else {
            assert.equal(at(2.25).emphasis.transform, base.emphasis.transform, `${name}: reduced one-shot emphasis is static`);
            assert.equal(at(2.25).emphasis.boxShadow, base.emphasis.boxShadow, `${name}: reduced one-shot emphasis shadow is static`);
          }
          continue;
        }

        assert.equal(at(1).reveal.visibility, 'hidden', `${name}: reveal hidden before cue`);
        if (['pop', 'stamp', 'glitch-in', 'short-rise'].includes(spec.effects.reveal)) {
          assert.notEqual(at(2).reveal.transform, base.reveal.transform, `${name}: reveal moves at cue`);
          assert.equal(at(name === 'mixed' ? 3 : 2.6).reveal.transform, base.reveal.transform, `${name}: reveal settles on base transform`);
        }
        if (spec.effects.reveal === 'wipe') assert.notEqual(at(2).reveal.clipPath, base.reveal.clipPath, `${name}: wipe reveal clips at cue`);
        if (spec.effects.reveal === 'fade') {
          near(at(2).reveal.opacity, 0, `${name}: holds exact cue`);
          near(at(2.25).reveal.opacity, at(2.29).reveal.opacity, `${name}: hold_fps quantizes intermediate progress`);
          assert.notEqual(at(2.2).reveal.opacity, at(2.25).reveal.opacity, `${name}: hold_fps steps forward`);
          near(at(2.3).reveal.opacity, base.reveal.opacity, `${name}: holds exact end`);
        }
        if (['pulse', 'shake', 'wobble'].includes(spec.effects.emphasis)) {
          assert.notEqual(at(2.25).emphasis.transform, base.emphasis.transform, `${name}: emphasis animates`);
          assert.equal(at(2.5).emphasis.transform, base.emphasis.transform, `${name}: emphasis returns to base`);
        }
        if (spec.effects.emphasis === 'glow') {
          assert.notEqual(at(2.25).emphasis.boxShadow, base.emphasis.boxShadow, `${name}: glow animates shadow`);
          assert.equal(at(2.5).emphasis.boxShadow, base.emphasis.boxShadow, `${name}: glow returns to base shadow`);
          if (!reduced) glowShadows[name] = at(2.25).emphasis.boxShadow;
        }
        if (spec.effects.emphasis === 'focus-restore') {
          const accent = name === 'v3-4b' ? 'rgb(22, 115, 64)' : 'rgb(193, 38, 85)';
          assert.notEqual(at(2.25).emphasis.outlineColor, base.emphasis.outlineColor, `${name}: focus interpolates from base`);
          assert.equal(at(2.5).emphasis.outlineColor, accent, `${name}: focus-restore uses frozen Theme color`);
          assert.equal(at(4.5).emphasis.outlineColor, base.emphasis.outlineColor, `${name}: focus-restore restores base outline`);
        }
        if (spec.effects.exit === 'pop-out') assert.notEqual(at(2.6).exit.transform, base.exit.transform, `${name}: pop-out moves`);
        if (spec.effects.exit === 'wipe-out') assert.notEqual(at(2.6).exit.clipPath, base.exit.clipPath, `${name}: wipe-out clips`);
        if (['glitch-out', 'fade-out'].includes(spec.effects.exit)) near(at(2.6).exit.opacity, 0, `${name}: exit ends hidden`);
        assert.equal(at(3).exit.visibility, 'hidden', `${name}: exit hidden after end`);
        if (spec.effects.transition === 'crossfade') near(at(2.5).outgoing.opacity, base.outgoing.opacity * 0.5, `${name}: crossfade midpoint`);
        if (spec.effects.transition === 'cut') {
          assert.equal(at(2).incoming.visibility, 'visible', `${name}: cut reveals incoming at cue`);
          assert.equal(at(2).outgoing.visibility, 'hidden', `${name}: cut hides outgoing at cue`);
        }
        if (spec.effects.transition === 'wipe') assert.notEqual(at(2.5).incoming.clipPath, base.incoming.clipPath, `${name}: wipe transition clips incoming`);
        if (spec.effects.transition === 'push') {
          assert.notEqual(at(2.5).outgoing.transform, base.outgoing.transform, `${name}: push moves outgoing`);
          assert.notEqual(at(2.5).incoming.transform, base.incoming.transform, `${name}: push moves incoming`);
        }
        if (spec.effects.transition === 'glitch-cut') {
          near(at(3).outgoing.opacity, 0, `${name}: glitch-cut hides outgoing`);
          near(at(3).incoming.opacity, base.incoming.opacity, `${name}: glitch-cut reveals incoming`);
        }
      }
    }
  }

  await page.setViewportSize({ width: 1280, height: 720 });
  assert.notEqual(glowShadows['v3-4'], glowShadows['v3-4b'], 'two Themes drive different glow colors');
  for (const [name, spec] of Object.entries(specs)) {
    await visit(name);
    const conflict = await page.evaluate(() => conflictTest(false));
    assert.equal(conflict.threw, spec.conflict, `${name}: property conflict ${spec.conflict ? 'rejected' : 'composed'}`);
    assert.equal(conflict.animations, 0, `${name}: conflict cleanup is clean`);
    await visit(name);
    const rhythm = await page.evaluate(() => rhythmTest(false));
    assert.equal(rhythm.before, 0, `${name}: no stale rhythm sources`);
    assert.equal(rhythm.after, 0, `${name}: dispose removes rhythm sources`);
    for (const slot of ['reveal', 'emphasis', 'exit']) {
      const event = rhythm.events.find(item => item.kind === `motion_${slot}` && item.time === 2);
      assert(event, `${name}: rhythm event for ${slot}`);
      assert.equal(event.id, slot, `${name}: rhythm target for ${slot}`);
      assert.equal(event.duration, durations[spec.effects[slot]], `${name}: rhythm duration for ${slot}`);
    }
    const transitionEvents = rhythm.events.filter(item => item.kind === 'motion_transition' && item.time === 2);
    assert.deepEqual(transitionEvents.map(item => item.id).sort(), ['incoming', 'outgoing'], `${name}: transition registers distinct actual targets`);
    assert(transitionEvents.every(item => item.duration === transitionDurations[spec.effects.transition]), `${name}: transition rhythm duration`);
    if (spec.effects.emphasis === 'focus-restore') {
      const restore = rhythm.events.find(item => item.kind === 'motion_emphasis' && item.time === 4);
      assert(restore, `${name}: focus restore point registered`);
      assert.equal(restore.duration, 0.5, `${name}: focus restore duration`);
    }
    await page.evaluate(() => bindExample(false));
    const candidates = await page.evaluate(inspectRhythmFrame);
    const probeTimes = [...new Set(candidates.flatMap(event => [event.before ?? event.time-.001,
      event.after ?? event.time+(event.duration/2 || .001)]))].sort((a,b)=>a-b);
    const samples = [];
    for (const time of probeTimes) {
      await page.evaluate(time => seekExample(time), time);
      samples.push({time,ready:true,texts:[],rhythm_candidates:await page.evaluate(inspectRhythmFrame)});
    }
    const report = diagnose(samples);
    for (const slot of ['reveal','emphasis','exit','transition']) assert(report.events.some(event=>event.kind===`motion_${slot}`), `${name}: real probe observes ${slot}`);
    await page.evaluate(() => bindings.forEach(binding=>binding.dispose()));
  }
  await visit('v3-1');
  await page.evaluate(() => {target('emphasis').style.visibility='hidden';return bindExample(false);});
  const hiddenSamples=[];
  for (const time of [1.999,2.1,2.3]) {
    await page.evaluate(time=>seekExample(time),time);
    hiddenSamples.push({time,ready:true,texts:[],rhythm_candidates:await page.evaluate(inspectRhythmFrame)});
  }
  assert(!diagnose(hiddenSamples).events.some(event=>event.kind==='motion_emphasis'),'hidden Motion is not counted');
  await page.evaluate(() => {bindings.forEach(binding=>binding.dispose());target('emphasis').style.visibility='visible';
    const copy={...appearance,motion:structuredClone(appearance.motion)};copy.motion.emphasis.slots.emphasis.scale=1;
    window.bindings=[HarnessAppearance.bindMotion(target('emphasis'),copy,'emphasis',{cue:2,reducedMotion:false})];});
  const noopSamples=[];
  for (const time of [1.999,2.1]) {
    await page.evaluate(time=>seekExample(time),time);
    noopSamples.push({time,ready:true,texts:[],rhythm_candidates:await page.evaluate(inspectRhythmFrame)});
  }
  assert.equal(diagnose(noopSamples).events.length,0,'unchanged Motion is not counted');
  await page.evaluate(()=>bindings.forEach(binding=>binding.dispose()));
  await visit('v3-4');
  await page.evaluate(()=>{window.bindings=[HarnessAppearance.bindMotion(target('reveal'),appearance,'reveal',{cue:2}),
    HarnessAppearance.bindMotion(target('reveal'),appearance,'emphasis',{cue:2})];seekExample(2.25);});
  const composed=await page.evaluate(inspectRhythmFrame);
  assert.deepEqual(composed.filter(event=>event.targets.includes('reveal')).map(event=>event.kind).sort(),
    ['motion_emphasis','motion_reveal'],'disjoint Motion slots on one target retain both rhythm candidates');
  await page.evaluate(()=>bindings.forEach(binding=>binding.dispose()));
  assert.deepEqual(errors, [], 'no page errors');
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify({ lockVersions, specs }, null, 2));
  console.log(output);
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
