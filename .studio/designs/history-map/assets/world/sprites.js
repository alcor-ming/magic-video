// 代码画的纸片：平涂 + 墨线 + 淡彩，透明底，交给 diecut 加白边和纸纹。全部由种子决定。
import { canvas, rng } from './util.js';

const INK = '#3b2a1e';

function wash(x, w, h, top, bot) { const g = x.createLinearGradient(0, 0, 0, h); g.addColorStop(0, top); g.addColorStop(1, bot); return g; }

function strokeJitter(x, pts, r, amp) { x.beginPath(); pts.forEach((p, i) => { const px = p[0] + (r() - .5) * amp, py = p[1] + (r() - .5) * amp; i ? x.lineTo(px, py) : x.moveTo(px, py); }); }

// 白墙茅草（或瓦）顶的摩拉维亚农舍，山墙朝前
export function cottage(seed = 1, { tiles = false, wide = 1 } = {}) {
  const r = rng(seed); const W = Math.round(560 * wide), H = 470; const c = canvas(W, H), x = c.getContext('2d');
  x.lineJoin = 'round'; x.lineCap = 'round';
  const wx0 = 40, wx1 = W - 40, wy0 = 210, wy1 = H - 22;
  // 墙
  x.fillStyle = wash(x, W, H, '#f3ede0', '#ddd2bd'); x.fillRect(wx0, wy0, wx1 - wx0, wy1 - wy0);
  x.fillStyle = 'rgba(120,100,80,.18)'; x.fillRect(wx0, wy1 - 34, wx1 - wx0, 34); // 墙脚
  for (let i = 0; i < 14; i++) { x.fillStyle = `rgba(150,130,100,${0.05 + r() * 0.08})`; x.beginPath(); x.ellipse(wx0 + r() * (wx1 - wx0), wy0 + r() * (wy1 - wy0), 14 + r() * 30, 6 + r() * 12, 0, 0, 6.28); x.fill(); }
  // 门窗
  const dx = wx0 + (wx1 - wx0) * (0.6 + r() * 0.12), dw = 62, dh = 118;
  x.fillStyle = '#7a5638'; x.fillRect(dx, wy1 - dh, dw, dh); x.strokeStyle = INK; x.lineWidth = 4; x.strokeRect(dx, wy1 - dh, dw, dh);
  x.strokeStyle = 'rgba(40,25,15,.5)'; x.lineWidth = 2; for (let k = 1; k < 4; k++) { x.beginPath(); x.moveTo(dx + k * dw / 4, wy1 - dh + 4); x.lineTo(dx + k * dw / 4, wy1 - 4); x.stroke(); }
  const winX = wx0 + (wx1 - wx0) * 0.2, winY = wy0 + 52;
  x.fillStyle = '#3e4a55'; x.fillRect(winX, winY, 66, 60); x.fillStyle = 'rgba(200,215,225,.35)'; x.fillRect(winX + 6, winY + 6, 24, 20);
  x.strokeStyle = '#6b4a30'; x.lineWidth = 7; x.strokeRect(winX, winY, 66, 60); x.lineWidth = 4; x.beginPath(); x.moveTo(winX + 33, winY); x.lineTo(winX + 33, winY + 60); x.moveTo(winX, winY + 30); x.lineTo(winX + 66, winY + 30); x.stroke();
  x.strokeStyle = INK; x.lineWidth = 5; x.strokeRect(wx0, wy0, wx1 - wx0, wy1 - wy0);
  // 屋顶（长坡朝前的梯形 + 山墙小三角）
  const ry0 = 40, ov = 26;
  x.beginPath(); x.moveTo(wx0 - ov, wy0 + 8); x.lineTo(wx0 + 70, ry0); x.lineTo(wx1 - 70, ry0); x.lineTo(wx1 + ov, wy0 + 8); x.closePath();
  if (tiles) {
    x.fillStyle = wash(x, W, H, '#b5644a', '#8c4434'); x.fill(); x.save(); x.clip();
    x.strokeStyle = 'rgba(60,25,15,.55)'; x.lineWidth = 3;
    for (let y = ry0 + 18; y < wy0 + 10; y += 20) { x.beginPath(); x.moveTo(0, y); x.lineTo(W, y); x.stroke(); for (let xx = (y / 20 % 2) * 14; xx < W; xx += 28) { x.beginPath(); x.moveTo(xx, y); x.lineTo(xx, y - 20); x.stroke(); } }
    x.restore();
  } else {
    x.fillStyle = wash(x, W, H, '#c9a464', '#a07a44'); x.fill(); x.save(); x.clip();
    for (let i = 0; i < 520; i++) { const px = r() * W, py = ry0 + r() * (wy0 - ry0 + 10); x.strokeStyle = r() < 0.5 ? 'rgba(90,60,25,.45)' : 'rgba(240,215,150,.4)'; x.lineWidth = 1.6 + r() * 1.5; x.beginPath(); x.moveTo(px, py); x.lineTo(px + (r() - .5) * 6, py + 10 + r() * 16); x.stroke(); }
    // 白霜压在屋脊
    x.fillStyle = 'rgba(248,250,250,.85)'; x.beginPath(); x.moveTo(wx0 + 60, ry0 - 2); x.lineTo(wx1 - 60, ry0 - 2); for (let xx = wx1 - 60; xx > wx0 + 60; xx -= 18) x.lineTo(xx, ry0 + 8 + r() * 12); x.closePath(); x.fill();
    x.restore();
  }
  x.strokeStyle = INK; x.lineWidth = 6; x.beginPath(); x.moveTo(wx0 - ov, wy0 + 8); x.lineTo(wx0 + 70, ry0); x.lineTo(wx1 - 70, ry0); x.lineTo(wx1 + ov, wy0 + 8); x.closePath(); x.stroke();
  // 檐下阴影
  x.fillStyle = 'rgba(60,40,25,.28)'; x.fillRect(wx0, wy0, wx1 - wx0, 16);
  // 烟囱
  const chx = wx0 + (wx1 - wx0) * 0.72; x.fillStyle = '#d9cdb8'; x.fillRect(chx, ry0 - 26, 34, 60); x.strokeStyle = INK; x.lineWidth = 4; x.strokeRect(chx, ry0 - 26, 34, 60);
  return c;
}

