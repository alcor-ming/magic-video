/* 纸上灯塔 · 40s 无声编排。只抄积木结构，内容与几何由本例提供；帆船演示 prop.states 的本期专属道具写法。
 * 0–2 展台；2–10 港湾；10–14 转入夜海；14–19 光路局部；
 * 20–23.75 折叠换肤；28–36 灯室拉开、点名、收拢；36–40 留读。
 */
(function (global) {
  "use strict";

  var DURATION = 40;
  var REBUILD_AT = 20;
  var REBUILD_END = 23.75;
  var root = document.getElementById("stage-full-kit-demo");
  var kit = global.HarnessStageKit;
  var stage = root.querySelector('[data-hf-layer="stage"]');
  var blocks = [];
  var disposed = false;
  // 积木构造会写 apply(0)，字体完成前不显示这些初始 DOM。
  root.style.opacity = "0";

  var rig = global.HarnessStageRig.createPaperStage({
    mount: document.getElementById("rig"), panels: 4, floor: true, props: true
  });

  function svg(w, h, body) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h +
      '" viewBox="0 0 ' + w + ' ' + h + '">' + body + '</svg>';
  }
  function piece(id, kind, x, y, w, h, body) {
    return { id: id, kind: kind, x: x, y: y, w: w, h: h,
      file: encodeURIComponent(svg(w, h, body)) };
  }
  function add(name, options) {
    var block = kit.create(name, options);
    blocks.push(block);
    return block;
  }

  // 两景各四件，全由 SVG 生成。base 与编码正文直接拼成 data URI。
  add("disc.scene", {
    mount: root.querySelector('[data-hf-layer="background"]'),
    base: "data:image/svg+xml;charset=utf-8,",
    scenes: [
      { id: "harbour", color: "#d8b783", pieces: [
        piece("water", "floor", 0, 760, 1920, 320,
          '<path fill="#527e86" d="M0 0H1920V320H0Z"/><path d="M0 70H1920M0 170H1920" stroke="#d6e7dc" stroke-width="8"/>'),
        piece("sun", "sky", 1320, 20, 160, 160,
          '<circle cx="80" cy="80" r="65" fill="#fff1bc"/>'),
        piece("cloud", "sky", 680, 45, 360, 110,
          '<path d="M20 90Q0 30 80 40Q110 0 170 35Q230 0 270 45Q350 30 340 90Z" fill="#fff7e5"/>'),
        piece("quay", "prop", 60, 100, 440, 120,
          '<path d="M0 85H440V120H0Z" fill="#7f6551"/><path d="M40 90V15M180 90V15M320 90V15" stroke="#fff0ce" stroke-width="18"/>')
      ] },
      { id: "night-sea", color: "#263d5b", pieces: [
        piece("water", "floor", 0, 760, 1920, 320,
          '<path fill="#284b68" d="M0 0H1920V320H0Z"/><path d="M0 65H1920M0 165H1920" stroke="#7da8bc" stroke-width="8"/>'),
        piece("moon", "sky", 1420, 20, 160, 160,
          '<circle cx="80" cy="80" r="65" fill="#f5edc9"/><circle cx="108" cy="60" r="58" fill="#263d5b"/>'),
        piece("stars", "sky", 540, 20, 700, 150,
          '<g fill="#e9ddae"><circle cx="40" cy="60" r="5"/><circle cx="210" cy="25" r="7"/><circle cx="450" cy="100" r="5"/><circle cx="650" cy="40" r="6"/></g>'),
        piece("headland", "prop", 40, 100, 460, 120,
          '<path d="M0 120L70 75L150 92L230 20L320 65L410 50L460 120Z" fill="#66818b"/>')
      ] }
    ],
    entries: [
      { scene: "harbour", turnAt: null, buildAt: 0, buildDur: 3.5 },
      { scene: "night-sea", turnAt: 10, buildAt: 12.2, buildDur: 3.5 }
    ],
    turnDur: 2.2
  });

  add("prop.stand", {
    mount: rig.parts.propsLayer, box: { x: 850, y: 360, w: 300, h: 490 },
    media: { kind: "svg", markup: svg(300, 490,
      '<path d="M85 440L108 145H192L215 440Z" fill="#fff3da" stroke="#9a5542" stroke-width="10"/>' +
      '<path d="M100 235H200M94 325H206" stroke="#c5684e" stroke-width="42"/>' +
      '<path d="M75 145H225L150 55Z" fill="#344d64"/><rect x="110" y="110" width="80" height="65" fill="#f4cd67" stroke="#344d64" stroke-width="12"/>' +
      '<path d="M60 450H240" stroke="#344d64" stroke-width="22"/>') },
    at: 2, dur: 0.6, out: 19.5, outDur: 0.5, rim: 6
  });
  // 本期专属的物用 prop.states 写：帆船分船身、桅杆、两面帆、旗五件，按命名状态切换。
  add("prop.states", {
    mount: rig.parts.propsLayer, box: { x: 1300, y: 470, w: 380, h: 390 },
    parts: [
      { id: "hull", box: { x: 20, y: 270, w: 340, h: 110 }, origin: "50% 0",
        look: { kind: "svg", markup: svg(340, 110, '<path d="M0 20H340L285 100H55Z" fill="#486e83"/><path d="M30 40H310" stroke="#fff3da" stroke-width="8"/>') } },
      { id: "mast", box: { x: 180, y: 20, w: 16, h: 260 }, origin: "50% 100%",
        look: { kind: "paper", color: "#69533e", radius: 4 } },
      { id: "main", box: { x: 60, y: 50, w: 120, h: 210 }, origin: "100% 100%",
        look: { kind: "svg", markup: svg(120, 210, '<path d="M120 0L0 210H120Z" fill="#fff4d7" stroke="#9a5542" stroke-width="6"/>') } },
      { id: "jib", box: { x: 196, y: 90, w: 110, h: 170 }, origin: "0 100%",
        look: { kind: "svg", markup: svg(110, 170, '<path d="M0 0L110 170H0Z" fill="#d29b69"/>') } },
      { id: "flag", box: { x: 196, y: 10, w: 70, h: 40 }, origin: "0 50%",
        look: { kind: "label", text: "港", size: 24, paper: "#c5684e", ink: "#fff8e8" } }
    ],
    states: {
      docked: { hull: { y: 60, o: 0 }, mast: { s: 0, o: 0 }, main: { s: 0, o: 0 }, jib: { s: 0, o: 0 }, flag: { ry: 90, o: 0 } },
      afloat: { hull: { y: 0, o: 1 }, mast: { s: 1, o: 1 } },
      sails: { main: { s: 1, o: 1 }, jib: { s: 1, o: 1 }, flag: { ry: 0, o: 1 } },
      gust: { main: { r: -6 }, jib: { r: 5 }, hull: { r: -2 } },
      calm: { main: { r: 0 }, jib: { r: 0 }, hull: { r: 0 } },
      away: { hull: { y: 40, o: 0 }, mast: { o: 0 }, main: { o: 0 }, jib: { o: 0 }, flag: { o: 0 } }
    },
    start: "docked",
    steps: [
      { at: 4.5, to: "afloat", dur: 0.5, stagger: 0.15 },
      { at: 5.4, to: "sails", dur: 0.45, stagger: 0.2, ease: "backOut" },
      { at: 7.5, to: "gust", dur: 0.6, ease: "sineInOut" },
      { at: 12.6, to: "calm", dur: 0.8, ease: "sineInOut" },
      { at: 19.0, to: "away", dur: 0.4, ease: "inOut" }
    ]
  });

  var diagram = document.createElement("div");
  diagram.style.cssText = "width:100%;height:100%;background:#20374d;";
  diagram.innerHTML = svg(900, 520,
    '<path d="M135 260L810 85V435Z" fill="#f5d67d" opacity=".22"/>' +
    '<path d="M135 260H810M135 260L810 85M135 260L810 435" stroke="#f5d67d" stroke-width="7"/>' +
    '<ellipse cx="330" cy="260" rx="45" ry="165" fill="#bce5e9" fill-opacity=".5" stroke="#e6fbf7" stroke-width="9"/>' +
    '<circle cx="135" cy="260" r="38" fill="#fff0ab"/>' +
    '<path d="M720 440H840L815 478H745Z" fill="#fff4dc"/>');
  diagram.firstChild.style.cssText = "display:block;width:100%;height:100%;";
  add("inset.broll", {
    mount: stage, box: { x: 790, y: 310, w: 960, h: 580 }, safe: { bottom: 980 },
    media: { kind: "node", node: diagram },
    enter: { from: "right", at: 14, dur: 0.6 }, exit: { at: 18.6, dur: 0.4 },
    move: { zoom: [1, 1.08], pan: [[0, 0], [-12, 4]] },
    label: { text: "灯光路径", side: "top" }
  });

  // wrapper 必须是 rig.root 的直接父节点，即 #rig（外面仍保留 #rig-wrapper）。
  var rebuild = kit.create("rig.rebuild", {
    rig: rig, wrapper: document.getElementById("rig"), at: REBUILD_AT,
    skin: { before: "", after: "is-cool", target: root },
    recede: { y: 40, scale: 0.92 }
  });
  blocks.push({
    root: rebuild.root,
    apply: function (t) {
      // 积木区间外也会写全展开，故只在接管区间调用它。
      if (t >= REBUILD_AT && t <= REBUILD_END) rebuild.apply(t);
      else {
        rebuild.root.style.transform = "translateY(0px) scale(1)";
        root.classList.toggle("is-cool", t > REBUILD_END);
      }
    },
    dispose: function () { rebuild.dispose(); }
  });

  // stack 本身一直可见；用无类名的宿主安排它的出场，不争写内部板与标签。
  var stackMount = document.createElement("div");
  stackMount.style.cssText = "position:absolute;inset:0;display:none;";
  stage.appendChild(stackMount);
  add("stack.explode", {
    mount: stackMount, origin: { x: 1240, y: 655 },
    layers: [
      { id: "base", name: "承台", note: "托住灯室", w: 430, h: 270 },
      { id: "lens", name: "透镜", note: "整理光束", w: 400, h: 250 },
      { id: "roof", name: "顶盖", note: "遮风挡雨", w: 450, h: 290 }
    ],
    tilt: { x: 52, z: -26 }, gap: 135,
    explode: { at: 28, dur: 1.4 },
    focus: [
      { index: 0, from: 29.4, to: 31 },
      { index: 1, from: 31, to: 32.5 },
      { index: 2, from: 32.5, to: 34.5 }
    ],
    collapse: { at: 34.5, dur: 1.5 }
  });

  add("slot.text", {
    mount: root.querySelector('[data-hf-layer="text"]'),
    box: { x: 100, y: 300, w: 570, h: 490 }, slots: 3, gap: 20,
    style: { size: 30, ink: "#2a302f", paper: "#fff8e8" },
    entries: [
      { id: "title", slot: 0, html: "纸上灯塔<br>把一束光送向海面", at: 2, hold: 2, out: 19.2 },
      { id: "harbour", slot: 1, html: "港湾里，灯塔与帆船<br>各自立在纸舞台上", at: 4.5, hold: 2, out: 9.3 },
      { id: "night", slot: 1, html: "夜色转入<br>灯光成为海上的路标", at: 11.8, hold: 1.5, out: 19.2 },
      { id: "detail", slot: 2, html: "靠近灯室<br>看光穿过透镜的路径", at: 7, hold: 2, out: 19.2 },
      { id: "structure", slot: 0, html: "灯室打开了<br>三层各有自己的位置", at: 24.2, hold: 2 },
      { id: "recap", slot: 2, html: "承台 · 透镜 · 顶盖<br>拆开看清，再合成一座灯塔", at: 28, hold: 2 }
    ],
    dim: [{ from: 14, to: 19 }]
  });

  var composition = kit.compose(blocks);
  var timeline = global.gsap.timeline({ paused: true });
  timeline.to({}, { duration: DURATION }, 0);

  function foldState(t) {
    // 对照 scene.js 的实际起点顺序：内板、地面、外板、道具。
    return {
      inner: kit.ease.out3(kit.ramp(t, 0, 0.65)),
      floor: kit.ease.out3(kit.ramp(t, 0.15, 0.85)),
      outer: kit.ease.out3(kit.ramp(t, 0.45, 1.25)),
      prop: kit.ease.out3(kit.ramp(t, 1.3, 2))
    };
  }
  function renderAt(t) {
    if (disposed) return;
    if (t < REBUILD_AT || t > REBUILD_END) rig.apply(foldState(t));
    composition.apply(t);
    stackMount.style.display = t >= 24 ? "block" : "none";
  }

  global.__timelines = global.__timelines || {};
  global.__timelines["stage-full-kit-demo"] = timeline;
  var binding = global.HarnessScene.bindScene({
    start: 0, duration: DURATION, timeline: timeline,
    ready: document.fonts.ready, renderAt: renderAt
  });
  var ready = binding.seek(0).then(function () {
    if (!disposed) root.style.opacity = "1";
  });
  global.__example = {
    duration: DURATION,
    seek: function (time) { return ready.then(function () { return binding.seek(time); }); },
    dispose: function () {
      if (disposed) return;
      disposed = true;
      binding.dispose();
      composition.dispose();
      stackMount.remove();
      rig.root.remove();
      delete global.__timelines["stage-full-kit-demo"];
    },
    ready: ready
  };
})(window);
