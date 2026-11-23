# stage-light CHANGELOG

- v7（2026-11-23）更新 A/B-roll 编排与主体默认值，明确分镜索引、Rolls 接线及三种文字落点。
- v6（2026-11-21）：文字归属文档按世界里、页面里或屏幕上的落点改写，A1 与阅读保护引用通用规范；同步 Plan 说明、主体描述与文档摘要。capabilities、积木参数、运行时与示例行为不变。
- v5（2026-10-30）：声音工具移出公开仓。删去 `generate-sfx`、`import-bgm` 引用；音轨以 `data-audio-role="stem"` 放进工程，`sfx.*` / `bgm.*` 配置字段不变。
- v4（2026-10-21）：去本地化与去绑定。文档删去运行环境细节；BGM 写法改为按 `bgm.enabled` / `bgm.policy` 配置，封面交由工具封面合同，不再写账号模板与角色库生图流程。行为与示例画面不变。
- v3（2026-10-20，媒体支线）：解禁 BGM——新增字段 `bgm.enabled`（卡默认 false，由配置开启）与 `bgm.policy`（曲库与情绪偏好）；BGM 只用开源曲库的现成曲目（`work component import-bgm` 带许可导入），不合成。音效新增 earshot 音效库来源。GUIDE §7 改为「声音与封面」，`stages/draft.md` 同步。
- v2（2026-10-20）：复用 stage-full 的动作包。新增 `MOTION.md`，前景七个动作用 `HarnessMotion.create({ card: 'stage-full' })`，默认背景用同一个全屏纸板背景动作（`panels: 2`），不用圆盘进阶背景；`design.json` 引用 `stage-full/stage-motion`；GUIDE 与 `stages/plan.md`、`draft.md`、`export.md` 写明 Work 里的安装、加载顺序与工程本地资产。示例保持原样，作为动作标准化之前的编排示范。
- v1：初版。
