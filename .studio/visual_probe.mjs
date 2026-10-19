import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

export const defaults = {step: 0.5, width: 960, timeout_ms: 5000};

export function inspectCarry() {
  const result = [];
  const visit = (doc, x = 0, y = 0, scaleX = 1, scaleY = 1) => {
    const win = doc.defaultView;
    const visible = element => {
      for (let node = element; node; node = node.parentElement) {
        const style = win.getComputedStyle(node);
        if (style.display === 'none' || style.visibility !== 'visible' || +style.opacity < .02) return false;
      }
      const box = element.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && box.right > 0 && box.bottom > 0 && box.x < win.innerWidth && box.y < win.innerHeight;
    };
    for (const element of doc.querySelectorAll('[data-hf-carry]')) {
      if (!visible(element)) continue;
      const box = element.getBoundingClientRect();
      result.push({id: element.dataset.hfCarry, box: [x + box.x * scaleX, y + box.y * scaleY, box.width * scaleX, box.height * scaleY]});
    }
    for (const frame of doc.querySelectorAll('iframe')) {
      if (!visible(frame) || !frame.contentDocument) continue;
      const box = frame.getBoundingClientRect();
      visit(frame.contentDocument, x + box.x * scaleX, y + box.y * scaleY,
        scaleX * box.width / frame.clientWidth, scaleY * box.height / frame.clientHeight);
    }
  };
  visit(document);
  const root = document.querySelector('[data-width][data-height]');
  const box = root?.getBoundingClientRect();
  if (box?.width && box.height) for (const item of result) {
    item.box = [(item.box[0] - box.x) * +root.dataset.width / box.width,
      (item.box[1] - box.y) * +root.dataset.height / box.height,
      item.box[2] * +root.dataset.width / box.width, item.box[3] * +root.dataset.height / box.height];
  }
  return result;
}

export async function layerPixels(page, frame, screenshot) {
  const styles = [];
  const excluded = '[data-hf-layer="background"], [data-hf-layer="captions"], [data-hf-ambient], [data-hf-motion="idle"], [data-hf-motion="talk"]';
  const hide = async target => {
    styles.push(await target.addStyleTag({content: excluded.split(',').flatMap(selector => [selector, selector.trim() + ' *']).join(',') + '{visibility:hidden!important}'}));
    for (const child of target.childFrames()) await hide(child);
  };
  try {
    await hide(frame);
    const bytes = await screenshot();
    return await page.evaluate(async base64 => {
      const image = new Image(); image.src = 'data:image/png;base64,' + base64; await image.decode();
      const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
      const context = canvas.getContext('2d', {willReadFrequently: true});
      context.drawImage(image, 0, 0);
      return Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data);
    }, Buffer.from(bytes).toString('base64'));
  } finally {
    for (const style of styles.reverse()) await style.evaluate(element => element.remove()).catch(() => {});
  }
}