// 白色乡村教堂：中殿 + 钟楼 + 洋葱顶
export function church(seed = 3) {
  const r = rng(seed); const W = 520, H = 760; const c = canvas(W, H), x = c.getContext('2d'); x.lineJoin = 'round';
  // 中殿
  const nx0 = 40, nx1 = 330, ny0 = 470, ny1 = H - 20;
  x.fillStyle = wash(x, W, H, '#f4efe4', '#dcd3c2'); x.fillRect(nx0, ny0, nx1 - nx0, ny1 - ny0);
  x.fillStyle = '#9a4a36'; x.beginPath(); x.moveTo(nx0 - 18, ny0 + 6); x.lineTo(nx0 + 40, ny0 - 70); x.lineTo(nx1, ny0 - 70); x.lineTo(nx1, ny0 + 6); x.closePath(); x.fill();
  x.strokeStyle = INK; x.lineWidth = 5; x.stroke(); x.strokeRect(nx0, ny0, nx1 - nx0, ny1 - ny0);
  for (const wx of [90, 170, 250]) { x.fillStyle = '#3e4a55'; x.beginPath(); x.moveTo(wx, ny0 + 140); x.lineTo(wx, ny0 + 70); x.arc(wx + 20, ny0 + 70, 20, Math.PI, 0); x.lineTo(wx + 40, ny0 + 140); x.closePath(); x.fill(); x.lineWidth = 4; x.stroke(); }
  // 钟楼
  const tx0 = 320, tx1 = 470, ty0 = 250;
  x.fillStyle = wash(x, W, H, '#f6f1e6', '#d8cebd'); x.fillRect(tx0, ty0, tx1 - tx0, ny1 - ty0); x.lineWidth = 5; x.strokeRect(tx0, ty0, tx1 - tx0, ny1 - ty0);
  x.fillStyle = '#3e4a55'; x.beginPath(); x.arc(395, ty0 + 70, 26, 0, 6.28); x.fill(); x.stroke();
  x.fillStyle = '#6b4a30'; x.fillRect(370, ny1 - 120, 50, 100); x.strokeRect(370, ny1 - 120, 50, 100);
  // 洋葱顶
  x.fillStyle = wash(x, W, H, '#5a6b58', '#3d4a3c');
  x.beginPath(); x.moveTo(tx0 - 8, ty0 + 4); x.bezierCurveTo(tx0 - 20, ty0 - 70, 395 - 70, ty0 - 90, 395, ty0 - 170); x.bezierCurveTo(395 + 70, ty0 - 90, tx1 + 20, ty0 - 70, tx1 + 8, ty0 + 4); x.closePath(); x.fill(); x.stroke();
  x.fillStyle = 'rgba(240,245,240,.5)'; x.beginPath(); x.ellipse(372, ty0 - 70, 14, 40, -0.3, 0, 6.28); x.fill();
  x.strokeStyle = '#b8913e'; x.lineWidth = 7; x.beginPath(); x.moveTo(395, ty0 - 165); x.lineTo(395, ty0 - 235); x.moveTo(370, ty0 - 210); x.lineTo(420, ty0 - 210); x.stroke();
  return c;
}

