/* 进阶背景（原型）：圆盘半周换景 + 每景一块全屏纸板展开 + 小素材逐件堆叠，三个动作合成同一层背景。
 * 0.2 第一景纸板展开 → 小素材落位 → 前景表演 → 8.0 整盘转半周 → 第二景纸板展开 → 小素材落位 → 前景表演。16 s，无声。
 */
(function (global) {
  "use strict";

  var DURATION = 16;
  var root = document.getElementById("stage-full-advanced-demo");
  var caption = document.getElementById("caption");
  var stage = root.querySelector('[data-hf-layer="stage"]');
  root.style.opacity = "0";

  function svg(w, h, body) {
    return encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' + body + '</svg>');
  }
  // 小素材：带白边的纸片剪贴，全部内联 SVG。
  function bit(id, kind, x, y, w, h, body) { return { id: id, kind: kind, x: x, y: y, w: w, h: h, file: svg(w, h, body) }; }
  var EDGE = ' stroke="#fff" stroke-width="8" stroke-linejoin="round"';

  var kit = global.HarnessStageKit;
  var disc = kit.create("disc.scene", {
    mount: root.querySelector('[data-hf-layer="background"]'),
    base: "data:image/svg+xml;charset=utf-8,",
    scenes: [
      { id: "harbour", color: "#10141d",
        board: { wall: ["#f6e7c8", "#e7c996"], floor: ["#d8b783", "#bf9259"] },
        pieces: [
          bit("sun", "sky", 1420, 70, 200, 200, '<circle cx="100" cy="100" r="80" fill="#ffd36b"' + EDGE + '/>'),
          bit("cloud", "sky", 360, 110, 380, 140, '<path d="M30 120Q8 60 90 64Q120 14 190 50Q260 8 300 66Q372 60 350 120Z" fill="#fff8ea"' + EDGE + '/>'),
          bit("flag", "hanging", 900, 0, 120, 260, '<path d="M60 0V150" stroke="#7a5730" stroke-width="6"/><path d="M14 150H106L60 250Z" fill="#e0563c"' + EDGE + '/>'),
          bit("quay", "prop", 120, 560, 520, 170, '<path d="M10 70H510V160H10Z" fill="#8a6b4f"' + EDGE + '/><path d="M70 70V10M250 70V10M430 70V10" stroke="#fff0ce" stroke-width="22"/>'),
          bit("waves", "ground", 1240, 600, 600, 120, '<path d="M10 60Q85 10 160 60T310 60T460 60T590 60V110H10Z" fill="#5f97b5"' + EDGE + '/>')
        ] },
      { id: "night", color: "#10141d",
        board: { wall: ["#26385a", "#1a2840"], floor: ["#34507a", "#22375a"] },
        pieces: [
          bit("moon", "sky", 1440, 80, 180, 180, '<circle cx="90" cy="90" r="72" fill="#f5edc9"' + EDGE + '/><circle cx="122" cy="68" r="62" fill="#26385a"/>'),
          bit("stars", "sky", 300, 60, 760, 200, '<g fill="#f3df9a"' + EDGE + '><path d="M60 80l14 30 32 4-24 22 6 32-28-16-28 16 6-32-24-22 32-4z"/><path d="M380 30l10 22 24 3-18 16 5 24-21-12-21 12 5-24-18-16 24-3z"/><path d="M660 110l12 26 28 3-21 19 6 28-25-14-25 14 6-28-21-19 28-3z"/></g>'),
          bit("lamp", "hanging", 1000, 0, 140, 300, '<path d="M70 0V170" stroke="#d9c79a" stroke-width="6"/><path d="M20 170H120L100 240H40Z" fill="#ffcf5a"' + EDGE + '/>'),
          bit("rock", "prop", 160, 540, 460, 190, '<path d="M10 180L90 70L190 110L280 20L380 90L450 180Z" fill="#6c7f95"' + EDGE + '/>'),
          bit("boat", "prop", 1260, 520, 420, 210, '<path d="M30 140H390L330 200H90Z" fill="#c8553d"' + EDGE + '/><path d="M200 140V10L320 130Z" fill="#fff6e3"' + EDGE + '/>')
        ] }
    ],
    entries: [
      { scene: "harbour", turnAt: null, buildAt: 0.2, buildDur: 4.0 },
      { scene: "night", turnAt: 8.0, buildAt: 10.2, buildDur: 4.0 }
    ]
  });

  function piece(label, colour, x) {
    var node = document.createElement("div");
    node.className = "piece";
    node.textContent = label;
    node.style.background = colour;
    node.style.left = x + "px";
    node.style.top = "650px";
    stage.appendChild(node);
    return node;
  }
  var a = piece("甲", "#e0563c", 690), b = piece("乙", "#4f8fb8", 1040);
  var c = piece("丙", "#e8a83a", 690), d = piece("丁", "#5aa36e", 1040);
  var motion = global.HarnessMotion.create({ card: "stage-full" });
  motion.appear([a, b], { at: 4.4, stagger: { span: 0.3 } });
  motion.emphasize(a, { at: 5.6 });
  motion.exit([a, b], { at: 7.2, stagger: { span: 0.2 } });
  motion.appear([c, d], { at: 14.3, stagger: { span: 0.3 } });

  var STEPS = [[0, ""], [0.2, "纸板展开"], [1.8, "小素材逐件堆叠"], [4.4, "前景 · 出现"], [5.6, "前景 · 强调"],
    [7.2, "前景 · 退场"], [8.0, "整体背景旋转（圆盘半周）"], [10.2, "新景 · 纸板展开"], [11.8, "新景 · 小素材堆叠"], [14.3, "前景 · 出现"]];
  function renderAt(t) {
    disc.apply(t);
    motion.apply(t);
    var text = "";
    for (var i = 0; i < STEPS.length; i += 1) if (t >= STEPS[i][0]) text = STEPS[i][1];
    if (caption.textContent !== text) caption.textContent = text;
    caption.style.visibility = text ? "visible" : "hidden";
  }

  var timeline = global.gsap.timeline({ paused: true });
  timeline.to({}, { duration: DURATION }, 0);
  global.__timelines = global.__timelines || {};
  global.__timelines["stage-full-advanced-demo"] = timeline;
  var binding = global.HarnessScene.bindScene({ start: 0, duration: DURATION, timeline: timeline, ready: document.fonts.ready, renderAt: renderAt });
  var ready = binding.seek(0).then(function () { root.style.opacity = "1"; });
  global.__example = {
    duration: DURATION,
    seek: function (time) { return ready.then(function () { return binding.seek(time); }); },
    dispose: function () { binding.dispose(); motion.dispose(); disc.dispose(); delete global.__timelines["stage-full-advanced-demo"]; },
    ready: ready
  };
})(window);