// Helper intent is only a candidate: the Python report also requires a visible state change.
export function inspectRhythmFrame() {
  const observed = element => {
    const win = element.ownerDocument.defaultView, rect = element.getBoundingClientRect();
    const style = win.getComputedStyle(element);
    const stroke = element instanceof win.SVGGeometryElement && style.stroke !== 'none' ? parseFloat(style.strokeWidth) || 0 : 0;
    let visible = element.isConnected && rect.width + stroke > 0 && rect.height + stroke > 0 && rect.right + stroke > 0 && rect.bottom + stroke > 0 &&
      rect.left < win.innerWidth && rect.top < win.innerHeight;
    for (let parent = element; parent; parent = parent.parentElement) {
      const style = win.getComputedStyle(parent);
      if (style.display === 'none' || style.visibility !== 'visible' || +style.opacity < 0.02 ||
          [...style.filter.matchAll(/blur\(([\d.]+)px\)/g)].some(match => +match[1] > 0)) visible = false;
    }
    const points = [.2, .5, .8].flatMap(x => [.2, .5, .8].map(y => ({x: rect.left + rect.width * x, y: rect.top + rect.height * y})));
    if (element instanceof win.SVGGeometryElement && element.getScreenCTM()) {
      const length = element.getTotalLength();
      for (const fraction of length > 0 ? [.2, .5, .8] : []) {
        const point = element.getPointAtLength(length * fraction);
        points.push(new win.DOMPoint(point.x, point.y).matrixTransform(element.getScreenCTM()));
      }
    }
    visible &&= points.some(point => {
      const top = element.ownerDocument.elementsFromPoint(point.x, point.y)[0];
      return top && (top === element || top === element.getRootNode().host || element.contains(top) ||
        win.getComputedStyle(element).pointerEvents === 'none' && top.contains(element));
    });
    if (win.frameElement) visible &&= observed(win.frameElement).visible;
    const transparent = color => color === 'transparent' || /rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(color);
    const painted = node => {
      const css = win.getComputedStyle(node);
      if (node instanceof win.SVGElement) {
        if (node.closest('defs,clipPath,mask,pattern,symbol') || css.display === 'none' || css.visibility !== 'visible' || +css.opacity < .02) return false;
        if (!/^(path|line|polyline|polygon|rect|circle|ellipse|text|tspan|use|image)$/.test(node.localName)) return false;
        return node.localName === 'image' || node.localName !== 'line' && css.fill !== 'none' && !transparent(css.fill) && +css.fillOpacity >= .02 ||
          css.stroke !== 'none' && !transparent(css.stroke) && +css.strokeOpacity >= .02 && parseFloat(css.strokeWidth) > 0;
      }
      return /^(IMG|CANVAS|VIDEO|IFRAME|OBJECT|INPUT|BUTTON)$/.test(node.tagName.toUpperCase()) ||
        [...node.childNodes].some(child => child.nodeType === 3 && child.textContent.trim()) ||
        !transparent(css.backgroundColor) || css.backgroundImage !== 'none' || css.boxShadow !== 'none' ||
        ['Top', 'Right', 'Bottom', 'Left'].some(side => parseFloat(css['border' + side + 'Width']) > 0 &&
          !transparent(css['border' + side + 'Color']));
    };
    visible &&= [element, ...element.querySelectorAll('*')].some(painted);
    const images = [...element.querySelectorAll('img')];
    if (element.tagName === 'IMG') images.push(element);
    return {visible, geometry: [rect.x, rect.y, rect.width, rect.height],
      state_signature: JSON.stringify(images.map(image => image.currentSrc || image.src)),
      signature: JSON.stringify([style.visibility, style.filter, Math.round(+style.opacity * 50),
        ...[rect.x, rect.y, rect.width, rect.height].map(value => Math.round(value * 2)),
        [...new win.DOMMatrix(style.transform === 'none' ? undefined : style.transform).toFloat64Array()]
          .map(value => Math.round(value * 100) / 100),
        style.color, style.backgroundColor, style.borderColor, style.fill, style.stroke,
        style.clipPath, style.boxShadow, style.outlineColor, style.outlineWidth, style.outlineStyle,
        style.fillOpacity, style.strokeOpacity, style.strokeWidth, style.strokeDasharray, style.strokeDashoffset,
        element instanceof win.SVGElement ? ['d', 'points', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry']
          .map(name => element.getAttribute(name)) : null,
        element.textContent, images.map(image => image.currentSrc || image.src)])};
  };
  const candidates = [];
  const claimed = new Map();
  const registered = new Map();
  const add = (event, id) => {
    const target = event.target;
    if (!target?.ownerDocument || target.closest('[data-hf-ambient], [data-hf-motion="idle"], [data-hf-motion="talk"]')) return;
    const host = target.ownerDocument.defaultView.frameElement;
    const layer = target.closest('[data-hf-layer]')?.dataset.hfLayer || host?.closest('[data-hf-layer]')?.dataset.hfLayer;
    if (!['stage', 'overlay', 'text'].includes(layer)) return;
    const targets = [];
    const address = [];
    for (let el = target; el?.parentElement; el = el.parentElement)
      address.unshift([...el.parentElement.children].indexOf(el));
    const frames = [];
    for (let frame = target.ownerDocument.defaultView.frameElement; frame;
      frame = frame.ownerDocument.defaultView.frameElement) {
      frames.unshift([...frame.ownerDocument.querySelectorAll('iframe,frame')].indexOf(frame));
    }
    const frameKey = frames.join('/') || 'host';
    for (let el = target; el; el = el.parentElement || el.ownerDocument.defaultView.frameElement) {
      for (const key of ['id', 'data-info-id', 'data-b-id', 'data-hf-math-id']) {
        const value = el.getAttribute(key);
        if (value) targets.push(value);
      }
    }
    candidates.push({id: `${location.href}#${frameKey}:${id}`, time: event.time, before: event.before, after: event.after,
      duration: event.duration, kind: event.kind, targets: [...new Set(targets)], target_node: `${frameKey}:${address.join('.')}`,
      unverified: event.unverified,
      scene: event.scene || target.closest('[data-scene-id]')?.dataset.sceneId || null, layer, ...observed(target)});
  };
  let sourceIndex = 0;
  for (const source of window.__hfRhythmSources || []) {
    const index = sourceIndex++;
    source().forEach((event, i) => {
      const times = claimed.get(event.target) || new Set();
      const kinds = registered.get(event.target) || new Set(), key = `${event.time}:${event.kind}`;
      if (kinds.has(key)) return;
      kinds.add(key); registered.set(event.target, kinds);
      times.add(event.time); claimed.set(event.target, times);
      add(event, `helper:${index}:${i}`);
    });
  }
  const root = document.querySelector('[data-composition-id]');
  const timeline = window.__timelines?.[root?.dataset.compositionId];
  if (timeline?.getChildren) {
    const origin = timeline.globalTime(0), scale = timeline.globalTime(1) - origin;
    timeline.getChildren(true, true, false).forEach((tween, i) => {
      const time = (tween.globalTime(0) - origin) / scale;
      const duration = Math.abs((tween.globalTime(tween.totalDuration()) - tween.globalTime(0)) / scale);
      if (!Number.isFinite(time) || !Number.isFinite(duration)) return;
      for (const [j, target] of (tween.targets?.() || []).entries()) {
        if (!target?.ownerDocument || [...claimed.get(target) || []].some(at => Math.abs(at - time) < .00001)) continue;
        const properties = Object.keys(tween.vars).filter(key => !['duration', 'delay', 'ease', 'parent',
          'overwrite', 'immediateRender', 'lazy', 'repeat', 'repeatDelay', 'yoyo', 'onComplete', 'onUpdate', 'data'].includes(key));
        if (!properties.length) continue;
        const camera = target.closest('[data-hf-camera]') || ['pan', 'zoom', 'camera'].includes(target.dataset.hfMotion) ||
          duration >= 2 && properties.every(key => ['x', 'y', 'xPercent', 'yPercent', 'scale', 'scaleX', 'scaleY'].includes(key));
        if (tween.repeat() < 0 || tween.repeat() >= 1000) {
          add({target, time, duration: 0, kind: 'tween', unverified: 'unbounded_repeated_motion'}, `tween:${i}:${j}`);
          continue;
        }
        const firstDuration = camera ? Math.abs((tween.globalTime(tween.duration()) - tween.globalTime(0)) / scale) : duration;
        add({target, time, duration: firstDuration, kind: camera ? 'camera_start' : duration ? 'tween' : 'set'}, `tween:${i}:${j}`);
        if (camera && tween.yoyo() && tween.repeat() > 0 && tween.repeat() < 1000) {
          for (let cycle = 1; cycle <= tween.repeat(); cycle++) {
            const local = cycle * (tween.duration() + tween.repeatDelay());
            const turn = (tween.globalTime(local) - origin) / scale;
            add({target, time: turn, duration: firstDuration, kind: 'camera_turn'}, `tween:${i}:${j}:turn:${cycle}`);
          }
        }
        if (camera && duration) add({target, time: time + duration, duration: 0,
          before: time + duration - firstDuration / 2, kind: 'camera_end'}, `tween:${i}:${j}:end`);
        if (!camera && duration) add({target, time: time + duration, duration: 0,
          before: time + duration / 2, kind: 'tween_end'}, `tween:${i}:${j}:end`);
      }
    });
  }
  return candidates;
}

export function frameResourcesReady(time) {
  if (document.readyState !== 'complete' || document.fonts.status !== 'loaded') return false;
  return [...document.images].every(image => image.complete && image.naturalWidth > 0) &&
    [...document.querySelectorAll('video,audio')].every(media => {
      const start = Number.parseFloat(media.dataset.start ?? '0');
      if (!Number.isFinite(start) || !media.hasAttribute('data-start')) return false;
      // Match the pinned runtime's media clip mapping, including trimmed loops.
      const offset = value => value != null && value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0
        ? Number(value) : null;
      const mediaStart = offset(media.dataset.playbackStart) ?? offset(media.dataset.mediaStart) ?? 0;
      const declaredRate = Number.parseFloat(media.dataset.playbackRate ?? '');
      const baseRate = Number.isFinite(declaredRate) && declaredRate > 0 ? declaredRate : media.defaultPlaybackRate;
      const rate = Number.isFinite(baseRate) && baseRate > 0 ? Math.max(0.1, Math.min(5, baseRate)) : 1;
      const sourceDuration = Number.isFinite(media.duration) && media.duration > 0 ? media.duration : null;
      let duration = Number.parseFloat(media.dataset.duration ?? '');
      if (!Number.isFinite(duration) || duration < 0)
        duration = sourceDuration == null ? Infinity : Math.max(0, (sourceDuration - mediaStart) / rate);
      if (time < start || time >= start + duration) return true;
      let expected = (time - start) * rate + mediaStart;
      if (sourceDuration != null && expected >= sourceDuration) {
        if (media.loop && sourceDuration > mediaStart)
          expected = mediaStart + (expected - mediaStart) % (sourceDuration - mediaStart);
        else if (!media.loop && media.tagName === 'VIDEO') expected = sourceDuration;
      }
      return !media.error && media.readyState >= 2 && !media.seeking && Math.abs(media.currentTime - expected) < 0.08;
    });
}

export async function inspectFrame(scenes, time) {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height || rect.bottom <= 0 || rect.right <= 0 ||
        rect.top >= innerHeight || rect.left >= innerWidth) return false;
    for (let parent = element; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility !== 'visible' || +style.opacity < 0.02) return false;
      if ([...style.filter.matchAll(/blur\(([\d.]+)px\)/g)].some(match => +match[1] > 0)) return false;
    }
    return true;
  };
  const selector = element => {
    const parts = [];
    while (element && element !== document.documentElement) {
      if (element.id) { parts.unshift('#' + CSS.escape(element.id)); break; }
      const siblings = [...element.parentElement?.children || []].filter(item => item.tagName === element.tagName);
      parts.unshift(element.localName + ':nth-of-type(' + (siblings.indexOf(element) + 1) + ')');
      element = element.parentElement;
    }
    return parts.join(' > ');
  };
  const texts = [], unverified = new Set();
  const transparent = color => color === 'transparent' || /rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(color);
  const painted = element => {
    const style = getComputedStyle(element);
    // Hit testing includes empty transparent full-frame layers, unlike actual paint.
    return element instanceof SVGElement || /^(IMG|VIDEO|CANVAS|IFRAME|OBJECT|INPUT|BUTTON)$/.test(element.tagName) ||
      [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()) ||
      !transparent(style.backgroundColor) || style.backgroundImage !== 'none' || style.boxShadow !== 'none' ||
      style.backdropFilter && style.backdropFilter !== 'none' ||
      ['Top', 'Right', 'Bottom', 'Left'].some(side => parseFloat(style['border' + side + 'Width']) > 0 &&
        !transparent(style['border' + side + 'Color']));
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, element = node.parentElement;
    if (!node.textContent.trim() || !element || element.closest('script,style,noscript') || !visible(element)) continue;
    const style = getComputedStyle(element);
    if (element instanceof SVGElement ? (style.fill === 'none' || transparent(style.fill) || +style.fillOpacity === 0) &&
      (style.stroke === 'none' || transparent(style.stroke) || +style.strokeOpacity === 0)
      : transparent(style.webkitTextFillColor || style.color)) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()];
    const exposed = rects.some(rect => {
      if (!rect.width || !rect.height) return false;
      return [0.2, 0.5, 0.8].some(fraction => {
        const top = document.elementsFromPoint(rect.left + rect.width * fraction, rect.top + rect.height / 2)
          .find(candidate => visible(candidate) && (candidate === element || candidate.contains(element) || painted(candidate)));
        return top && (top === element || element.contains(top) ||
          getComputedStyle(element).pointerEvents === 'none' && top.contains(element));
      });
    });
    if (!exposed) continue;
    const info = element.closest('[data-info-id]')?.getAttribute('data-info-id') || null;
    const owner = element.closest('[data-scene-id]') || element.closest('[id]');
    let scene = owner?.getAttribute('data-scene-id');
    if (!scene) {
      let parent = element;
      while (parent) {
        if (scenes.some(item => item.id === parent.id)) { scene = parent.id; break; }
        parent = parent.parentElement;
      }
    }
    if (!scene) {
      const active = scenes.filter(item => time >= item.start && time < item.start + item.duration);
      if (active.length === 1) scene = active[0].id;
    }
    texts.push({scene: scene || null, info, text: node.textContent.trim(),
      selector: selector(element), frame: location.href,
      layer: element.closest('[data-hf-layer]')?.getAttribute('data-hf-layer') || null});
  }
  for (const element of document.querySelectorAll('*')) {
    if (!visible(element)) continue;
    if (element.shadowRoot) unverified.add('shadow DOM text is not extracted');
    if (['CANVAS', 'IMG', 'VIDEO'].includes(element.tagName)) unverified.add('canvas/image/video text is not OCR verified');
    if (['::before', '::after'].some(pseudo => !['none', 'normal', '""'].includes(getComputedStyle(element, pseudo).content)))
      unverified.add('pseudo-element text is not extracted');
  }
  const timeline = [];
  for (const [id, track] of Object.entries(window.__timelines || {})) {
    if (typeof track.getChildren !== 'function') continue;
    for (const tween of track.getChildren(true, true, false)) {
      const targets = tween.targets?.() || [];
      timeline.push({id, start: tween.globalTime?.(0) ?? tween.startTime(), duration: tween.totalDuration(),
        properties: Object.keys(tween.vars || {}).filter(key => !['duration', 'delay', 'ease', 'parent', 'overwrite'].includes(key)),
        targets: targets.map(target => target instanceof Element
          ? {selector: selector(target), visible: visible(target)} : {non_dom: true}),
        clue: targets.length && targets.every(target => !(target instanceof Element)) ? 'non-DOM/possibly empty tween; not a verdict' : null});
    }
  }
  const exposedIcon = element => {
    if (!visible(element)) return false;
    const rect = element.getBoundingClientRect();
    return [.2, .5, .8].some(x => [.2, .5, .8].some(y => {
      const top = document.elementFromPoint(rect.left + rect.width * x, rect.top + rect.height * y);
      return top && (top === element || element.contains(top) ||
        getComputedStyle(element).pointerEvents === 'none' && top.contains(element));
    }));
  };
  const icons = [...document.querySelectorAll('svg')].filter(exposedIcon).map(element => {
    const rect = element.getBoundingClientRect();
    return {svg: element.outerHTML, width: rect.width, height: rect.height, target: selector(element),
      schematic: !!element.closest('[data-hf-schematic]')};
  });
  for (const element of [...document.images].filter(exposedIcon)) {
    try {
      const url = new URL(element.currentSrc || element.src, document.baseURI);
      const inlineSvg = /^data:image\/svg\+xml(?:[;,])/i.test(url.href);
      if (!inlineSvg && !url.pathname.toLowerCase().endsWith('.svg')) continue;
      if (!inlineSvg && (!['http:', 'https:'].includes(url.protocol) || url.origin !== location.origin))
        throw new Error('SVG resource is not same-origin');
      const response = await fetch(url.href, {redirect: 'error'});
      if (!response.ok) throw new Error('SVG resource unavailable');
      const svg = await response.text();
      const documentSvg = new DOMParser().parseFromString(svg, 'image/svg+xml');
      if (documentSvg.querySelector('parsererror') || documentSvg.documentElement.localName !== 'svg' ||
          documentSvg.documentElement.namespaceURI !== 'http://www.w3.org/2000/svg')
        throw new Error('SVG resource is invalid');
      const rect = element.getBoundingClientRect();
      icons.push({svg, width: rect.width, height: rect.height, target: selector(element),
        schematic: !!element.closest('[data-hf-schematic]')});
    } catch { unverified.add('SVG image provenance could not be sampled: ' + selector(element)); }
  }
  const motion_unverified = [...document.querySelectorAll('canvas,video')].filter(visible)
    .filter(element => ['stage', 'overlay', 'text'].includes(element.closest('[data-hf-layer]')?.dataset.hfLayer))
    .map(element => ({reason: 'media_canvas_motion_unverified', target: selector(element), time}));
  const module_texts = [...(window.__hfTextSources || [])].flatMap(source => source());
  for (const item of module_texts) if (item.start <= time && time < item.end) texts.push(item);
  const stagePainted = [...document.querySelectorAll('[data-hf-layer="stage"] *')].filter(element => {
    if (!visible(element) || element.closest('[data-hf-ambient]')) return false;
    const rect = element.getBoundingClientRect();
    if (!(rect.width > 2 && rect.height > 2)) return false;
    // Transparent containers do not count: the element must paint pixels itself.
    if (['IMG', 'SVG', 'VIDEO', 'CANVAS', 'PICTURE'].includes(element.tagName.toUpperCase())) return true;
    const style = getComputedStyle(element);
    const alpha = color => { const match = /rgba?\(([^)]+)\)/.exec(color || ''); if (!match) return color && color !== 'transparent' ? 1 : 0; const parts = match[1].split(/[\s,\/]+/).map(Number); return parts.length > 3 ? parts[3] : 1; };
    if (alpha(style.backgroundColor) > 0 || style.backgroundImage !== 'none' || style.boxShadow !== 'none') return true;
    if (['Top', 'Right', 'Bottom', 'Left'].some(side => parseFloat(style['border' + side + 'Width']) > 0 && alpha(style['border' + side + 'Color']) > 0)) return true;
    return [...element.childNodes].some(node => node.nodeType === 3 && node.textContent.trim());
  });
  // Foreground coverage: share of a 64x36 grid over the composition whose cell centres fall inside a
  // painted stage element. Scenery marked data-hf-set (rig walls, floor) is background, not foreground.
  const frameBox = document.querySelector('[data-width][data-height]')?.getBoundingClientRect()
    || {x: 0, y: 0, width: innerWidth, height: innerHeight};
  const columns = 64, rows = 36, covered = new Set();
  for (const element of stagePainted) {
    if (element.closest('[data-hf-set]')) continue;
    const rect = element.getBoundingClientRect();
    const first = value => Math.max(0, Math.ceil(value - .5)), last = (value, size) => Math.min(size - 1, Math.floor(value - .5));
    const c0 = first((rect.left - frameBox.x) / frameBox.width * columns), c1 = last((rect.right - frameBox.x) / frameBox.width * columns, columns);
    const r0 = first((rect.top - frameBox.y) / frameBox.height * rows), r1 = last((rect.bottom - frameBox.y) / frameBox.height * rows, rows);
    for (let row = r0; row <= r1; row++) for (let column = c0; column <= c1; column++) covered.add(row * columns + column);
  }
  return {texts, module_texts, unverified: [...unverified], timeline, icons, motion_unverified,
    stage_visible: stagePainted.length,
    stage_coverage: frameBox.width > 0 && frameBox.height > 0 ? +(covered.size / (columns * rows)).toFixed(4) : null};
}

