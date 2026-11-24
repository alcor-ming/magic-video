// 历史卡牌子模块：九种纸片牌子。不依赖 three。apply(t) 是 t 的纯函数。
const sheets = new WeakMap();
const CSS_URL = new URL('./plates.css', import.meta.url).href;
const FADE = 0.5;
const BOUNDS = { x0: 120, y0: 110, x1: 1800, y1: 820 };
const GAP = 30;
const PAD = 14;
const NEUTRAL = '#8b7b5c';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = u => u * u * (3 - 2 * u);
function hash(str) { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
function rng(seed) { let s = seed || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const lines = s => String(s).split('\n').map(l => `<span class="ln">${esc(l)}</span>`).join('');

// 略不齐的手剪边：切角 + 沿边抖动，确定性（只由种子决定）
function paperClip(w, h, seed, c = 10, j = 2.2) {
  const r = rng(seed); const pts = [];
  const jit = () => (r() - .5) * 2 * j;
  const edge = (x0, y0, x1, y1) => { const n = Math.max(2, Math.round(Math.hypot(x1 - x0, y1 - y0) / 46)); for (let i = 0; i < n; i++) { const u = i / n; pts.push([x0 + (x1 - x0) * u + jit(), y0 + (y1 - y0) * u + jit()]); } };
  edge(c, 0, w - c, 0); edge(w - c, 0, w, c); edge(w, c, w, h - c); edge(w, h - c, w - c, h);
  edge(w - c, h, c, h); edge(c, h, 0, h - c); edge(0, h - c, 0, c); edge(0, c, c, 0);
  return 'polygon(' + pts.map(p => `${clamp(p[0], 0, w).toFixed(1)}px ${clamp(p[1], 0, h).toFixed(1)}px`).join(',') + ')';
}

function rotBox(w, h, deg) {
  const a = Math.abs(deg) * Math.PI / 180;
  return { w: Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a)), h: Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a)) };
}
const overlaps = (a, b, p = PAD) => a.x < b.x + b.w + p && b.x < a.x + a.w + p && a.y < b.y + b.h + p && b.y < a.y + a.h + p;
const inside = r => r.x >= BOUNDS.x0 - .5 && r.y >= BOUNDS.y0 - .5 && r.x + r.w <= BOUNDS.x1 + .5 && r.y + r.h <= BOUNDS.y1 + .5;
const clampRect = r => ({ ...r, x: clamp(r.x, BOUNDS.x0, Math.max(BOUNDS.x0, BOUNDS.x1 - r.w)), y: clamp(r.y, BOUNDS.y0, Math.max(BOUNDS.y0, BOUNDS.y1 - r.h)) });

function placeRect(place, a, w, h) {
  switch (place) {
    case 'above': return { x: a.x - w / 2, y: a.y - GAP - h, w, h };
    case 'below': return { x: a.x - w / 2, y: a.y + GAP, w, h };
    case 'left': return { x: a.x - GAP - w, y: a.y - h / 2, w, h };
    case 'right': return { x: a.x + GAP, y: a.y - h / 2, w, h };
    default: return { x: a.x - w / 2, y: a.y - h / 2, w, h };
  }
}
const ORDER = { above: ['above', 'below', 'right', 'left'], below: ['below', 'above', 'right', 'left'], left: ['left', 'right', 'above', 'below'], right: ['right', 'left', 'above', 'below'], center: ['center', 'above', 'below'] };

