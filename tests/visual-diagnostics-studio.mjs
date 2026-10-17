// Isolated native Studio, no WorkStore and no rendering/encoding paths.
// HF_PACKAGE, CHROME_PATH and VIDEO_FIXTURE point to existing local dependencies.
// VIDEO_FIXTURE: existing moving video of at least 5s, not generated/encoded here.
// Verified with https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import {probe} from '../.studio/visual_probe.mjs';

const {HF_PACKAGE, CHROME_PATH, VIDEO_FIXTURE} = process.env;
assert(HF_PACKAGE && CHROME_PATH, 'Set HF_PACKAGE and CHROME_PATH');
assert.equal(JSON.parse(await fs.readFile(path.join(HF_PACKAGE, 'package.json'))).version, '0.8.150');
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-visual-diagnostics-'));
const project = path.join(root, 'fixture');
await fs.mkdir(project);
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
await fs.copyFile(path.join(repo, '.studio/runtime/figures.js'), path.join(project, 'figures.js'));
await fs.copyFile(process.env.GSAP_FILE || path.join(HF_PACKAGE, '../gsap/dist/gsap.min.js'), path.join(project, 'gsap.js'));
const videoFile = 'video' + path.extname(VIDEO_FIXTURE || 'video.webm');
if (VIDEO_FIXTURE) await fs.copyFile(VIDEO_FIXTURE, path.join(project, videoFile));
const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
const cli = path.join(HF_PACKAGE, 'dist/cli.js');
let server, log = '';
const checks = [];
async function source(mode) {
  if (mode.startsWith('text-layer') || mode === 'nested-frame') {
    await fs.writeFile(path.join(project, 'index.html'), `<!doctype html><meta charset="utf-8"><style>
html,body{margin:0}main{position:relative;width:960px;height:540px;background:white;overflow:hidden}
[data-hf-layer]{position:absolute;inset:0}article,p{position:absolute;left:40px;top:40px;font:32px Arial}
</style><script src="gsap.js"></script>
<main data-composition-id="fixture" data-width="960" data-height="540" data-duration="4">
<div data-hf-layer="text" data-scene-id="S01"><article id="a" data-info-id="I01">Readable explanation</article>
<p id="b" data-info-id="I02" style="visibility:hidden">B evidence remains clear</p></div>
${mode === 'text-layer-broken' ? '<img src="missing.png">' : ''}
${mode === 'nested-frame' ? '<iframe srcdoc="<p>Unverified embedded text</p>"></iframe>' : ''}</main>
<script>window.__timelines={fixture:gsap.timeline({paused:true})
.set('#a',{filter:'blur(6px)'},1).set('#a',{visibility:'hidden'},2)
.set('#a',{visibility:'visible',filter:'none'},3)
.set('#b',{visibility:'visible'},1).set('#b',{visibility:'hidden'},3).to({},{duration:1},3)};</script>`);
    return;
  }
  const video = mode.startsWith('video');
  const duration = video ? 2.5 : 4;
  const mediaTiming = {
    'video-offset': 'data-media-start="0.5" data-playback-rate="1.5" data-duration="2.5"',
    'video-loop': 'data-media-start="4" data-playback-rate="2" data-duration="2.5" loop',
    'video-default-duration': 'data-media-start="4" data-playback-rate="2"',
  }[mode] || 'data-duration="2.5"';
  const actions = {
    static: '.to({}, {duration:4})',
    short: '.to("#block", {x:50,duration:.4}).to({}, {duration:3.6})',
    slow: '.to("#block", {x:60,duration:4,ease:"none"})',
    periodic: '.to("#block", {x:250,duration:.25,ease:"none",repeat:15,yoyo:true})',
    corner: '.to("#corner", {opacity:0,duration:.25,repeat:15,yoyo:true})',
    noise: '.to("main", {backgroundColor:"rgb(246,246,246)",duration:.25,repeat:15,yoyo:true})',
    video: '.to({}, {duration:2.5})',
    broken: '.to({}, {duration:4})',
    transition: '.to({}, {duration:4})',
    rhythm: '.to({}, {duration:4})',
    'transparent-overlay': '.to({}, {duration:4})',
    'opaque-overlay': '.to({}, {duration:4})',
  }[mode] || (video ? '.to({}, {duration:2.5})' : '');
  await fs.writeFile(path.join(project, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:100%;height:100%;overflow:hidden}main{position:relative;width:960px;height:540px;background:rgb(250,250,250)}
#block{position:absolute;width:250px;height:250px;left:100px;top:180px;background:#dd3155}#corner{position:absolute;right:0;top:0;width:5px;height:5px;background:#000}
p{position:absolute;font:26px Arial;left:100px;top:30px}video{position:absolute;width:960px;height:540px;object-fit:cover}.hidden{opacity:0}
</style></head><body><main data-composition-id="fixture" data-width="960" data-height="540" data-duration="${duration}"${mode === 'video-native' ? ' data-no-timeline="true"' : ''}>
<section data-scene-id="S01" class="clip" data-start="0" data-duration="${mode === 'transition' ? 2 : duration}"><p data-info-id="I01">Visible text <span>continues here.</span></p><p class="hidden">Hidden text must not appear.</p><div id="block" data-hf-layer="stage"></div><div id="corner" data-hf-layer="background"></div>
<svg width="300" height="100" style="position:absolute;left:400px;top:100px"><text x="0" y="40">SVG evidence</text></svg></section>
${mode === 'transition' ? '<section class="clip" data-scene-id="S02" data-start="2" data-duration="2"><p>Visible text <span>continues here.</span></p><div style="position:absolute;width:250px;height:250px;left:100px;top:180px;background:#dd3155"></div><svg width="300" height="100" style="position:absolute;left:400px;top:100px"><text x="0" y="40">SVG evidence</text></svg></section>' : ''}
${video ? `<video src="${videoFile}" muted preload="auto" data-start="0" ${mediaTiming} data-track-index="1"></video>` : ''}
${mode === 'broken' ? '<img src="missing.png">' : ''}
${mode.endsWith('-overlay') ? `<div style="position:absolute;inset:0;z-index:20;background:${mode === 'opaque-overlay' ? 'white' : 'transparent'}"><span style="position:absolute;bottom:5px">Overlay footer</span></div>` : ''}
</main>${mode === 'video-native' ? '' : `<script src="gsap.js"></script><script>window.__timelines={fixture:gsap.timeline({paused:true})${actions}};</script>`}
${mode === 'rhythm' ? `<script src="figures.js"></script><script>window.ready=(async()=>{
if(document.readyState==='loading')await new Promise(resolve=>document.addEventListener('DOMContentLoaded',resolve,{once:true}));
const figures=await HarnessFigures.load({assets:[]},{cues:{find:value=>value}});
for(let i=0;i<120&&(!document.querySelector('[data-hf-layer="stage"]')||!document.querySelector('[data-hf-layer="background"]'));i++)await new Promise(resolve=>requestAnimationFrame(resolve));
const target=document.querySelector('[data-hf-layer="stage"]'),background=document.querySelector('[data-hf-layer="background"]');
if(!target||!background)throw new Error('Rhythm fixture DOM missing '+document.body.innerHTML.slice(0,500));
figures.image(target).point(.123,{duration:.04}).pan(1,{duration:2,x:100});
figures.image(background).idle(0,{duration:4});
window.__timelines.fixture.eventCallback('onUpdate',()=>figures.renderAt(window.__timelines.fixture.time()));
await figures.renderAt(0);})();</script>` : ''}</body></html>`);
}
try {
  const url = `http://127.0.0.1:${port}/#project/fixture`;
  for (const mode of ['static', 'short', 'slow', 'periodic', 'corner', 'noise', 'transition', 'rhythm', 'transparent-overlay', 'opaque-overlay', 'broken', 'text-layer', 'text-layer-broken', 'nested-frame',
    ...(VIDEO_FIXTURE ? ['video', 'video-native', 'video-offset', 'video-loop', 'video-default-duration'] : [])]
    .filter(mode => !process.env.PROBE_MODES || process.env.PROBE_MODES.split(',').includes(mode))) {
    await source(mode);
    const index = path.join(project, 'index.html');
    const before = await fs.readFile(index);
    // Match registered review copies: Studio's first-read ID stamp must not trigger its file watcher.
    await fs.chmod(index, 0o444);
    server = spawn(process.execPath, [cli, 'preview', project, '--port', String(port), '--foreground', '--no-open', '--no-proxy'],
      {env: {...process.env, HOME: root, XDG_CONFIG_HOME: root, XDG_CACHE_HOME: root, DO_NOT_TRACK: '1', HYPERFRAMES_NO_TELEMETRY: '1'}});
    server.stdout.on('data', data => { log += data; }); server.stderr.on('data', data => { log += data; });
    let ready = false;
    for (let i = 0; i < 300; i++) {
      try { if ((await fetch(url)).ok) { ready = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, log);
    const report = await probe({cli, browser: CHROME_PATH, url,
      scenes: mode === 'transition' ? [{id: 'S01', start: 0, duration: 2}, {id: 'S02', start: 2, duration: 2}]
        : [{id: 'S01', start: 0, duration: mode.startsWith('video') ? 2.5 : 4}], parameters: {timeout_ms: mode.includes('broken') ? 300 : 10000}});
    await fs.writeFile(path.join(root, mode + '.json'), JSON.stringify(report, null, 2));
    assert.deepEqual(await fs.readFile(index), before, 'Studio must not rewrite the sampled source');
    assert(!('motion' in report), 'D2 stillness output is retired');
    if (mode.includes('broken') || mode === 'nested-frame') {
      assert(report.samples.every(item => !item.ready));
    } else {
      assert(report.samples.every(item => item.ready), `${mode}: ${JSON.stringify(report.samples.filter(item => !item.ready))}`);
      if (mode === 'text-layer') {
        const texts = report.samples.flatMap(item => item.texts);
        assert(texts.length > 0, 'visible DOM yields D1 text');
        assert(texts.some(item => item.info === 'I01'), 'the text panel was actually sampled');
        assert(texts.every(item => item.scene === 'S01' && ['I01', 'I02'].includes(item.info) && item.layer === 'text'),
          'text inherits host scene/info and fourth layer');
        assert(report.samples.filter(item => item.time > 1 && item.time < 3).every(item =>
          item.texts.length > 0 && item.texts.every(text => text.info === 'I02')),
          'hidden/blurred A text is not sampled while clear B text remains');
      } else if (!mode.startsWith('video')) {
        const text = report.samples.flatMap(item => item.texts).map(item => item.text).join(' ');
        assert.equal(text.includes('Visible text'), mode !== 'opaque-overlay', 'Transparent containers do not hide painted text');
        assert.equal(text.includes('SVG evidence'), mode !== 'opaque-overlay', 'Opaque covering content remains excluded');
        if (mode.endsWith('-overlay')) assert(text.includes('Overlay footer'));
        assert(!text.includes('Hidden text'));
        if (mode === 'rhythm') {
          const before = report.samples.find(item => item.time === .122);
          const after = report.samples.find(item => item.time === .143);
          assert(before && after, 'probe samples a short helper event between fixed-grid times');
          const candidate = sample => sample.rhythm_candidates.find(item => item.kind === 'point');
          assert(candidate(after).visible);
          assert.notEqual(candidate(before).signature, candidate(after).signature);
          assert(report.samples.every(item => item.rhythm_candidates.every(event => event.layer === 'stage')));
        }
      }
    }
    if (mode === 'transition') {
      const scenes = [{id: 'S02', start: 2, duration: 2}];
      const ranged = await probe({cli, browser: CHROME_PATH, url, scenes, range: [2, 4], parameters: {timeout_ms: 10000}});
      assert(ranged.samples.length > 0 && ranged.samples.every(item => item.ready && item.time >= 2), 'range limits sampling');
      const evidence = path.join(root, 'scoped-frames');
      const exact = await probe({cli, browser: CHROME_PATH, url, scenes, range: [2, 4], times: [2.5, 3.25],
        measurements: true, fps: 60, evidence_dir: evidence, parameters: {timeout_ms: 10000}});
      assert.deepEqual(exact.samples.map(item => item.time), [2.5, 3.25], 'explicit times replace the grid');
      assert(exact.samples.every(item => item.screenshot), 'explicit samples are saved as frames');
      for (const item of exact.samples) await fs.access(path.join(evidence, item.screenshot));
      assert.deepEqual(exact.determinism.map(item => [item.time, item.identical]), [[2.5, true], [3.25, true]],
        'every explicit time is re-seeked through both ends and compared');
      checks.push({mode: 'transition-scoped', samples: ranged.samples.length + exact.samples.length});
    }
    checks.push({mode, samples: report.samples.length});
    server.kill('SIGTERM'); await once(server, 'exit'); server = null;
    await fs.chmod(index, 0o644);
  }
  console.log(JSON.stringify({platform: process.platform, actualStudio: '0.8.150', viewport: {width: 960, height: 540},
    checks, realVideo: !!VIDEO_FIXTURE, evidence: root}));
} finally {
  if (server && server.exitCode === null) { server.kill('SIGTERM'); await once(server, 'exit'); }
  for (const file of [path.join(project, 'index.html')]) {
    await fs.chmod(file, 0o644).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}
