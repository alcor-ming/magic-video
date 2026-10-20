/* 标准背景动作（原型）：全屏纸板展开 → 前景动作 → 折叠换景（换皮）→ 前景再上 → 收起。15 s，无声。
 * 背景只有这一块纸板：背板铺满地平线以上，台面铺满以下，后面不再垫第二层底。
 */
(function (global) {
  "use strict";

  var DURATION = 15;
  var root = document.getElementById("stage-full-backdrop-demo");
  var caption = document.getElementById("caption");
  var stage = root.querySelector('[data-hf-layer="stage"]');
  root.style.opacity = "0";

  var backdrop = global.HarnessStageRig.createBackdrop({
    mount: root.querySelector('[data-hf-layer="background"]'), panels: 4, horizon: 700,
    skins: {
      warm: { wall: ["#f7ecd8", "#e6cfa8"], floor: ["#dcbd8e", "#c49a63"] },
      cool: { wall: ["#e4eff7", "#b4cde0"], floor: ["#b9d3e6", "#8fb2cd"] }
    }
  });
  backdrop.unfold({ at: 0.2 });
  backdrop.refold({ at: 7.2, skin: "cool" });
  backdrop.fold({ at: 13.6 });

  function piece(label, colour, x) {
    var node = document.createElement("div");
    node.className = "piece";
    node.textContent = label;
    node.style.background = colour;
    node.style.left = x + "px";
    node.style.top = "640px";
    stage.appendChild(node);
    return node;
  }
  var a = piece("甲", "#e0563c", 520), b = piece("乙", "#4f8fb8", 865), c = piece("丙", "#e8a83a", 1210);
  var d = piece("丁", "#5aa36e", 690), e = piece("戊", "#8a6bb8", 1040);

  var motion = global.HarnessMotion.create({ card: "stage-full" });
  motion.appear([a, b, c], { at: 2.3, stagger: { span: 0.4 } });
  motion.emphasize(b, { at: 3.8 });
  motion.sortTo(c, { at: 4.6, to: { x: -120, y: 60 } });
  motion.exit([a, b, c], { at: 6.5, stagger: { span: 0.3 } });
  motion.appear([d, e], { at: 10.3, stagger: { span: 0.3 } });
  motion.moveTo(e, { at: 11.6, to: { x: 140, y: 0 } });
  motion.exit([d, e], { at: 13.0, stagger: { span: 0.2 } });

  var STEPS = [[0, ""], [0.2, "背景 · 纸板展开"], [2.3, "前景 · 出现"], [3.8, "前景 · 强调"], [4.6, "前景 · 归位"],
    [6.5, "前景 · 退场（换景前先让位）"], [7.2, "背景 · 折叠换景（折起时换皮）"], [10.3, "前景 · 出现"],
    [11.6, "前景 · 移动到"], [13.0, "前景 · 退场"], [13.6, "背景 · 收起"]];
  function renderAt(t) {
    backdrop.apply(t);
    motion.apply(t);
    var text = "";
    for (var i = 0; i < STEPS.length; i += 1) if (t >= STEPS[i][0]) text = STEPS[i][1];
    if (caption.textContent !== text) caption.textContent = text;
    caption.style.visibility = text ? "visible" : "hidden";
  }

  var timeline = global.gsap.timeline({ paused: true });
  timeline.to({}, { duration: DURATION }, 0);
  global.__timelines = global.__timelines || {};
  global.__timelines["stage-full-backdrop-demo"] = timeline;
  var binding = global.HarnessScene.bindScene({ start: 0, duration: DURATION, timeline: timeline, ready: document.fonts.ready, renderAt: renderAt });
  var ready = binding.seek(0).then(function () { root.style.opacity = "1"; });
  global.__example = {
    duration: DURATION,
    seek: function (time) { return ready.then(function () { return binding.seek(time); }); },
    dispose: function () { binding.dispose(); motion.dispose(); backdrop.dispose(); delete global.__timelines["stage-full-backdrop-demo"]; },
    ready: ready
  };
})(window);
