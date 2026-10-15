/* Shared paper-stage fold mechanism for the stage-full / stage-light design cards.
 *
 * One rig, two cards: stage-full builds the full four-panel set, stage-light passes
 * { panels: 2 } and gets only the inner pair. Geometry and hinge owners are the same.
 *
 * Extracted from an authorised project mechanism:
 *   .set perspective > slide > wall + floor + props
 *   - four wall panels, each 480px wide, tiled across the 1920 frame;
 *   - inner pair anchored at the frame centre, folding +/-86deg;
 *   - outer panels are children of the inner panels and fold the opposite way +/-172deg;
 *   - the floor bridge hinges about its top edge out of -90deg;
 *   - prop feet hinge about their top edge from 88deg to stand.
 * Unfold order is inner first, then outer, each stage locking when it reaches 0deg.
 *
 * Ownership rule: this rig owns hinge rotation only. The scene's own wrapper owns
 * translation, scale and every other transform, so the fold can never be faked by
 * panning or fading the whole set.
 *
 * Determinism: apply(state) is a pure function of {inner, outer, floor, prop}, all
 * 0..1, so any seek or backwards seek rebuilds the complete set from scratch.
 * No RAF, no timers, no Date, no Math.random, no event/callback dependency.
 */
(function (global) {
  "use strict";

  var WALL_PANEL_WIDTH = 480;
  var WALL_PANEL_HEIGHT = 520;
  var WALL_TOP = 200;                 // stage base line is WALL_TOP + WALL_PANEL_HEIGHT
  var FLOOR_DEPTH = 360;
  var STAGE_WIDTH = 1920;
  var INNER_FOLD_DEG = 86;
  var OUTER_FOLD_DEG = 172;
  var FLOOR_FOLD_DEG = -90;
  var PROP_FOLD_DEG = 88;

  var RIG_CSS = [
    ".hf-rig{position:absolute;inset:0;perspective:1800px;perspective-origin:50% 34%;transform-style:preserve-3d;}",
    ".hf-rig-deck{position:absolute;inset:0;transform-style:preserve-3d;}",
    ".hf-rig-props{position:absolute;inset:0;transform-style:preserve-3d;pointer-events:none;}",
    ".hf-rig-wall{position:absolute;top:" + WALL_TOP + "px;width:" + WALL_PANEL_WIDTH + "px;height:" + WALL_PANEL_HEIGHT + "px;transform-style:preserve-3d;backface-visibility:visible;}",
    ".hf-rig-wall-inner-left{left:" + (STAGE_WIDTH / 2 - WALL_PANEL_WIDTH) + "px;transform-origin:right center;}",
    ".hf-rig-wall-inner-right{left:" + (STAGE_WIDTH / 2) + "px;transform-origin:left center;}",
    ".hf-rig-wall-outer-left{top:0;left:-" + WALL_PANEL_WIDTH + "px;transform-origin:right center;}",
    ".hf-rig-wall-outer-right{top:0;left:" + WALL_PANEL_WIDTH + "px;transform-origin:left center;}",
    ".hf-rig-floor{position:absolute;left:0;top:" + (WALL_TOP + WALL_PANEL_HEIGHT) + "px;width:" + STAGE_WIDTH + "px;height:" + FLOOR_DEPTH + "px;transform-origin:50% 0;transform-style:preserve-3d;}",
    "[data-hf-prop-foot]{transform-origin:50% 0;transform-style:preserve-3d;}"
  ].join("");

  function ensureCss() {
    if (document.getElementById("hf-stage-rig-css")) return;
    var style = document.createElement("style");
    style.id = "hf-stage-rig-css";
    style.textContent = RIG_CSS;
    document.head.appendChild(style);
  }

  function make(tag, cls, parent) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (parent) parent.appendChild(node);
    return node;
  }

  function clamp01(value) {
    var number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return 0;
    return number >= 1 ? 1 : number;
  }

  function createPaperStage(options) {
    options = options || {};
    var mount = options.mount;
    if (!mount) throw new TypeError("createPaperStage requires a mount element");
    var panels = options.panels === 2 ? 2 : 4;
    var withFloor = options.floor !== false;
    var withProps = options.props !== false;
    var name = options.name || "set";

    ensureCss();

    var root = make("div", "hf-rig hf-rig-" + name, mount);
    root.setAttribute("aria-hidden", "true");
    var deck = make("div", "hf-rig-deck", root);

    var parts = { root: root, deck: deck, walls: [] };
    parts.innerLeft = make("div", "hf-rig-wall hf-rig-wall-inner-left", deck);
    parts.innerRight = make("div", "hf-rig-wall hf-rig-wall-inner-right", deck);
    parts.walls.push(parts.innerLeft, parts.innerRight);
    if (panels === 4) {
      parts.outerLeft = make("div", "hf-rig-wall hf-rig-wall-outer-left", parts.innerLeft);
      parts.outerRight = make("div", "hf-rig-wall hf-rig-wall-outer-right", parts.innerRight);
      parts.walls.push(parts.outerLeft, parts.outerRight);
    }
    if (withFloor) parts.floor = make("div", "hf-rig-floor", deck);
    if (withProps) parts.propsLayer = make("div", "hf-rig-props", deck);
    // Walls and floor are scenery (background track). Diagnostics measure foreground
    // coverage without them; outer walls inherit the mark through their inner parent.
    parts.walls.concat(parts.floor ? [parts.floor] : []).forEach(function (node) {
      node.setAttribute("data-hf-set", "");
    });

    function propFeet() {
      return root.querySelectorAll("[data-hf-prop-foot]");
    }

    function apply(state) {
      state = state || {};
      var inner = clamp01(state.inner);
      var outer = clamp01(state.outer);
      var floor = clamp01(state.floor);
      var prop = clamp01(state.prop);
      var innerAngle = INNER_FOLD_DEG * (1 - inner);
      var outerAngle = OUTER_FOLD_DEG * (1 - outer);
      parts.innerLeft.style.transform = "rotateY(" + innerAngle + "deg)";
      parts.innerRight.style.transform = "rotateY(" + (-innerAngle) + "deg)";
      if (parts.outerLeft) parts.outerLeft.style.transform = "rotateY(" + (-outerAngle) + "deg)";
      if (parts.outerRight) parts.outerRight.style.transform = "rotateY(" + outerAngle + "deg)";
      if (parts.floor) parts.floor.style.transform = "rotateX(" + (FLOOR_FOLD_DEG * (1 - floor)) + "deg)";
      var propAngle = PROP_FOLD_DEG * (1 - prop);
      var feet = propFeet();
      for (var i = 0; i < feet.length; i += 1) {
        feet[i].style.transform = "rotateX(" + propAngle + "deg)";
      }
    }

    // Skins live in each example's style.css so the two cards stay materially
    // distinct while sharing this one fold mechanism.
    apply({ inner: 0, outer: 0, floor: 0, prop: 0 });

    return {
      root: root,
      deck: deck,
      parts: parts,
      apply: apply,
      refreshProps: propFeet
    };
  }

  global.HarnessStageRig = {
    createPaperStage: createPaperStage,
    WALL_PANEL_WIDTH: WALL_PANEL_WIDTH,
    WALL_PANEL_HEIGHT: WALL_PANEL_HEIGHT,
    WALL_TOP: WALL_TOP,
    FLOOR_DEPTH: FLOOR_DEPTH,
    STAGE_WIDTH: STAGE_WIDTH,
    INNER_FOLD_DEG: INNER_FOLD_DEG,
    OUTER_FOLD_DEG: OUTER_FOLD_DEG,
    FLOOR_FOLD_DEG: FLOOR_FOLD_DEG,
    PROP_FOLD_DEG: PROP_FOLD_DEG
  };
})(window);