export function createPlates(overlay, { fontFamily, sides = {}, mode = 'standalone' } = {}) {
  const doc = overlay.ownerDocument;
  let sheet = sheets.get(doc);
  if (!sheet) {
    const link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = CSS_URL;
    const ready = new Promise((resolve, reject) => {
      link.addEventListener('load', resolve, { once: true });
      link.addEventListener('error', () => reject(new Error('字牌样式载入失败')), { once: true });
    });
    sheet = { link, ready, count: 0 };
    sheets.set(doc, sheet);
    doc.head.appendChild(link);
  }
  sheet.count++;
  let disposed = false;
  const layer = document.createElement('div'); layer.className = 'pl-layer'; if (fontFamily) layer.style.fontFamily = `"${fontFamily}", "Source Han Sans CN", sans-serif`;
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg'); svg.setAttribute('class', 'pl-threads'); svg.setAttribute('width', 1920); svg.setAttribute('height', 1080);
  layer.appendChild(svg); overlay.appendChild(layer);

  const sideColor = s => (s && sides[s] && sides[s].color) || NEUTRAL;
  const standalone = mode === 'standalone';
  const DATE_POS = standalone ? { x: 60, y: 40 } : { x: 120, y: 112 };
  layer.style.perspective = '1400px';
  // 页内的日期牌向右展开，透视变换后的左边仍停在安全线。
  layer.style.perspectiveOrigin = `${DATE_POS.x + (standalone ? 200 : 0)}px ${DATE_POS.y}px`;
  let items = [];       // 所有牌子（日期除外）
  let dates = [];       // 日期牌
  let corners = [];
  let spec = {};

  function mk(kind, id, cls, html, color, seed, clipC, extra = {}) {
    const el = document.createElement('div'); el.className = `pl pl-${kind} ${cls || ''}`; el.dataset.id = id;
    const body = document.createElement('div'); body.className = 'pl-body'; body.style.setProperty('--side', color); body.innerHTML = html; el.appendChild(body);
    layer.appendChild(el);
    return { el, body, kind, id, color, seed, clipC, ...extra };
  }
  function measure(it, fixed) {
    it.el.style.visibility = 'hidden'; it.el.style.transform = 'none';
    it.w = it.el.offsetWidth; it.h = it.el.offsetHeight;
    if (it.clipC !== null && it.clipC !== undefined) it.body.style.clipPath = paperClip(it.w, it.h, it.seed, it.clipC);
    const r = rng(it.seed ^ 0x9e3779b9); it.rot = it.rotFixed !== undefined ? it.rotFixed : (r() - .5) * 2.2;
    if (it.angle) it.rot = it.angle;
    it.box = it.angle ? rotBox(it.w, it.h, it.angle) : { w: it.w, h: it.h };
  }

  function load(s) {
    // 清理旧
    layer.querySelectorAll('.pl').forEach(e => e.remove()); svg.innerHTML = '';
    items = []; dates = []; corners = []; spec = s || {};
    const add = (it) => { items.push(it); return it; };
    for (const d of (spec.date || [])) {
      const it = mk('date', 'date@' + d.at, '', `<div class="yr">${esc(d.year)}</div><div class="dd">${esc(d.date)}</div><div class="sb">${d.sub ? `<span class="sub">${esc(d.sub)}</span>` : ''}${d.time ? `<span class="tm">${esc(d.time)}</span>` : ''}</div>`, '#7c2b22', hash('date' + d.at), 12, { at: d.at, rotFixed: 0 });
      it.spec = d; dates.push(it);
    }
    dates.sort((a, b) => a.at - b.at);
    for (const c of (spec.cards || [])) add(mk('card', c.id, '', lines(c.text), sideColor(c.side), hash(c.id), 9, { spec: c, anchored: true, thread: true, place: c.place || 'above' }));
    for (const c of (spec.names || [])) add(mk('name', c.id, '', `<i class="tape"></i>${esc(c.text)}`, sideColor(c.side), hash(c.id), 8, { spec: c, anchored: true, thread: true, place: c.place || 'above' }));
    for (const c of (spec.labels || [])) add(mk('label', c.id, 'pl-kraft', esc(c.text), NEUTRAL, hash(c.id), 8, { spec: c, anchored: true, thread: true, place: 'above' }));
    for (const c of (spec.pills || [])) {
      const num = (v, col) => `<span class="seg num" style="--c:${col}">${esc(v)}</span>`;
      add(mk('pill', c.id, '', `${num(c.a, sideColor('a'))}<span class="seg mid">${esc(c.place)}</span>${num(c.b, sideColor('b'))}`, NEUTRAL, hash(c.id), 14, { spec: c, anchored: true, thread: false, place: 'center' }));
    }
    for (const c of (spec.banners || [])) add(mk('banner', c.id, '', esc(c.text), sideColor(c.side), hash(c.id), 12, { spec: c, anchored: true, thread: false, place: 'center', angle: c.angle || 0 }));
    for (const c of (spec.tables || [])) {
      const isNum = v => /\d/.test(String(v));
      const hd = `<div class="tr hd"><span class="c0"></span><span class="cv" style="--c:${sideColor('a')}">${esc((sides.a || {}).name || '甲方')}</span><span class="cv" style="--c:${sideColor('b')}">${esc((sides.b || {}).name || '乙方')}</span></div>`;
      const rows = c.rows.map(r => `<div class="tr"><span class="c0">${esc(r[0])}</span><span class="cv ${isNum(r[1]) ? 'n' : 't'}">${esc(r[1])}</span><span class="cv ${isNum(r[2]) ? 'n' : 't'}">${esc(r[2])}</span></div>`).join('');
      const it = add(mk('table', c.id, '', `<div class="tt">${esc(c.title)}</div>${hd}${rows}`, NEUTRAL, hash(c.id), 10, { spec: c, corner: c.corner || 'tr' }));
      corners.push(it);
    }
    for (const c of (spec.counters || [])) {
      const it = add(mk('counter', c.id, '', `<div class="lb">${esc(c.label)}</div><div class="nv">0</div>`, sideColor(c.side), hash(c.id), 10, { spec: c, corner: c.corner || 'bl' }));
      it.nv = it.el.querySelector('.nv'); corners.push(it);
    }
    for (const c of (spec.quotes || [])) {
      const it = add(mk('quote', c.id, '', `<div class="qt">${lines(c.text)}</div>${c.by ? `<div class="by">${esc(c.by)}</div>` : ''}`, NEUTRAL, hash(c.id), 10, { spec: c, corner: c.corner || 'br' }));
      corners.push(it);
    }
    for (const it of items) {
      if (it.thread) {
        it.line = document.createElementNS(svgNS, 'line'); it.line.setAttribute('class', 'pl-thread');
        it.pin = document.createElementNS(svgNS, 'circle'); it.pin.setAttribute('class', 'pl-pin'); it.pin.setAttribute('r', 10); it.pin.style.setProperty('--c', it.color);
        svg.appendChild(it.line); svg.appendChild(it.pin);
      }
    }
    measured = false;
  }
  let measured = false;
  function finalize() {
    if (measured) return true;
    if (!sheet.link.sheet) return false;
    for (const it of dates) measure(it);
    for (const it of items) measure(it);
    // 角落静态堆叠：同角落、时间有交叠的按载入顺序依次叠开
    const dateH = dates.length ? Math.max(...dates.map(d => d.h)) : 0;
    const topStart = dates.length ? DATE_POS.y + dateH + 24 : BOUNDS.y0;
    const done = [];
    for (const it of corners) {
      let off = 0;
      for (const o of done) if (o.corner === it.corner && o.spec.from < it.spec.to && it.spec.from < o.spec.to) off = Math.max(off, o.off + o.h + 20);
      it.off = off; done.push(it);
      const left = it.corner.endsWith('l'), top = it.corner.startsWith('t');
      const x = left ? BOUNDS.x0 : BOUNDS.x1 - it.w;
      const y = top ? (left ? topStart : BOUNDS.y0) + off : BOUNDS.y1 - 10 - it.h - off;
      it.cornerRect = { x, y, w: it.w, h: it.h };
    }
    measured = true; return true;
  }

  const anchorOf = (it, t) => { const a = it.spec.anchor; const v = typeof a === 'function' ? a(t) : a; return v || { x: 960, y: 540 }; };
  const activeAt = (it, t) => t >= it.spec.from && t <= it.spec.to;
  function dateState(t) {
    // 返回 [{it, alpha, rotX, dy}]
    if (!dates.length) return [];
    let idx = -1; for (let i = 0; i < dates.length; i++) if (dates[i].at <= t) idx = i;
    if (idx < 0) return [];
    const cur = dates[idx], next = dates[idx + 1];
    const u = ease(clamp((t - cur.at) / (idx === 0 ? FADE : FADE / 2), 0, 1));
    const out = next ? ease(clamp(1 - (next.at - t) / (FADE / 2), 0, 1)) : 0;
    // 到达换页时刻前掀走旧页，再放下新页；两页宽度不同也不会露边。
    return [{ it: cur, alpha: idx === 0 ? u : 1, rotX: 82 * (out - (idx === 0 ? 0 : 1 - u)), dy: idx === 0 ? -14 * (1 - u) : 0 }];
  }

  // 全部确定性布局：只看 t
  function compute(t) {
    const placed = []; const res = [];
    const ds = dateState(t);
    for (const d of ds) {
      const r = { x: DATE_POS.x, y: DATE_POS.y, w: d.it.w, h: d.it.h };
      placed.push(r);
      res.push({ it: d.it, rect: r, alpha: d.alpha, rotX: d.rotX, dy: d.dy, dx: 0, rot: 0, id: d.it.id });
    }
    for (const it of corners) if (activeAt(it, t)) { placed.push(it.cornerRect); res.push({ it, rect: it.cornerRect, id: it.id }); }
    for (const it of items) {
      if (!it.anchored || !activeAt(it, t)) continue;
      const a = anchorOf(it, t); const w = it.box.w, h = it.box.h;
      const cands = ORDER[it.place] || ORDER.above; let best = null;
      for (const p of cands) {
        let r = placeRect(p, a, w, h);
        if (p === 'above' || p === 'below' || p === 'center') r = { ...r, x: clamp(r.x, BOUNDS.x0, BOUNDS.x1 - w) };
        if (p === 'left' || p === 'right' || p === 'center') r = { ...r, y: clamp(r.y, BOUNDS.y0, BOUNDS.y1 - h) };
        if (inside(r) && !placed.some(o => overlaps(r, o))) { best = r; break; }
      }
      if (!best) { best = clampRect(placeRect(cands[0], a, w, h)); }
      placed.push(best); res.push({ it, rect: best, id: it.id, anchor: a });
    }
    return res;
  }

  function alphaAt(it, t) {
    const f = it.spec.from, e = it.spec.to;
    return Math.min(clamp((t - f) / FADE, 0, 1), clamp((e - t) / FADE, 0, 1));
  }

  function apply(t) {
    if (!finalize()) return;
    const res = compute(t);
    const shown = new Set(res.map(r => r.it));
    for (const it of [...dates, ...items]) {
      if (shown.has(it)) continue;
      it.el.style.cssText = 'visibility: hidden; transform: none;';
      if (it.nv) it.nv.textContent = '0';
      if (it.line) {
        it.line.style.cssText = 'display: none;';
        it.pin.style.cssText = `--c: ${it.color}; display: none;`;
        for (const attr of ['x1', 'y1', 'x2', 'y2']) it.line.removeAttribute(attr);
        for (const attr of ['cx', 'cy']) it.pin.removeAttribute(attr);
      }
    }
    for (const r of res) {
      const it = r.it; const el = it.el;
      el.style.cssText = '';
      let alpha, dy = 0, dx = 0, rotX = 0, sc = 1;
      if (it.kind === 'date') { alpha = r.alpha; dy = r.dy; rotX = r.rotX; }
      else { const u = alphaAt(it, t); const e = ease(u); alpha = e; dy = -14 * (1 - e); sc = 1 + .035 * (1 - e); }
      const rect = r.rect;
      let cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
      if (!standalone) {
        const box = rotBox(it.w, it.h, it.rot || 0);
        const halfW = box.w * sc / 2, halfH = box.h * sc / 2;
        cx = clamp(cx, BOUNDS.x0 + halfW, BOUNDS.x1 - halfW);
        cy = clamp(cy + dy, BOUNDS.y0 + halfH, 800 - halfH) - dy;
      }
      const left = cx - it.w / 2, top = cy - it.h / 2;
      el.style.visibility = alpha > 0.002 ? 'visible' : 'hidden';
      el.style.opacity = alpha.toFixed(3);
      el.style.zIndex = it.kind === 'date' ? (r.rotX ? 5 : 4) : 3;
      el.style.transform = `translate(${left.toFixed(1)}px, ${(top + dy).toFixed(1)}px) rotateX(${rotX.toFixed(1)}deg) rotate(${(it.rot || 0).toFixed(2)}deg) scale(${sc.toFixed(3)})`;
      if (it.kind === 'date') el.style.transformOrigin = '50% 0';
      if (it.nv) {
        const keys = it.spec.keys; let v = keys[0][1];
        if (t >= keys[keys.length - 1][0]) v = keys[keys.length - 1][1];
        else if (t > keys[0][0]) for (let i = 0; i < keys.length - 1; i++) if (t >= keys[i][0] && t <= keys[i + 1][0]) { const u = (t - keys[i][0]) / (keys[i + 1][0] - keys[i][0]); v = keys[i][1] + (keys[i + 1][1] - keys[i][1]) * u; }
        it.nv.textContent = Math.round(v).toLocaleString('en-US');
      }
      if (it.line) {
        const a = r.anchor; const px = clamp(a.x, rect.x, rect.x + rect.w), py = clamp(a.y, rect.y, rect.y + rect.h);
        const away = Math.hypot(a.x - px, a.y - py) > 6;
        it.line.style.cssText = away ? '' : 'display: none;';
        it.pin.style.cssText = `--c: ${it.color};`;
        it.line.setAttribute('x1', px.toFixed(1)); it.line.setAttribute('y1', (py + dy).toFixed(1)); it.line.setAttribute('x2', a.x.toFixed(1)); it.line.setAttribute('y2', a.y.toFixed(1));
        it.pin.setAttribute('cx', a.x.toFixed(1)); it.pin.setAttribute('cy', a.y.toFixed(1));
        it.line.style.opacity = it.pin.style.opacity = alpha.toFixed(3);
      }
    }
  }

  const FONT = { card: 48, name: 52, label: 50, pill: 50, banner: 68, table: 50, counter: 50, quote: 48, date: 50 };
  function texts() {
    const out = [];
    for (let i = 0; i < dates.length; i++) { const d = dates[i].spec; out.push({ id: dates[i].id, text: [d.year, d.date, d.sub, d.time].filter(Boolean).join(' '), start: d.at, end: i + 1 < dates.length ? dates[i + 1].at : Infinity, kind: 'date' }); }
    for (const it of items) {
      const s = it.spec; let text = '';
      if (it.kind === 'pill') text = `${s.a} | ${s.place} | ${s.b}`;
      else if (it.kind === 'table') text = s.title + ' ' + s.rows.map(r => r.join(' ')).join(' / ');
      else if (it.kind === 'counter') text = s.label + ' ' + s.keys[s.keys.length - 1][1];
      else if (it.kind === 'quote') text = s.text + (s.by ? ' ' + s.by : '');
      else text = s.text;
      out.push({ id: it.id, text, start: s.from, end: s.to, kind: it.kind });
    }
    return out;
  }
  function layoutAt(t) {
    if (!finalize()) return [];
    const res = compute(t);
    // 日期牌按当前页的平放矩形报告，给翻页动画预留完整空间。
    const ds = res.filter(r => r.it.kind === 'date');
    const out = res.filter(r => r.it.kind !== 'date');
    if (ds.length) {
      const cur = ds.find(r => !r.rotX) || ds[0];
      const x0 = Math.min(...ds.map(r => r.rect.x)), y0 = Math.min(...ds.map(r => r.rect.y)), x1 = Math.max(...ds.map(r => r.rect.x + r.rect.w)), y1 = Math.max(...ds.map(r => r.rect.y + r.rect.h));
      out.unshift({ ...cur, rect: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } });
    }
    return out.map(r => ({ id: r.id, kind: r.it.kind, x: Math.round(r.rect.x), y: Math.round(r.rect.y), w: Math.round(r.rect.w), h: Math.round(r.rect.h), fontPx: FONT[r.it.kind] }));
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    layer.remove();
    if (--sheet.count === 0) {
      sheet.link.remove();
      sheets.delete(doc);
    }
  }
  return { load, apply, texts, layoutAt, dispose, ready: sheet.ready };
}
