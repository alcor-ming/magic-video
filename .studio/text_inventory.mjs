// Collect module declarations from a frozen project; never render a movie.
import fs from 'node:fs/promises';
import {coveredCharacters, actualCharacters} from './font_cmap.mjs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {crc32, deflateSync} from 'node:zlib';
if (!process.env.HYPERFRAMES_CLI) throw new Error('Runtime is not configured: HYPERFRAMES_CLI');
// The host ships only the runtime's puppeteer-core; .studio/parser is a development toolchain.
const puppeteer = createRequire(process.env.HYPERFRAMES_CLI)('puppeteer-core');
const input = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const directory = await fs.realpath(input.project);
const lock = JSON.parse(await fs.readFile(path.join(directory,'appearance-lock.json'),'utf8'));
let components;
try { components = JSON.parse(await fs.readFile(path.join(directory,'COMPONENT_LOCK.json'),'utf8')).components; }
catch (error) { if (error.code !== 'ENOENT') throw error; }
// HarnessFigures validates anchors against the original image dimensions.
const characterDirectories = [...(lock.assets || []), ...(components || [])]
  .filter(asset => (asset.kind || asset.asset_kind) === 'character')
  .map(asset => path.join(directory, asset.vendor_path) + path.sep);

// Read only the dimensions of PNG and WebP textures. Other image formats
// use their original response so their metadata and load behavior are preserved.
function imageDimensions(header) {
  if (header.length >= 24 && header.subarray(0, 8).equals(pngSignature) &&
      header.toString('ascii', 12, 16) === 'IHDR') {
    return [header.readUInt32BE(16), header.readUInt32BE(20)];
  }
  if (header.length < 30 || header.toString('ascii', 0, 4) !== 'RIFF' || header.toString('ascii', 8, 12) !== 'WEBP') return;
  switch (header.toString('ascii', 12, 16)) {
    case 'VP8X': return [1 + header.readUIntLE(24, 3), 1 + header.readUIntLE(27, 3)];
    case 'VP8L': {
      if (header[20] !== 0x2f) return;
      const dimensions = header.readUInt32LE(21);
      return [1 + (dimensions & 0x3fff), 1 + ((dimensions >>> 14) & 0x3fff)];
    }
    case 'VP8 ': {
      if (header.readUIntLE(23, 3) !== 0x2a019d) return;
      return [header.readUInt16LE(26) & 0x3fff, header.readUInt16LE(28) & 0x3fff];
    }
  }
}

const pngSignature = Buffer.from('89504e470d0a1a0a', 'hex');
const imagePlaceholders = new Map();
function pngChunk(type, data) {
  const chunk = Buffer.alloc(12 + data.length);
  chunk.writeUInt32BE(data.length);
  chunk.write(type, 4);
  data.copy(chunk, 8);
  chunk.writeUInt32BE(crc32(chunk.subarray(4, -4)), chunk.length - 4);
  return chunk;
}

// Preserve intrinsic dimensions and give the browser a cheap, solid 1-bit PNG.
async function imagePlaceholder(handle) {
  const header = Buffer.alloc(30);
  const {bytesRead} = await handle.read(header, 0, header.length, 0);
  const dimensions = imageDimensions(header.subarray(0, bytesRead));
  if (!dimensions || dimensions.some(size => size < 1 || size > 16384)) return;
  const [width, height] = dimensions;
  const key = width + 'x' + height;
  if (!imagePlaceholders.has(key)) {
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(width);
    ihdr.writeUInt32BE(height, 4);
    ihdr[8] = 1;
    const pixels = Buffer.alloc((1 + Math.ceil(width / 8)) * height);
    imagePlaceholders.set(key, Buffer.concat([pngSignature, pngChunk('IHDR', ihdr),
      pngChunk('IDAT', deflateSync(pixels)), pngChunk('IEND', Buffer.alloc(0))]));
  }
  return imagePlaceholders.get(key);
}

