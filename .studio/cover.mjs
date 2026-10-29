import path from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
if (!process.env.HYPERFRAMES_CLI) throw new Error('Runtime is not configured: HYPERFRAMES_CLI');
// The host ships only the runtime's puppeteer-core; .studio/parser is a development toolchain.
const puppeteer = createRequire(process.env.HYPERFRAMES_CLI)('puppeteer-core');
const [directory, width, height] = process.argv.slice(2);
const browser = await puppeteer.launch({headless:true, executablePath:process.env.CHROME_PATH || process.env.HYPERFRAMES_BROWSER_PATH,
  args:process.platform === 'linux' ? ['--no-sandbox'] : []});
try {
  const page = await browser.newPage();
  await page.setViewport({width:Number(width),height:Number(height),deviceScaleFactor:1});
  const allowed = value => {
    const url = new URL(value);
    return url.protocol === 'file:' && path.dirname(fileURLToPath(url)) === path.resolve(directory);
  };
  await page.setRequestInterception(true);
  page.on('request', request => allowed(request.url()) ? request.continue() : request.abort());
  await page.goto(pathToFileURL(path.join(directory,'index.html')).href);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode()));
    if (!document.fonts.check('16px Cover')) throw Error('Cover font missing');
    const heading = document.querySelector('h1'), logo = document.querySelector('.logo');
    const copy = document.querySelector('.copy'), character = document.querySelector('.character');
    const box = element => element.getBoundingClientRect();
    const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    const overflow = element => element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight;
    if (!copy) {
      if (box(heading).bottom >= box(logo).top) throw Error('Cover title overlaps Logo');
      if (overflow(heading)) throw Error(`Cover title overflow: ${heading.scrollWidth}x${heading.scrollHeight} in ${heading.clientWidth}x${heading.clientHeight}`);
    } else {
      if (overflow(copy)) throw Error(`Cover title and tagline overflow: ${copy.scrollWidth}x${copy.scrollHeight} in ${copy.clientWidth}x${copy.clientHeight}`);
      for (const text of copy.children) if (overflow(text)) throw Error('Cover text overflow: ' + text.className);
      if (meets(box(copy), box(character))) throw Error('Cover text overlaps the character');
      if (logo && [...copy.children].some(text => meets(box(text), box(logo)))) throw Error('Cover text overlaps Logo');
    }
  });
  await page.screenshot({path:path.join(directory,'cover.png')});
} finally { await browser.close(); }