// 低矮的干砌石墙：一层层不规则石块、深色缝、顶上一排压顶石和白霜
export function stoneWall(seed = 5, len = 1) {
  const r = rng(seed); const W = Math.round(900 * len), H = 240; const c = canvas(W, H), x = c.getContext('2d'); x.lineJoin = 'round';
  const top = (xx) => 58 + 9 * Math.sin(xx * 0.011 + seed) + 5 * Math.sin(xx * 0.037 + seed * 2);
  const outline = () => { x.beginPath(); x.moveTo(0, H - 10); for (let xx = 0; xx <= W; xx += 10) x.lineTo(xx, top(xx)); x.lineTo(W, H - 10); x.closePath(); };
  outline(); x.fillStyle = '#3c3229'; x.fill(); x.save(); x.clip();
  const stone = (cx, cy, w, h, tone) => {
    const n = 7, pts = []; for (let k = 0; k < n; k++) { const a = k / n * 6.283 + r() * 0.5; const rr = 0.8 + r() * 0.25; pts.push([cx + Math.cos(a) * w / 2 * rr, cy + Math.sin(a) * h / 2 * rr]); }
    x.beginPath(); pts.forEach((p, i) => i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1])); x.closePath();
    const g = x.createLinearGradient(cx - w / 2, cy - h / 2, cx + w / 3, cy + h / 2); g.addColorStop(0, `rgb(${tone + 34},${tone + 28},${tone + 16})`); g.addColorStop(1, `rgb(${tone - 12},${tone - 16},${tone - 24})`);
    x.fillStyle = g; x.fill(); x.strokeStyle = 'rgba(30,22,15,.85)'; x.lineWidth = 3; x.stroke();
    if (r() < 0.25) { x.fillStyle = 'rgba(105,118,70,.5)'; x.beginPath(); x.ellipse(cx + (r() - .5) * w * 0.4, cy + h * 0.2, w * 0.2, h * 0.15, 0, 0, 6.28); x.fill(); }
    for (let k = 0; k < 3; k++) { x.strokeStyle = 'rgba(40,30,20,.35)'; x.lineWidth = 1.5; x.beginPath(); const px = cx + (r() - .5) * w * 0.5, py = cy + (r() - .5) * h * 0.4; x.moveTo(px, py); x.lineTo(px + (r() - .5) * 14, py + (r() - .5) * 8); x.stroke(); }
  };
  for (let y0 = H - 24; y0 > 40; y0 -= 30 + r() * 6) { let xx = -r() * 40; while (xx < W + 30) { const w = 38 + r() * 56, h = 26 + r() * 12; stone(xx + w / 2, y0, w, h, 112 + r() * 46 | 0); xx += w * (0.86 + r() * 0.1); } }
  // 压顶石
  for (let xx = -10; xx < W; ) { const w = 50 + r() * 40; stone(xx + w / 2, top(xx + w / 2) + 10, w, 24, 140 + r() * 30 | 0); xx += w * 0.9; }
  x.restore();
  outline(); x.strokeStyle = INK; x.lineWidth = 5; x.stroke();
  x.fillStyle = 'rgba(250,252,252,.92)'; x.beginPath(); for (let xx = 0; xx <= W; xx += 10) x.lineTo(xx, top(xx) - 2); for (let xx = W; xx >= 0; xx -= 12) x.lineTo(xx, top(xx) + 4 + r() * 9); x.closePath(); x.fill();
  x.strokeStyle = '#8a7348'; x.lineWidth = 3; for (let i = 0; i < 80; i++) { const px = r() * W; x.beginPath(); x.moveTo(px, H - 10); x.lineTo(px + (r() - .5) * 18, H - 28 - r() * 30); x.stroke(); }
  x.fillStyle = 'rgba(250,252,255,.8)'; for (let i = 0; i < 30; i++) { x.beginPath(); x.ellipse(r() * W, H - 12 - r() * 6, 8 + r() * 12, 3, 0, 0, 6.28); x.fill(); }
  return c;
}

