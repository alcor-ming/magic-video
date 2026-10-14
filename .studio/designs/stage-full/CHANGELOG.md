# stage-full CHANGELOG

- v4（2026-10-14）：stage-kit 补齐四个积木 `spot.sweep`、`spot.split`、`tray.sort`、`sign.plate`，舞台动作菜单除 rig.build / rig.recede / hold 外全部有独立积木；`capabilities.checks` 新增 `css-contract`（JS 创建却无样式契约的类名）与 `frame-blank`（Scene 中段舞台层空画面），对应工具侧 `css_contract.py`、`stage_checks.py` 与探针 `stage_visible` 字段。
- v3（2026-10-14）：新增 `stage-kit` 资产六个积木（`disc.scene`、`rig.rebuild`、`prop.stand`、`inset.broll`、`stack.explode`、`slot.text`）与 `example/kit-demo.html` + `example/kit-demo.js` 出场示范；新增 GUIDE §10 积木清单与来源表圆盘换景机制，明确轨道档积木用法、重建变换归属与视频预览限制；更新 `stages/plan.md` 动作参数合同及文档链接、`stages/draft.md` 积木优先与类名覆盖说明。
- v2（2026-10-14）：新增「轨道档」合同。GUIDE §0 分档与 §9 六种做坏方式；`stages/plan.md` 轨道镜头表（表前三行画风/色板/角色、舞台动作菜单、硬规则）；`stages/draft.md` 轨道档自检（三帧截图、计算样式、可见性归属、类名覆盖、位图与声音规则）；卡内 `ANIMATION_PLAN.template.md` 加 `## 轨道镜头表` 节；新增 `tools/check-classes.mjs` 类名覆盖检查。机制、示例与 stage-rig 资产不变。
- v1：初版。
