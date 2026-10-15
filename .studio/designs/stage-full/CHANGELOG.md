# stage-full CHANGELOG

- v5（2026-10-15）：按层分轨替代按模型分档。GUIDE §0 改为背景轨（默认 stage-rig + rig.rebuild，定制背景由高级模型做）与前景轨（普通模型可做），声明台面区、换景时刻与 `data-hf-set` 接口；删除「积木优先 / 手写等价物视为缺陷」，积木降为可选工具；新增 `prop.states` 积木，以数据描述本期专属的多部件、多状态道具，kit-demo 加帆船示范；`stages/plan.md` 轨道镜头表改为先写一句话画面、逐镜写结束状态，规则压到六条正面写法并加入台面区占比；`stages/draft.md` 改为前景自检，加入先静后动与覆盖率线索；stage-rig 墙板与地面标 `data-hf-set`；`thresholds.stage_coverage_min=0.18`，frame-blank 据此报告 `stage_sparse`；`settings_defaults.critic.model` 指定为 `gpt-6.1-sol`（与个人卡一致）。
- v4（2026-10-14）：stage-kit 补齐四个积木 `spot.sweep`、`spot.split`、`tray.sort`、`sign.plate`，舞台动作菜单除 rig.build / rig.recede / hold 外全部有独立积木；`capabilities.checks` 新增 `css-contract`（JS 创建却无样式契约的类名）与 `frame-blank`（Scene 中段舞台层空画面），对应工具侧 `css_contract.py`、`stage_checks.py` 与探针 `stage_visible` 字段。
- v3（2026-10-14）：新增 `stage-kit` 资产六个积木（`disc.scene`、`rig.rebuild`、`prop.stand`、`inset.broll`、`stack.explode`、`slot.text`）与 `example/kit-demo.html` + `example/kit-demo.js` 出场示范；新增 GUIDE §10 积木清单与来源表圆盘换景机制，明确轨道档积木用法、重建变换归属与视频预览限制；更新 `stages/plan.md` 动作参数合同及文档链接、`stages/draft.md` 积木优先与类名覆盖说明。
- v2（2026-10-14）：新增「轨道档」合同。GUIDE §0 分档与 §9 六种做坏方式；`stages/plan.md` 轨道镜头表（表前三行画风/色板/角色、舞台动作菜单、硬规则）；`stages/draft.md` 轨道档自检（三帧截图、计算样式、可见性归属、类名覆盖、位图与声音规则）；卡内 `ANIMATION_PLAN.template.md` 加 `## 轨道镜头表` 节；新增 `tools/check-classes.mjs` 类名覆盖检查。机制、示例与 stage-rig 资产不变。
- v1：初版。
