// HYPERFRAMES_CLI=<runtime CLI> node tests/design-examples-browser.mjs <materialized-example> <evidence-directory>
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {actualCharacters, coveredCharacters} from './font_cmap.mjs';
assert(process.env.HYPERFRAMES_CLI, 'Runtime is not configured: HYPERFRAMES_CLI');
// The host ships only the runtime's puppeteer-core; .studio/parser is a development toolchain.
const puppeteer = createRequire(process.env.HYPERFRAMES_CLI)('puppeteer-core');
const [directory, output] = process.argv.slice(2).map(value => path.resolve(value));
assert(directory && output && output !== directory);
await fs.mkdir(output, {recursive: true});
const browser = await puppeteer.launch({executablePath: process.env.HYPERFRAMES_BROWSER_PATH || process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox']});
const errors = [], requests = [], seeks = [], rasterDifferences = [];
const hash = buffer => createHash('sha256').update(buffer).digest('hex');
try {
  const lock = JSON.parse(await fs.readFile(path.join(directory, 'appearance-lock.json'), 'utf8').catch(() => '{}'));
  const page = await browser.newPage();
  await page.setViewport({width: lock.width || 1920, height: lock.height || 1080, deviceScaleFactor: 1});
  page.on('pageerror', error => errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    const url = new URL(request.url());
    if (url.protocol === 'data:') return request.continue(); // in-page data, never intercepted
    if (url.pathname === '/favicon.ico') return request.abort(); // Chromium's own tab icon, not page content
    try {
      assert.equal(url.origin, 'http://example.test');
      const file = await fs.realpath(path.join(directory, decodeURIComponent(url.pathname)));
      assert(file.startsWith(directory + path.sep));
      const types = {'.html':'text/html', '.js':'text/javascript', '.mjs':'text/javascript', '.json':'application/json', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp'};
      await request.respond({status:200, body:await fs.readFile(file), contentType:types[path.extname(file)] ? types[path.extname(file)] + '; charset=utf-8' : 'application/octet-stream'});
    } catch { requests.push(url.href); await request.abort(); }
  });
  const url = 'http://example.test/index.html';
  const load = async () => {
    await page.goto(url);
    await page.evaluate(async () => { await window.__example.ready; await document.fonts.ready; });
    assert.equal(await page.evaluate(() => Object.keys(window.__timelines).length), 1);
  };
  const seek = time => page.evaluate(time => window.__example.seek(time), time);
  const screenshot = async () => {
    // Capture only after the compositor has presented the seeked state.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    return Buffer.from(await page.screenshot());
  };
  const state = () => page.evaluate(() => [...document.querySelectorAll('body *')].map(node => ({
    id: node.id, class: [...node.classList].sort(), style: node.getAttribute('style'),
    transform: getComputedStyle(node).transform, path: node.getAttribute('d'),
    text: node.childElementCount ? null : node.textContent
  })));
  const assertFrame = async (actual, expected, label) => {
    if (hash(actual) === hash(expected)) return;
    const result = await page.evaluate(async ([a, b]) => {
      const pixels = async data => {
        const image = new Image(); image.src = 'data:image/png;base64,' + data; await image.decode();
        const canvas = new OffscreenCanvas(image.width, image.height);
        const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
        return context.getImageData(0, 0, image.width, image.height).data;
      };
      const x = await pixels(a), y = await pixels(b);
      let maximum = 0, changed = 0;
      for (let i = 0; i < x.length; i += 4) {
        let delta = 0;
        for (let channel = 0; channel < 4; channel++) delta = Math.max(delta, Math.abs(x[i + channel] - y[i + channel]));
        maximum = Math.max(maximum, delta); if (delta) changed++;
      }
      return {maximum, changed, pixels: x.length / 4};
    }, [actual.toString('base64'), expected.toString('base64')]);
    rasterDifferences.push({label, ...result});
    if (result.maximum > 1) {
      await fs.writeFile(path.join(output, 'mismatch-expected.png'), expected);
      await fs.writeFile(path.join(output, 'mismatch-actual.png'), actual);
    }
    // Identical DOM/geometry can differ by one 8-bit level after GPU layer reuse.
    assert(result.maximum <= 1, label + ': raster difference ' + JSON.stringify(result));
  };
  await load();
  const duration = await page.evaluate(() => window.__example.duration);
  for (const time of [duration * .15, duration * .52, duration * .7, duration * .9, duration - .1]) {
    await load();
    await seek(time);
    const directState = await state();
    const direct = await screenshot();
    await seek(duration - .01); await seek(time);
    assert.deepEqual(await state(), directState, 'backward state ' + time);
    await assertFrame(await screenshot(), direct, 'backward seek ' + time);
    await seek(time);
    assert.deepEqual(await state(), directState, 'repeat state ' + time);
    await assertFrame(await screenshot(), direct, 'repeat seek ' + time);
    await load();
    for (let step = 0; step < time; step += .2) await seek(step);
    await seek(time);
    assert.deepEqual(await state(), directState, 'sequential state ' + time);
    await assertFrame(await screenshot(), direct, 'sequential seek ' + time);
    const file = 'frame-' + time.toFixed(2) + '.png';
    await fs.writeFile(path.join(output, file), direct);
    seeks.push({time, sha256: hash(direct), file});
  }
  await page.evaluate(async () => {
    for (const source of window.__hfTextSources || []) for (const item of source()) {
      const probe = document.createElement('span');
      probe.textContent = item.text;
      Object.assign(probe.style, {position:'fixed',opacity:'0',fontFamily:item.font_family});
      document.body.append(probe);
    }
    await document.fonts.ready;
  });
  const cdp = await page.createCDPSession();
  await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
  const {root} = await cdp.send('DOM.getDocument');
  const {nodeIds} = await cdp.send('DOM.querySelectorAll', {nodeId: root.nodeId, selector: 'body *'});
  let glyphs = 0;
  for (const nodeId of nodeIds) {
    const {fonts} = await cdp.send('CSS.getPlatformFontsForNode', {nodeId});
    assert(fonts.every(font => font.isCustomFont), 'System fallback font: ' + JSON.stringify(fonts));
    glyphs += fonts.reduce((sum, font) => sum + font.glyphCount, 0);
  }
  assert(glyphs > 0);
  if (lock.card_fonts) {
    const text = await page.evaluate(() => document.body.innerText + [...(window.__hfTextSources || [])].flatMap(source => source()).map(item => item.text).join(''));
    const characters = actualCharacters(text), covered = new Set();
    for (const font of lock.card_fonts.fonts) {
      const file = await fs.realpath(path.join(directory, font.path));
      assert(file.startsWith(directory + path.sep));
      for (const character of coveredCharacters(await fs.readFile(file), characters)) covered.add(character);
    }
    assert.deepEqual([...characters].filter(character => !covered.has(character)), [], 'Card font glyph coverage');
  }
  await cdp.detach();
  await page.evaluate(() => window.__example.dispose());
  const before = await screenshot();
  await page.evaluate(async () => {
    const pending = [];
    window.dispatchEvent(new CustomEvent('hf-seek', {detail: {time: 0, waitUntil: promise => pending.push(promise)}}));
    await Promise.all(pending);
  });
  assert.equal(hash(await screenshot()), hash(before), 'disposed scene must not respond to seek');
  assert.equal(await page.evaluate(() => Object.keys(window.__timelines).length), 0);
  assert.deepEqual(errors, []); assert.deepEqual(requests, []);
  await fs.writeFile(path.join(output, 'result.json'), JSON.stringify({directory, duration, seeks, glyphs, rasterDifferences, rasterTolerance: 1, errors, externalRequests: requests, disposed: true}, null, 2));
  console.log(JSON.stringify({duration, testedSeeks: seeks.length, glyphs, output}));
} finally { await browser.close(); }
