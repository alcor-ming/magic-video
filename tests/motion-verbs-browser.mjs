// CHROME_PATH=/usr/bin/chromium node tests/motion-verbs-browser.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const {chromium} = createRequire(path.join(repo, '.studio/parser/package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox']});
try {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
  await page.setContent('<main style="position:relative;width:1920px;height:1080px">' +
    [0, 1, 2, 3, 4].map(i => `<div id="p${i}" style="position:absolute;left:${200 + i * 300}px;top:500px;width:160px;height:200px;background:#eee"></div>`).join('') + '</main>');
  await page.addScriptTag({path: path.join(repo, '.studio/runtime/motion.js')});
  await page.addScriptTag({path: path.join(repo, '.studio/designs/stage-full/assets/stage-motion/stage-motion.js')});

  const result = await page.evaluate(() => {
    const M = window.HarnessMotion, $ = id => document.getElementById(id);
    const nodes = [0, 1, 2, 3, 4].map(i => $('p' + i));
    // 同一段调用，分别用工具默认和 stage-full 卡片跑一遍。
    const script = (m, card) => {
      m.appear(nodes.slice(0, 3), {at: 0.5, stagger: {span: 0.3}});
      m.emphasize(nodes[1], {at: 2});
      m.moveTo(nodes[0], {at: 3, to: {x: 120, y: -40}});
      m.moveTo(nodes[0], {at: 4, to: {x: 240, y: 0}});
      m.settle(nodes[0], {at: 4.8});
      if (card) m.sortTo(nodes[2], {at: 3, to: {x: -100, y: 60}});
      m.transition({outgoing: nodes.slice(0, 3), incoming: nodes.slice(3)}, {at: 6});
    };
    const snap = t => nodes.map(n => [n.style.transform, n.style.opacity, n.style.visibility]);
    const times = [0, 0.6, 1.1, 2.3, 3.4, 4.5, 5.2, 6.5, 7.4, 9];
    const run = card => {
      const m = M.create(card ? {card} : {});
      script(m, card);
      const forward = times.map(t => { m.apply(t); return snap(t); });
      const backward = times.slice().reverse().map(t => { m.apply(t); return snap(t); }).reverse();
      m.apply(9.5);
      const end = nodes.map(n => n.style.visibility);
      m.apply(4.79); // 第二次 moveTo 已结束、settle 未开始：起点链接应落在 240
      const chained = nodes[0].style.transform;
      const sources = window.__hfRhythmSources.size;
      m.dispose();
      return {forward, backward, end, chained, sources, after: window.__hfRhythmSources.size,
        restored: nodes.map(n => n.style.transform + '|' + n.style.opacity)};
    };
    const tool = run(null), card = run('stage-full');

    const errors = {};
    const attempt = (name, fn) => { try { fn(); errors[name] = 'none'; } catch (error) { errors[name] = error.constructor.name + ': ' + error.message; } };
    attempt('overlapTool', () => { const m = M.create(); m.appear(nodes[0], {at: 1}); m.settle(nodes[0], {at: 1.2}); });
    attempt('overlapCard', () => { const m = M.create({card: 'stage-full'}); m.appear(nodes[0], {at: 1}); m.settle(nodes[0], {at: 1.3}); });
    attempt('missingTo', () => M.create().moveTo(nodes[0], {at: 1}));
    attempt('missingAt', () => M.create().appear(nodes[0], {}));
    attempt('unknownOption', () => M.create().appear(nodes[0], {at: 1, ease: 'back'}));
    attempt('cardOnlyOnTool', () => M.create().sortTo(nodes[0], {at: 1, to: {x: 1}}));
    attempt('badStagger', () => M.create().appear(nodes, {at: 1, duration: 1, stagger: {span: 2}}));
    attempt('cardAddsParam', () => M.registerCard('bad-a', {replace: {appear: {how: 'x', impl: () => ({}), params: {extra: 'number!'}}}}));
    attempt('cardRedefinesVerb', () => M.registerCard('bad-b', {extra: {appear: {name: 'a', intent: 'a', fits: 'a', how: 'a', durationDefault: 'quick', impl: () => ({})}}}));
    attempt('halfAddRollsBack', () => {
      const m = M.create(); m.settle(nodes[2], {at: 1});
      try { m.appear([nodes[1], nodes[2]], {at: 1}); } catch (error) { /* expected */ }
      m.appear(nodes[1], {at: 1}); m.dispose();
    });

    const sequential = (() => {
      const m = M.create({card: 'stage-full'});
      m.appear(nodes[4], {at: 1}); m.settle(nodes[4], {at: 1.6}); m.exit(nodes[4], {at: 3});
      m.apply(0.5); const before = nodes[4].style.visibility;
      m.apply(2.5); const standing = nodes[4].style.transform;
      m.apply(4); const after = nodes[4].style.visibility;
      m.dispose();
      return {before, standing, after};
    })();

    return {tool, card, errors, sequential, toolMenu: M.menu(null), cardMenu: M.menu('stage-full')};
  });

  for (const [name, run] of Object.entries({tool: result.tool, card: result.card})) {
    assert.deepEqual(run.forward, run.backward, name + ': apply(t) is a pure function of t');
    assert.deepEqual(run.end, ['hidden', 'hidden', 'hidden', 'visible', 'visible'], name + ': transition hands over');
    assert.match(run.chained, /translate\(240px, 0px\)/, name + ': second moveTo starts where the first ended');
    assert.equal(run.after, run.sources - 1, name + ': dispose unregisters the rhythm source');
    assert.deepEqual(run.restored, Array(5).fill('|'), name + ': dispose restores inline styles');
  }
  assert.notDeepEqual(result.tool.forward, result.card.forward, 'the card replaces how the verbs move');
  assert.equal(result.tool.forward[0][0][2], 'hidden', 'appear hides the element before its cue');
  assert.match(result.card.forward[1][0][0], /rotateX/, 'card appear stands up on the hinge');

  assert.equal(result.errors.halfAddRollsBack, 'none', 'a rejected call leaves no half binding');
  for (const [name, message] of Object.entries(result.errors)) {
    if (name !== 'halfAddRollsBack') assert.match(message, /^TypeError/, name + ': ' + message);
  }
  assert.match(result.errors.overlapCard, /both drive 'rx'/);

  assert.equal(result.sequential.before, 'hidden');
  assert.equal(result.sequential.standing, 'translate(0px, 0px)', 'settle ends upright with no residual tilt');
  assert.equal(result.sequential.after, 'hidden');

  assert.deepEqual(result.toolMenu.map(item => item.verb), ['appear', 'exit', 'emphasize', 'moveTo', 'settle', 'transition']);
  assert(result.toolMenu.every(item => item.source === 'tool'));
  assert.deepEqual(result.cardMenu.map(item => [item.verb, item.source]), [
    ['appear', 'card'], ['exit', 'card'], ['emphasize', 'card'], ['moveTo', 'card'], ['settle', 'card'], ['transition', 'card'], ['sortTo', 'card-only']]);
  assert.deepEqual(result.cardMenu.find(item => item.verb === 'moveTo').required, ['at', 'to'], 'replacement keeps the tool parameters');

  // 卡片给 AI 的唯一清单与运行时合并结果一致。
  const guide = fs.readFileSync(path.join(repo, '.studio/designs/stage-full/MOTION.md'), 'utf8');
  const listed = [...guide.matchAll(/^\| `(\w+)` \|/gm)].map(match => match[1]);
  assert.deepEqual(listed, result.cardMenu.map(item => item.verb), 'MOTION.md lists exactly the merged verbs');
  for (const item of result.cardMenu) assert(guide.includes(item.how), 'MOTION.md describes ' + item.verb + ' as the runtime does');
  console.log('motion verbs browser checks passed');
} finally {
  await browser.close();
}
