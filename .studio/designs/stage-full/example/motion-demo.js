/* 动作对照（原型）：左右两边执行同一段动词调用，左边用工具默认实现，右边用 stage-full 卡片实现。
 * 只有「归位」是本卡独有动作，左边用 moveTo + settle 代替。12 s，无声。
 */
(function (global) {
  "use strict";

  var DURATION = 12;
  var root = document.getElementById("stage-full-motion-demo");
  var caption = document.getElementById("caption");
  root.style.opacity = "0";

  // 布局原位：三张纸片站在台面上，两张新纸片在换场后接手。
  var LAYOUT = [
    { id: "a", label: "甲", x: 150, y: 520 },
    { id: "b", label: "乙", x: 395, y: 520 },
    { id: "c", label: "丙", x: 640, y: 520 },
    { id: "d", label: "丁", x: 270, y: 520 },
    { id: "e", label: "戊", x: 520, y: 520 }
  ];
  function pieces(mount) {
    var out = {};
    LAYOUT.forEach(function (item) {
      var node = document.createElement("div");
      node.className = "piece piece-" + item.id;
      node.textContent = item.label;
      node.style.left = item.x + "px";
      node.style.top = item.y + "px";
      mount.appendChild(node);
      out[item.id] = node;
    });
    return out;
  }

  function script(motion, p, card) {
    motion.appear([p.a, p.b, p.c], { at: 0.5, stagger: { span: 0.4 } });
    motion.emphasize(p.b, { at: 2.0 });
    motion.moveTo(p.a, { at: 3.0, to: { x: 40, y: -170 } });
    motion.settle(p.a, { at: 3.7 });
    if (card) {
      motion.sortTo(p.c, { at: 4.8, to: { x: -60, y: 40 } });
    } else {
      motion.moveTo(p.c, { at: 4.8, to: { x: -60, y: 40 } });
      motion.settle(p.c, { at: 5.45 });
    }
    motion.exit(p.b, { at: 6.4 });
    motion.transition({ outgoing: [p.a, p.c], incoming: [p.d, p.e] }, { at: 7.6 });
    motion.emphasize(p.d, { at: 9.8, strength: "strong" });
  }

  var tool = global.HarnessMotion.create();
  var card = global.HarnessMotion.create({ card: "stage-full" });
  script(tool, pieces(document.getElementById("tool-side")), false);
  script(card, pieces(document.getElementById("card-side")), true);

  var STEPS = [
    [0.5, "出现 · 三张错峰"], [2.0, "强调 · 乙"], [3.0, "移动到 · 甲上架"], [3.7, "落定 · 甲"],
    [4.8, "归位 · 丙（卡片独有；左边用移动到 + 落定）"], [6.4, "退场 · 乙"],
    [7.6, "换场 · 甲丙 → 丁戊"], [9.8, "强调 · 丁（strong）"]
  ];
  function renderAt(t) {
    tool.apply(t);
    card.apply(t);
    var text = "";
    for (var i = 0; i < STEPS.length; i += 1) if (t >= STEPS[i][0]) text = STEPS[i][1];
    if (caption.textContent !== text) caption.textContent = text;
  }

  var timeline = global.gsap.timeline({ paused: true });
  timeline.to({}, { duration: DURATION }, 0);
  global.__timelines = global.__timelines || {};
  global.__timelines["stage-full-motion-demo"] = timeline;
  var binding = global.HarnessScene.bindScene({
    start: 0, duration: DURATION, timeline: timeline,
    ready: document.fonts.ready, renderAt: renderAt
  });
  var ready = binding.seek(0).then(function () { root.style.opacity = "1"; });
  global.__example = {
    duration: DURATION,
    seek: function (time) { return ready.then(function () { return binding.seek(time); }); },
    dispose: function () {
      binding.dispose();
      tool.dispose();
      card.dispose();
      delete global.__timelines["stage-full-motion-demo"];
    },
    ready: ready
  };
})(window);