// 地图上的兵棋纸片：法军的楔形（指向画布上方），联军纵队的长条（可带撕口）
// 法军的突击箭：一条窄纸条剪成的箭（箭头 + 箭杆 + 燕尾），墨线描边，杆上一道手画的墨线
export function wedge(color = '#2c4f9a') {
  const W = 300, H = 760; const c = canvas(W, H), x = c.getContext('2d'); x.lineJoin = 'round'; x.lineCap = 'round';
  const sw = 64, hy = 250, notch = 70;
  const path = () => { x.beginPath(); x.moveTo(W / 2, 22); x.lineTo(W - 22, hy); x.lineTo(W / 2 + sw, hy - 34); x.lineTo(W / 2 + sw, H - 24); x.lineTo(W / 2, H - 24 - notch); x.lineTo(W / 2 - sw, H - 24); x.lineTo(W / 2 - sw, hy - 34); x.lineTo(22, hy); x.closePath(); };
  path(); x.fillStyle = color; x.fill();
  x.save(); path(); x.clip();
  // 水彩的不匀：斜向淡排线
  x.strokeStyle = 'rgba(255,255,255,.09)'; x.lineWidth = 5; for (let o = -H; o < H; o += 16) { x.beginPath(); x.moveTo(0, o); x.lineTo(W, o + W * 0.6); x.stroke(); }
  const g = x.createLinearGradient(0, 0, W, 0); g.addColorStop(0, 'rgba(255,255,255,.12)'); g.addColorStop(0.55, 'rgba(255,255,255,0)'); g.addColorStop(1, 'rgba(0,0,0,.16)'); x.fillStyle = g; x.fillRect(0, 0, W, H);
  x.restore();
  x.strokeStyle = INK; x.lineWidth = 8; path(); x.stroke();
  x.strokeStyle = 'rgba(250,244,228,.85)'; x.lineWidth = 6; x.beginPath(); x.moveTo(W / 2, H - 120); x.lineTo(W / 2, 120); x.stroke();
  x.beginPath(); x.moveTo(W / 2 - 44, 170); x.lineTo(W / 2, 112); x.lineTo(W / 2 + 44, 170); x.stroke();
  return c;
}
export function columnBar(color = '#3f6a3e', part = 'whole', seed = 3) {
  const r = rng(seed); const W = 190, H = part === 'whole' ? 1500 : 760; const c = canvas(W, H), x = c.getContext('2d'); x.lineJoin = 'round';
  // a：上半段（撕口在下），b：下半段（撕口在上）；撕口锯齿先算好，填色和描边用同一条
  const jag = []; for (let xx = 22; xx <= W - 22; xx += 14) jag.push([xx, 4 + r() * 30]);
  const path = () => {
    x.beginPath();
    if (part === 'b') { x.moveTo(22, 40); jag.forEach(([xx, j]) => x.lineTo(xx, 26 + j)); x.lineTo(W - 22, H - 24); x.lineTo(22, H - 24); x.closePath(); return; }
    x.moveTo(22, 24); x.lineTo(W - 22, 24);
    if (part === 'a') { x.lineTo(W - 22, H - 40); jag.slice().reverse().forEach(([xx, j]) => x.lineTo(xx, H - 26 - j)); }
    else { x.lineTo(W - 22, H - 24); x.lineTo(22, H - 24); }
    x.closePath();
  };
  path(); x.fillStyle = color; x.fill();
  x.save(); path(); x.clip();
  // 营的刻度：一节一节的白线，像旧战役图上的纵队记号
  x.strokeStyle = 'rgba(245,240,225,.75)'; x.lineWidth = 6; for (let y = 90; y < H - 40; y += 110) { x.beginPath(); x.moveTo(30, y); x.lineTo(W - 30, y); x.stroke(); }
  x.strokeStyle = 'rgba(0,0,0,.16)'; x.lineWidth = 26; x.beginPath(); x.moveTo(W - 34, 0); x.lineTo(W - 34, H); x.stroke();
  x.restore();
  x.strokeStyle = INK; x.lineWidth = 8; path(); x.stroke();
  return c;
}

