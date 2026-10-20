# stage-light CHANGELOG

- v3（2026-10-20，媒体支线）：解禁 BGM——新增字段 `bgm.enabled`（卡默认 false，由账号开启）与 `bgm.policy`（账号的曲库与情绪偏好）；BGM 只用开源曲库的现成曲目（`work component import-bgm` 带许可导入），不合成。音效新增 earshot 音效库来源。封面仍按账号模板合成，账号角色库图片改由生图 MCP 生成并用 `work account character add` 登记。GUIDE §7 改为「声音与封面」，`stages/draft.md` 同步。
- v2（2026-10-20）：复用 stage-full 的动作包。新增 `MOTION.md`，前景七个动作用 `HarnessMotion.create({ card: 'stage-full' })`，默认背景用同一个全屏纸板背景动作（`panels: 2`），不用圆盘进阶背景；`design.json` 引用 `stage-full/stage-motion`；GUIDE 与 `stages/plan.md`、`draft.md`、`export.md` 写明 Work 里的安装、加载顺序与工程本地资产。示例保持原样，作为动作标准化之前的编排示范。
- v1：初版。