// A short WebM with black VP8 video and silent Opus audio.
const mediaPlaceholder = Buffer.from([
  'GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQRChYECGFOAZwH/////////EU2bdKtNu4tTq4QVSalmU6yBoU27i1Or',
  'hBZUrmtTrIG7TbuMU6uEElTDZ1OsggFn7AEAAAAAAABoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVSalmlSrX',
  'sYMPQkBNgIRMYXZmV0GETGF2ZhZUrmtApq4BAAAAAAAAONeBAXPFiAAAAAAAAAABnIEAIrWcg3VuZIiBAIaFVl9WUDiDgQEj',
  '44OEBfXhAOCJsIECuoECmoECrgEAAAAAAABc14ECc8WIAAAAAAAAAAKcgQAitZyDdW5kiIEAhoZBX09QVVNWqoNjLqBWu4QE',
  'xLQAg4EC4ZGfgQG1iEDncAAAAAAAYmSBEGOik09wdXNIZWFkAQE4AYC7AAAAAAASVMNn2XNzqWPAi2PFiAAAAAAAAAABZ8iY',
  'RaOHRU5DT0RFUkSHi0xhdmMgbGlidnB4c3OqY8CLY8WIAAAAAAAAAAJnyJlFo4dFTkNPREVSRIeMTGF2YyBsaWJvcHVzH0O2',
  'debngQCjh4IAAID4//6jooEAB4AQAgCdASoCAAIAC8cIhYWIhYSIP4IADA1gAP7mtQCjh4IAFYD4//6jh4IAKYD4//6jh4IA',
  'PYD4//6jh4IAUYD4//6gkKGHggBlAPj//nWihADN/mA=',
].join(''), 'base64');
const browser = await puppeteer.launch({executablePath: process.env.HYPERFRAMES_BROWSER_PATH || process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: process.platform === 'linux' ? ['--no-sandbox'] : []});
const errors = [], items = new Map(), domTexts = [];
try {
  const page = await browser.newPage();
  await page.setViewport({width: input.width || 1920, height: input.height || 1080});
  await page.evaluateOnNewDocument(() => {
    window.__hfCanvasTexts = new Map();
    for (const Context of [window.CanvasRenderingContext2D, window.OffscreenCanvasRenderingContext2D]) {
      if (!Context) continue;
      for (const name of ['fillText', 'strokeText']) {
        const draw = Context.prototype[name];
        Context.prototype[name] = function (text, ...args) {
          const value = {text:String(text), font:this.font};
          window.__hfCanvasTexts.set(JSON.stringify(value), value);
          return draw.call(this, text, ...args);
        };
      }
    }
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      const url = new URL(request.url());
      if (url.protocol === 'data:') return await request.continue(); // in-page data, never intercepted
      if (url.origin !== 'http://source.test') throw new Error('External source request');
      if (url.pathname === '/favicon.ico') return await request.abort(); // Chromium's own tab icon, not page content
      const source = path.join(directory, decodeURIComponent(url.pathname));
      const file = await fs.realpath(source);
      if (!file.startsWith(directory + path.sep)) throw new Error('Source path escaped snapshot');
      const resourceType = request.resourceType();
      const characterImage = resourceType === 'image' && characterDirectories.some(prefix => source.startsWith(prefix) || file.startsWith(prefix));
      if ((resourceType === 'image' && !characterImage) || resourceType === 'media') {
        // Require an existing, readable file in the closure without reading its payload.
        if (!(await fs.stat(file)).isFile()) throw new Error('Source is not a file: ' + url.pathname);
        const image = resourceType === 'image';
        const handle = await fs.open(file, 'r');
        let body;
        try { body = image ? await imagePlaceholder(handle) : mediaPlaceholder; }
        finally { await handle.close(); }
        if (body) return await request.respond({status: 200, body,
          contentType: image ? 'image/png' : 'video/webm'});
      }
      const types = {'.js':'text/javascript', '.mjs':'text/javascript', '.json':'application/json', '.html':'text/html', '.css':'text/css', '.woff':'font/woff', '.woff2':'font/woff2', '.ttf':'font/ttf', '.otf':'font/otf'};
      await request.respond({status: 200, body: await fs.readFile(file), contentType: (types[path.extname(file)] || 'application/octet-stream') + (['.html','.js','.mjs','.css','.json'].includes(path.extname(file)) ? '; charset=utf-8' : '')});
    } catch (error) { errors.push(error.message); await request.abort(); }
  });
  await page.goto('http://source.test/index.html', {waitUntil:'domcontentloaded'});
  // Keep load handlers and initial font work ahead of the first seek.
  await page.evaluate(async () => {
    if (document.readyState !== 'complete') await new Promise(resolve => window.addEventListener('load', resolve, {once:true}));
    await document.fonts.ready;
  });
  await page.waitForNetworkIdle();
  for (const scene of input.scenes) for (const time of [scene.start, scene.start + scene.duration / 2, scene.start + scene.duration - .001]) {
    await page.evaluate(async time => {
      await window.__example?.ready;
      const pending = [];
      for (const timeline of Object.values(window.__timelines || {})) timeline.totalTime?.(time, true);
      window.dispatchEvent(new CustomEvent('hf-seek', {detail:{time, waitUntil: promise => pending.push(promise)}}));
      await Promise.all(pending); await document.fonts.ready;
    }, time);
    domTexts.push(...await page.evaluate(() => {
      const result=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
      while(walker.nextNode()) { const node=walker.currentNode, element=node.parentElement;
        if(node.textContent.trim() && element?.closest('[data-hf-layer="text"], [data-hf-layer="captions"]'))
          result.push({text:node.textContent, font_family:getComputedStyle(element).fontFamily});
      } return result;
    }));
    for (const frame of page.frames()) {
      const inventory = await frame.evaluate(() => {
        if(document.querySelector('canvas') && !window.__hfTextSources?.size) throw Error('Canvas module requires a registered texts() inventory, including an empty inventory for graphics only');
        return [...(window.__hfTextSources || [])].flatMap(source => source());
      });
      for (const item of inventory) {
        if (!item.scene) throw new Error('Module text requires a Scene identity');
        const key = JSON.stringify([item.scene, item.asset, item.id]);
        if (items.has(key) && JSON.stringify(items.get(key)) !== JSON.stringify(item)) throw new Error('Module text inventory changes across seeks');
        items.set(key, item);
      }
    }
  }
  if (page.frames().length > 1 && items.size) throw new Error('Nested module text time mapping is not verified');
  const values = [...items.values()];
  for (const item of values) for (const time of [item.start, (item.start + item.end) / 2, item.end - .001]) {
    await page.evaluate(async time => {
      const pending = [];
      for (const timeline of Object.values(window.__timelines || {})) timeline.totalTime?.(time, true);
      window.dispatchEvent(new CustomEvent('hf-seek', {detail:{time, waitUntil: promise => pending.push(promise)}}));
      await Promise.all(pending);
    }, time);
  }
  await page.evaluate(async values => {
    const probes = values.flatMap((item,index) => item.embedded ? [{index,text:item.text,family:item.font_family}] : []);
    for (const draw of window.__hfCanvasTexts.values()) {
      if (!draw.text.trim()) continue;
      const matches = values.flatMap((item,index) => item.embedded && item.text.normalize('NFC').includes(draw.text.normalize('NFC')) ? [index] : []);
      if (!matches.length) throw Error('Canvas text missing from texts() inventory: ' + draw.text);
      for (const index of matches) probes.push({...draw,index});
    }
    for (const probe of probes) for (const character of new Set(probe.text.normalize('NFC'))) {
      if (/[\p{Cc}\p{Cf}\p{Z}]/u.test(character)) continue;
      const node = document.createElement('span');
      node.dataset.hfFontProbe = String(probe.index); node.textContent = character;
      Object.assign(node.style, {position:'fixed', top:'0', left:'0', opacity:'0'});
      if (probe.font) node.style.font = probe.font;
      else Object.assign(node.style,{fontSize:'32px',fontFamily:probe.family || ''});
      document.body.append(node);
    }
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, values);
  const cdp = await page.createCDPSession();
  await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
  const {root} = await cdp.send('DOM.getDocument');
  const {nodeIds} = await cdp.send('DOM.querySelectorAll', {nodeId:root.nodeId, selector:'[data-hf-font-probe]'});
  for (const item of values) if (item.embedded) item.font_coverage = true;
  for (const nodeId of nodeIds) {
    const {node} = await cdp.send('DOM.describeNode', {nodeId});
    const index = Number(node.attributes[node.attributes.indexOf('data-hf-font-probe') + 1]);
    const {fonts} = await cdp.send('CSS.getPlatformFontsForNode', {nodeId});
    values[index].font_coverage &&= fonts.length > 0 && fonts.every(font => font.isCustomFont && font.glyphCount > 0);
  }
  await cdp.detach();
  let fonts = lock.card_fonts?.fonts;
  if (!fonts && lock.selection.theme) {
    const asset = lock.assets.find(asset => asset.ref === lock.selection.theme.ref);
    const metadata = JSON.parse(await fs.readFile(path.join(directory,asset.vendor_path,'asset.json'),'utf8'));
    const theme = JSON.parse(await fs.readFile(path.join(directory,asset.vendor_path,metadata.entry),'utf8'));
    fonts = (theme.fonts || []).map(font => ({...font,path:asset.vendor_path+'/'+font.path}));
  }
  let captionText = '';
  try {
    const cues=JSON.parse(await fs.readFile(path.join(directory,'runtime/cues.json'),'utf8'));
    const visit=value=>{ if(Array.isArray(value)) value.forEach(visit); else if(value && typeof value==='object') { if(typeof value.char==='string') captionText+=value.char; Object.values(value).forEach(visit); } }; visit(cues);
  } catch(error) { if(error.code!=='ENOENT') throw error; }
  const domCharacters=actualCharacters(domTexts.map(item=>item.text).join('')+captionText);
  const characters = actualCharacters(values.filter(item=>item.embedded).map(item=>item.text).join('')+(lock.card_fonts?[...domCharacters].join(''):''));
  const covered = new Set();
  for (const font of fonts || []) {
    const file = await fs.realpath(path.join(directory,font.path));
    if (!file.startsWith(directory+path.sep)) throw Error('Font escaped closure');
    for (const char of coveredCharacters(await fs.readFile(file), characters)) covered.add(char);
  }
  for (const item of values) if (item.embedded) item.font_coverage &&= [...actualCharacters(item.text)].every(char=>covered.has(char));
  if (errors.length) throw new Error(errors.join('; '));
  const dom_fonts = lock.card_fonts ? {coverage:[...domCharacters].every(char=>covered.has(char)) && domTexts.every(item=>item.font_family.includes('HarnessFont_')), missing:[...domCharacters].filter(char=>!covered.has(char))} : null;
  process.stdout.write(JSON.stringify({schema_version:1, complete:true, items:values, dom_fonts}));
} finally { await browser.close(); }