// 冬天的光秃树。kind: 'orchard' 矮而宽的果树，'tall' 高树
export function bareTree(seed = 7, kind = 'orchard') {
  const r = rng(seed); const tall = kind === 'tall';
  const W = tall ? 520 : 620, H = tall ? 900 : 640; const c = canvas(W, H), x = c.getContext('2d'); x.lineCap = 'round'; x.lineJoin = 'round';
  const segs = [];
  const grow = (px, py, ang, len, w, d) => {
    const bend = (r() - .5) * 0.5; const mx = px + Math.cos(ang + bend) * len * 0.5, my = py + Math.sin(ang + bend) * len * 0.5;
    const ex = px + Math.cos(ang) * len, ey = py + Math.sin(ang) * len;
    segs.push([px, py, mx, my, ex, ey, w, d]);
    if (d <= 0 || w < 1.3) return;
    const n = d > 4 ? 2 : 2 + (r() < 0.45 ? 1 : 0);
    for (let i = 0; i < n; i++) {
      const spread = (tall ? 0.42 : 0.62) * (r() * 0.7 + 0.5) * (i - (n - 1) / 2 + (r() - .5) * 0.6);
      const na = ang + spread + (tall ? -0.04 * Math.sign(ang + Math.PI / 2) : 0);
      grow(ex, ey, na, len * (tall ? 0.74 : 0.7) * (0.85 + r() * 0.3), w * 0.64, d - 1);
    }
  };
  const baseY = H - 30;
  if (tall) grow(W / 2, baseY, -Math.PI / 2 + (r() - .5) * 0.1, 260, 34, 7);
  else grow(W / 2, baseY, -Math.PI / 2 + (r() - .5) * 0.15, 150, 36, 6);
  // 先画暗色，再画一侧的亮边
  for (const pass of [0, 1]) for (const [px, py, mx, my, ex, ey, w] of segs) {
    x.strokeStyle = pass ? 'rgba(170,140,105,.55)' : '#4a3626'; x.lineWidth = pass ? w * 0.28 : w;
    const off = pass ? -w * 0.22 : 0;
    x.beginPath(); x.moveTo(px + off, py); x.quadraticCurveTo(mx + off, my, ex + off, ey); x.stroke();
  }
  // 细枝末梢与霜点
  for (const [, , , , ex, ey, w, d] of segs) if (d <= 1) {
    x.strokeStyle = '#5a4432'; x.lineWidth = 1.6; for (let k = 0; k < 3; k++) { const a = -Math.PI / 2 + (r() - .5) * 2.2; x.beginPath(); x.moveTo(ex, ey); x.lineTo(ex + Math.cos(a) * (10 + r() * 14), ey + Math.sin(a) * (10 + r() * 14)); x.stroke(); }
    if (r() < 0.5) { x.fillStyle = 'rgba(250,252,255,.85)'; x.beginPath(); x.arc(ex, ey - 2, 2.5 + r() * 2.5, 0, 6.28); x.fill(); }
  }
  // 树下一小片地面和枯草
  x.fillStyle = '#8b7556'; x.beginPath(); x.ellipse(W / 2, baseY + 4, tall ? 90 : 110, 16, 0, 0, 6.28); x.fill();
  x.strokeStyle = '#a58a5c'; x.lineWidth = 2.6; for (let i = 0; i < 40; i++) { const px = W / 2 + (r() - .5) * (tall ? 170 : 210); x.beginPath(); x.moveTo(px, baseY + 6); x.lineTo(px + (r() - .5) * 12, baseY - 10 - r() * 18); x.stroke(); }
  x.fillStyle = 'rgba(250,252,255,.8)'; for (let i = 0; i < 18; i++) { x.beginPath(); x.ellipse(W / 2 + (r() - .5) * 180, baseY + 2 + (r() - .5) * 8, 6 + r() * 8, 2.5, 0, 0, 6.28); x.fill(); }
  return c;
}