export async function probe(input) {
  const deadline = Date.now() + 25 * 60 * 1000;
  const parameters = {...defaults, ...input.parameters};
  if (input.fps !== undefined && (!Number.isFinite(input.fps) || input.fps <= 0)) throw new Error('Invalid frame rate');
  for (const key of Object.keys(defaults)) if (!Number.isFinite(parameters[key]) || parameters[key] <= 0)
    throw new Error('Invalid positive parameter: ' + key);
  if (parameters.width < 160 || parameters.width > 4096 || parameters.timeout_ms < 100 ||
      parameters.timeout_ms > 30000) throw new Error('Invalid sampling bounds');
  const url = new URL(input.url);
  if (!['http:', 'https:'].includes(url.protocol) || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
    throw new Error('Only an explicitly bound local Studio URL is allowed');
  const require = createRequire(input.cli), puppeteer = require('puppeteer-core');
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-visual-probe-'));
  await fs.mkdir(path.join(profile, 'Default'));
  await fs.writeFile(path.join(profile, 'Default/Preferences'), JSON.stringify({enable_do_not_track: true}));
  const result = {samples: [], timeline: [], unverified: ['Finite sampling does not cover text between sample times; motion semantics require viewing.'], viewport: {}, parameters};
  let browser;
  try {
    browser = await puppeteer.launch({executablePath: input.browser, userDataDir: profile, headless: true, protocolTimeout: 30000,
      args: ['--disable-dev-shm-usage', '--disable-background-networking', '--disable-component-update',
        '--no-first-run', ...(process.platform === 'linux' ? ['--no-sandbox'] : [])]});
    const page = await browser.newPage();
    await page.evaluateOnNewDocument(() => {
      window.addEventListener('message', event => {
        const player = document.querySelector('hyperframes-player'), value = event.data;
        if (event.source !== player?.iframeElement?.contentWindow || value?.source !== 'hf-preview') return;
        const fps = value.fps?.numerator / value.fps?.denominator;
        if (Number.isFinite(fps) && fps > 0) window.__hfProbeFps = fps;
      });
    });
    page.on('pageerror', error => result.unverified.push('Page error: ' + error.message));
    let navigation = 0;
    page.on('framenavigated', () => { navigation++; });
    await page.setViewport({width: Math.max(1280, Math.ceil(parameters.width + 64)), height: 1080, deviceScaleFactor: 1});
    await page.setRequestInterception(true);
    page.on('request', request => {
      const target = new URL(request.url());
      if (['http:', 'https:', 'ws:', 'wss:'].includes(target.protocol) && target.origin !== url.origin) {
        result.unverified.push('Blocked non-Studio resource: ' + target.origin);
        void request.abort();
      } else void request.continue();
    });
    await page.goto(url.href, {waitUntil: 'domcontentloaded', timeout: 30000});
    await page.waitForFunction(() => document.querySelector('hyperframes-player')?.ready, {timeout: 30000});
    const size = await page.evaluate(width => {
      const player = document.querySelector('hyperframes-player'), frame = player.iframeElement;
      const root = frame.contentDocument.querySelector('[data-width][data-height]');
      if (!root) throw new Error('Cannot confirm composition dimensions');
      const height = Math.round(width * Number(root.dataset.height) / Number(root.dataset.width));
      player.pause(); player.removeAttribute('controls');
      player.style.cssText += `;position:fixed;left:0;top:0;width:${width}px;height:${height}px;max-width:none;max-height:none;z-index:2147483647;`;
      // Studio panels can overlay an iframe screenshot through ancestor stacking contexts.
      for (let child = player, parent = player.parentElement; parent; child = parent, parent = parent.parentElement) {
        for (const sibling of parent.children) if (sibling !== child)
          sibling.style.setProperty('visibility', 'hidden', 'important');
        for (const [key, value] of Object.entries({transform: 'none', overflow: 'visible', contain: 'none', filter: 'none'}))
          parent.style.setProperty(key, value, 'important');
      }
      return {width, height};
    }, Math.round(parameters.width));
    await page.setViewport({width: Math.max(1280, size.width + 64), height: Math.max(1080, size.height + 64), deviceScaleFactor: 1});
    await page.mouse.move(size.width + 32, size.height + 32);
    const iframe = (await page.evaluateHandle(() => document.querySelector('hyperframes-player').iframeElement)).asElement();
    const frame = await iframe.contentFrame();
    result.viewport = {...size};
    const duration = await page.evaluate(() => document.querySelector('hyperframes-player').duration);
    if (!Number.isFinite(duration) || duration <= 0) throw new Error('Invalid Studio duration');
    const last = Math.max(0, duration - 0.001);
    const span = Array.isArray(input.range) ? [Math.min(last, Math.max(0, +input.range[0])), Math.min(last, Math.max(0, +input.range[1]))] : [0, last];
    if (!span.every(Number.isFinite) || span[1] < span[0]) throw new Error('Invalid sampling range');
    const inSpan = time => time >= span[0] - 1e-6 && time <= span[1] + 1e-6;
    const explicit = Array.isArray(input.times) ? input.times.map(Number).filter(time => Number.isFinite(time) && time >= 0) : null;
    if ((span[1] - span[0]) / parameters.step > 2000) throw new Error('Sampling budget exceeded; increase step (maximum 2000 baseline samples)');
    const samples = new Map();
    let previousPixels = null;
    const settle = async (time, remaining) => {
      await page.waitForFunction(() => {
        const player = document.querySelector('hyperframes-player'), win = player?.iframeElement?.contentWindow;
        return player?.ready && win?.document.body && getComputedStyle(player.iframeElement).visibility === 'visible' &&
          (win.__player || Object.keys(win.__timelines || {}).length);
      }, remaining());
      await page.evaluate(time => document.querySelector('hyperframes-player').seek(time), time);
      await page.waitForFunction(time => {
        const player = document.querySelector('hyperframes-player');
        const win = player.iframeElement.contentWindow;
        const root = win.document.querySelector('[data-composition-id]');
        const timeline = win.__timelines?.[root?.dataset.compositionId];
        const actual = win.__player?.getTime?.() ?? timeline?.time?.();
        return player.ready && Math.abs(player.currentTime - time) < 0.04 &&
          typeof actual === 'number' && Math.abs(actual - time) < 0.04;
      }, remaining(), time);
      await frame.waitForFunction(frameResourcesReady, remaining(), time);
      await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };
    const sample = async (requested, measurePixels = false) => {
      if (Date.now() >= deadline) throw new Error('Diagnostic time budget exceeded; browser closed before outer command timeout');
      const time = Math.round(Math.min(duration - 0.001, Math.max(0, requested)) * 1e6) / 1e6;
      if (samples.has(time)) return samples.get(time);
      const value = {time, ready: false, texts: [], rhythm_candidates: [], icons: [], motion_unverified: [], unverified: []};
      if (samples.size >= 10000) throw new Error('Sampling budget exceeded (maximum 10000 samples)');
      samples.set(time, value);
      const sampleDeadline = Date.now() + parameters.timeout_ms;
      const remaining = () => ({timeout: Math.max(1, sampleDeadline - Date.now())});
      for (;;) {
        const before = navigation;
        try {
          await settle(time, remaining);
          value.actual_time = await frame.evaluate(() => {
            const root = document.querySelector('[data-composition-id]');
            return window.__player?.getTime?.() ?? window.__timelines?.[root?.dataset.compositionId]?.time?.();
          });
          const box = await iframe.boundingBox();
          if (!box || Math.abs(box.width - size.width) > 1 || Math.abs(box.height - size.height) > 1)
            throw new Error('Composition viewport is clipped or changed');
          if (!await page.evaluate(box => {
            const player = document.querySelector('hyperframes-player');
            return [[.02, .02], [.98, .02], [.02, .98], [.98, .98], [.5, .5]].every(([x, y]) =>
              document.elementFromPoint(box.x + box.width * x, box.y + box.height * y) === player);
          }, box)) throw new Error('Studio controls obscure the composition viewport');
          const info = await frame.evaluate(inspectFrame, input.scenes || [], time);
          const nestedFrames = frame.childFrames().length > 0;
          value.rhythm_candidates = await frame.evaluate(inspectRhythmFrame);
          for (const candidate of value.rhythm_candidates) {
            candidate.before = Math.min(duration - .001, Math.max(0, candidate.before ?? candidate.time - .001));
            candidate.after = Math.min(duration - .001, candidate.after ?? candidate.time + (candidate.duration / 2 || .001));
          }
          value.icons = info.icons;
          value.module_texts = info.module_texts;
          value.motion_unverified = info.motion_unverified;
          value.stage_visible = info.stage_visible;
          value.stage_coverage = info.stage_coverage;
          if (before !== navigation || !await iframe.evaluate(element => getComputedStyle(element).visibility === 'visible'))
            throw new Error('Studio frame reloaded during sampling');
          value.texts.push(...info.texts);
          value.unverified.push(...info.unverified);
          result.timeline.push(...info.timeline);
          value.ready = !nestedFrames;
          if (nestedFrames) value.unverified.push('Nested frame text/resources/time mapping is not verified');
          if (input.measurements) {
            value.carry = await frame.evaluate(inspectCarry);
            const shot = () => page.screenshot({type: 'png', clip: box});
            if (input.evidence_dir) {
              await fs.mkdir(input.evidence_dir, {recursive: true});
              value.screenshot = `frame-${String(Math.round(time * 1e6)).padStart(12, '0')}.png`;
              await fs.writeFile(path.join(input.evidence_dir, value.screenshot), await shot());
            }
            if (measurePixels && value.ready) {
              const pixels = await layerPixels(page, frame, shot);
              const prior = previousPixels;
              let delta = 0;
              if (prior?.pixels.length === pixels.length) {
                for (let i = 0; i < pixels.length; i++) delta += Math.abs(pixels[i] - prior.pixels[i]);
                value.still = {from: prior.time, mean_delta: delta / pixels.length, pixels: pixels.length / 4};
              }
              previousPixels = {time, pixels};
            } else if (measurePixels) previousPixels = null;
          }
        } catch (error) {
          if (before !== navigation && Date.now() < sampleDeadline) { value.retried_after_navigation = true; continue; }
          value.ready = false;
          if (measurePixels) previousPixels = null;
          value.unverified.push('Sample not verified: ' + error.message);
        }
        break;
      }
      return value;
    };
    const times = new Set(explicit || [span[0], span[1]]);
    if (!explicit) {
      for (let time = Math.ceil(span[0] / parameters.step - 1e-9) * parameters.step; time < span[1]; time += parameters.step)
        if (inSpan(time)) times.add(time);
      for (const scene of input.scenes || []) if (scene.start >= 0 && scene.start < duration && inSpan(scene.start)) times.add(scene.start);
    }
    for (const time of [...times].sort((a, b) => a - b)) await sample(time, !!input.measurements);
    if (explicit) result.unverified.push('Explicit sample times: boundary and helper samples skipped.');
    if (input.measurements && explicit && input.evidence_dir) {
      // Re-seek each explicit time through both ends of the film and compare pixels with the first capture.
      result.determinism = [];
      for (const time of [...times].sort((a, b) => a - b)) {
        const value = samples.get(Math.round(Math.min(duration - 0.001, Math.max(0, time)) * 1e6) / 1e6);
        if (!value?.screenshot) continue;
        const via = [0, last];
        try {
          const recheckDeadline = Date.now() + parameters.timeout_ms * 3;
          const remaining = () => ({timeout: Math.max(1, recheckDeadline - Date.now())});
          for (const stop of [...via, value.time]) await settle(stop, remaining);
          const box = await iframe.boundingBox();
          const again = Buffer.from(await page.screenshot({type: 'png', clip: box}));
          const first = await fs.readFile(path.join(input.evidence_dir, value.screenshot));
          const identical = first.equals(again);
          if (!identical) await fs.writeFile(path.join(input.evidence_dir, value.screenshot.replace(/\.png$/, '-reseek.png')), again);
          result.determinism.push({time: value.time, via, identical});
        } catch (error) {
          result.determinism.push({time: value.time, via, identical: null, detail: error.message});
        }
      }
    }
    if (input.measurements && !explicit) {
      const boundaries = new Set([...(input.scenes || []).map(scene => scene.start), ...(input.boundaries || [])]);
      for (const time of await frame.evaluate(() => [...(window.__hfRollBoundaries || [])].flatMap(read => read()))) boundaries.add(time);
      result.boundaries = [...boundaries].filter(time => time >= 0 && time < duration && inSpan(time)).sort((a, b) => a - b);
      const fps = await page.evaluate(() => window.__hfProbeFps) || input.fps || 60;
      result.fps = fps;
      if (input.fps && input.fps !== fps) result.unverified.push(`Studio sampling fps ${fps} differs from Plan fps ${input.fps}; boundary pairs use Studio frames.`);
      for (const boundary of result.boundaries) {
        const first = Math.ceil(boundary * fps - 1e-7) / fps;
        await sample(first - 1 / fps);
        await sample(first);
        for (const offset of [-.2, -.1, 0, .1, .2, .4]) await sample(boundary + offset);
      }
    }
    // Sample exact helper boundaries, including short actions lost by the baseline grid.
    if (!explicit) for (const value of [...samples.values()]) for (const event of value.rhythm_candidates) {
      if (event.time < 0 || event.time >= duration || !inSpan(event.time)) continue;
      await sample(event.before ?? Math.max(0, event.time - 0.001));
      await sample(event.after ?? event.time + (event.duration > 0 ? event.duration / 2 : 0.001));
    }
    result.samples = [...samples.values()].sort((a, b) => a.time - b.time);
    result.timeline = [...new Map(result.timeline.map(value => [JSON.stringify(value), value])).values()];
    result.unverified = [...new Set(result.unverified)];
    return result;
  } finally {
    if (browser) await browser.close();
    await fs.rm(profile, {recursive: true, force: true});
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    let text = '';
    for await (const chunk of process.stdin) text += chunk;
    process.stdout.write(JSON.stringify(await probe(JSON.parse(text))) + '\n');
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
