# Magic Video 仓库开发（Claude Code）

## 知识索引

- 工作边界与授权：[.studio/AGENTS.md](.studio/AGENTS.md)。开发前读取，包含按会话角色划分的开发与生产职责、生产隔离、授权和发布部署契约。
- 个人开发说明：私有来源 `personal/dev-notes.md`（如存在则读取），记录本机接线与个人偏好，不属于公开产品合同，不配送。
- 开发流程：[AGENTS.override.md](AGENTS.override.md)、[.trellis/workflow.md](.trellis/workflow.md)、[.trellis/AGENTS.md](.trellis/AGENTS.md)。本地开发入口、任务与验证流程，以及数据库、沙盒、WSL 互操作、收尾摘要排障与历史归档对账知识、三仓卡片更新顺序与卡仓隔离夹具配方、GitHub 分支与 CI 流程；仅用于开发仓，不随产品配送。
- 业务背景与需求：[README.md](README.md)、[docs/PRD/PRD_MASTER.md](docs/PRD/PRD_MASTER.md)。产品能力、当前需求与历史方案索引，按主题查阅。
- 架构与技术方案：[docs/PRD/](docs/PRD/)、[.studio/spec/runtime-interfaces.md](.studio/spec/runtime-interfaces.md)。职责划分、资产与部署设计、运行时接口；以 PRD 主索引标明的当前合同为准。
- 通用组件与规范：[.studio/spec/hyperframes-assets.md](.studio/spec/hyperframes-assets.md)、[.studio/spec/broll-assets.md](.studio/spec/broll-assets.md)、[.studio/templates/](.studio/templates/)。资产复用、组件创作与文档模板。
- 三方对接：[README.md](README.md)、[.studio/spec/hyperframes.md](.studio/spec/hyperframes.md)。TTS / ASR 接入、对齐数据完整性、HyperFrames 唯一宿主实现。
- 业务规范：[.studio/workflow.md](.studio/workflow.md)、[.studio/spec/](.studio/spec/)。Work / Variant 生命周期、创作、视觉、隐私与交付规则；开发验证使用隔离副本。

### 知识落盘规范

- 根目录 AGENTS.md 和 CLAUDE.md 只保留索引概要（路径 + 1～2 句摘要），不在此堆细节。
- 当对话中出现可复用的规则、兼容性、排障结论或项目知识时，必须就近落盘到对应模块的 AGENTS.md，并同步更新根目录 AGENTS.md 和 CLAUDE.md 中的知识索引，以模块内容为准；已有详细规范保留原位，由模块 AGENTS.md 链接。
- 发现知识索引过期、路径失效或摘要不准确时，主动修正，并同步两个根索引。