// 篝火底座：一圈石头 + 交叉的木柴（火苗另作）
export function fireBase(seed = 9) {
  const r = rng(seed); const W = 420, H = 220; const c = canvas(W, H), x = c.getContext('2d'); x.lineJoin = 'round';
  for (const [ax, ay, bx, by] of [[80, 190, 330, 120], [340, 190, 90, 118], [150, 200, 270, 100]]) {
    x.strokeStyle = INK; x.lineWidth = 34; x.lineCap = 'round'; x.beginPath(); x.moveTo(ax, ay); x.lineTo(bx, by); x.stroke();
    x.strokeStyle = '#6e4a2e'; x.lineWidth = 27; x.beginPath(); x.moveTo(ax, ay); x.lineTo(bx, by); x.stroke();
    x.strokeStyle = 'rgba(30,18,10,.6)'; x.lineWidth = 9; x.beginPath(); x.moveTo((ax + bx) / 2 - 20, (ay + by) / 2 + 4); x.lineTo((ax + bx) / 2 + 20, (ay + by) / 2 - 2); x.stroke();
    x.fillStyle = '#d8b48a'; x.beginPath(); x.ellipse(ax, ay, 14, 13, 0, 0, 6.28); x.fill(); x.strokeStyle = INK; x.lineWidth = 3; x.stroke();
  }
  x.fillStyle = 'rgba(255,150,60,.85)'; x.beginPath(); x.ellipse(210, 165, 70, 16, 0, 0, 6.28); x.fill(); // 炭火
  for (let i = 0; i < 9; i++) { const a = Math.PI * (0.05 + i / 8 * 0.9); const px = 210 + Math.cos(a) * 180, py = 196 - Math.sin(a) * 6; const g = 110 + r() * 50; x.fillStyle = `rgb(${g},${g - 6},${g - 16})`; x.beginPath(); x.ellipse(px, py, 26, 18, 0, 0, 6.28); x.fill(); x.strokeStyle = INK; x.lineWidth = 3.5; x.stroke(); }
  return c;
}

// 火苗：三帧轮换（不透明的纸剪火苗，后面再加发光）
export function flame(frame = 0) {
  const r = rng(40 + frame); const W = 260, H = 360; const c = canvas(W, H), x = c.getContext('2d');
  const tongue = (cx, base, h, w, col) => { x.fillStyle = col; x.beginPath(); x.moveTo(cx - w / 2, base); x.bezierCurveTo(cx - w * 0.7, base - h * 0.45, cx - w * 0.1 + (r() - .5) * 20, base - h * 0.7, cx + (r() - .5) * 26, base - h); x.bezierCurveTo(cx + w * 0.2, base - h * 0.6, cx + w * 0.75, base - h * 0.4, cx + w / 2, base); x.closePath(); x.fill(); };
  const H0 = H - 10;
  tongue(130, H0, 300 + r() * 40, 200, '#e2572a');
  tongue(100 + r() * 20, H0, 210 + r() * 40, 120, '#f08a2c');
  tongue(165 - r() * 20, H0, 230 + r() * 30, 110, '#f08a2c');
  tongue(130, H0, 150 + r() * 30, 90, '#f9c94e');
  tongue(130, H0, 80, 50, '#fff2b8');
  return c;
}
