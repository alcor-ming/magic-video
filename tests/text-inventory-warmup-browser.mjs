// Set HYPERFRAMES_CLI and HYPERFRAMES_BROWSER_PATH (or CHROME_PATH) before running.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {performance} from 'node:perf_hooks';

const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'text-inventory-warmup-'));
try {
  const project = path.join(temporary, 'project');
  await fs.mkdir(project);
  const write = (name, content) => fs.writeFile(path.join(project, name), content);
  await fs.copyFile('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', path.join(project, 'font.ttf'));
  await write('appearance-lock.json', JSON.stringify({card_fonts:{fonts:[{path:'font.ttf'}]}}));
  await write('COMPONENT_LOCK.json', JSON.stringify({components:[{asset_kind:'character',vendor_path:'character'}]}));
  await fs.mkdir(path.join(project, 'character'));
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABMAAAAHCAIAAABldeEWAAAAFklEQVR4nGNsaGhgIAswkadtVCcRAABqzgGOe8RgZQAAAABJRU5ErkJggg==', 'base64');
  const wav = Buffer.concat([
    Buffer.from('524946464403000057415645666d74201000000001000100401f0000401f0000010008006461746120030000', 'hex'),
    Buffer.alloc(800, 128),
  ]);
  await write('stage.png', image);
  await write('character/original.png', image);
  await write('payload.png', image);
  await write('sound.wav', wav);
  const request = path.join(temporary, 'request.json');
  const scenes = [{id:'S01',start:0,duration:2}, {id:'S02',start:2,duration:2}];
  await fs.writeFile(request, JSON.stringify({project, scenes}));

  const html = extra => write('index.html', `<!doctype html><meta charset="utf-8">
<style>
  @font-face { font-family: HarnessFont_Test; src: url(font.ttf) }
  body { font-family: HarnessFont_Test }
</style>
<img id="picture" src="stage.png">
<img id="character" src="character/original.png">
<audio id="sound" src="sound.wav" preload="auto"></audio>
<canvas></canvas><div id="title" data-hf-layer="text"></div><div id="captions" data-hf-layer="captions"></div>
${extra}
<script>
  const family = 'HarnessFont_Test';
  const canvas = document.querySelector('canvas').getContext('2d');
  const items = [
    {scene:'S01',asset:'fixture',id:'covered',text:'Stage',start:0,end:2,embedded:true,font_family:family},
    {scene:'S02',asset:'fixture',id:'missing',text:'Canvas 龘',start:2,end:4,embedded:true,font_family:family},
  ];
  window.__hfTextSources = new Set([() => items.map(item => ({...item}))]);
  window.__example = {ready: Promise.all([
    (async () => {
      const image = document.getElementById('picture');
      await image.decode();
      if (image.naturalWidth !== 19 || image.naturalHeight !== 7) throw Error('Stage image dimensions changed');
    })(),
    (async () => {
      const image = document.getElementById('character');
      await image.decode();
      const context = document.createElement('canvas').getContext('2d');
      context.drawImage(image, 0, 0);
      if (context.getImageData(0, 0, 1, 1).data[0] !== 128) throw Error('Character image was replaced');
    })(),
    (async () => {
      const response = await fetch('payload.png');
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== ${image.length} || bytes[0] !== 137) throw Error('Fetch response was replaced');
    })(),
    new Promise((resolve, reject) => {
      const audio = document.getElementById('sound');
      audio.addEventListener('loadeddata', resolve, {once:true});
      audio.addEventListener('error', () => reject(Error('Stage audio failed to load')), {once:true});
      if (audio.readyState >= 2) resolve();
      if (audio.error) reject(Error('Stage audio failed to load'));
    }),
    document.fonts.load('32px ' + family),
  ])};
  window.addEventListener('hf-seek', ({detail:{time}}) => {
    const index = Number(time >= 2);
    document.getElementById('title').textContent = index === 0 ? 'Title 雪' : 'Title';
    document.getElementById('captions').textContent = index === 1 ? 'Caption 仄' : 'Caption';
    canvas.font = '32px ' + family;
    canvas.fillText(items[index].text, 5, 45);
  });
</script>`);
  const inspect = () => JSON.parse(execFileSync(process.execPath, ['.studio/text_inventory.mjs',request],
    {encoding:'utf8', timeout:20000, stdio:['ignore','pipe','pipe']}));
  const fails = pattern => assert.throws(inspect, error => error.status === 1 && pattern.test(error.stderr));

  await html('');
  const small = inspect();
  assert.equal(small.complete, true);
  assert.deepEqual(small.items.map(({scene, text, font_coverage}) => [scene, text, font_coverage]), [
    ['S01','Stage',true], ['S02','Canvas 龘',false],
  ]);
  assert.deepEqual(small.dom_fonts, {coverage:false, missing:['雪','仄']});
  console.log('Small fixture verifies DOM text, captions, canvas text and missing glyphs');

  // Trailing space on disk leaves the valid PNG intact and makes reading it through CDP expensive.
  await fs.truncate(path.join(project, 'stage.png'), 160 * 1024 * 1024);
  const start = performance.now();
  const large = inspect();
  const seconds = (performance.now() - start) / 1000;
  assert.ok(seconds < 12, `160 MiB image inventory took ${seconds.toFixed(2)} s`);
  assert.deepEqual(large, small);
  console.log(`160 MiB image inventory matches the small fixture in ${seconds.toFixed(2)} s`);

  await html('<img src="missing.png"><audio src="missing.wav" preload="auto"></audio>');
  fails(/ENOENT[^\n]*missing\.png/);
  console.log('Missing stage image is rejected');
  fails(/ENOENT[^\n]*missing\.wav/);
  console.log('Missing stage audio is rejected');
  await html('<img src="https://example.invalid/stage.png">');
  fails(/External source request/);
  await fs.writeFile(path.join(temporary, 'outside.png'), image);
  await html('<img src="/..%2foutside.png">');
  fails(/Source path escaped snapshot/);
  console.log('External and escaping stage images are rejected');
} finally { await fs.rm(temporary,{recursive:true,force:true}); }
