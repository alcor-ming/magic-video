# Magic Video 仓库开发

## 知识索引

- 工作边界与授权：[.studio/AGENTS.md](.studio/AGENTS.md)。开发前读取，包含按会话角色划分的开发与生产职责、生产隔离、授权和发布部署契约。
- 个人开发说明：私有来源 `personal/dev-notes.md`（如存在则读取），记录本机接线与个人偏好，不属于公开产品合同，不配送。
- 本机开发与预览：[docs/PRD/macos-development-preview.md](docs/PRD/macos-development-preview.md)、[.studio/AGENTS.md](.studio/AGENTS.md)。Apple Silicon 使用 `dev-macos` 配置原生工具、隔离 Review 与执行检查；正式渲染及部署不在此阶段范围。当前公开仓不含旧的 AGENTS.override.md 或 .trellis 工作流入口，不按失效路径启动流程。
- 业务背景与需求：[README.md](README.md)、[docs/PRD/PRD_MASTER.md](docs/PRD/PRD_MASTER.md)。产品能力、当前需求与历史方案索引，按主题查阅。
- 架构与技术方案：[docs/PRD/](docs/PRD/)、[.studio/spec/runtime-interfaces.md](.studio/spec/runtime-interfaces.md)。职责划分、资产与部署设计、运行时接口；以 PRD 主索引标明的当前合同为准。
- Python 路径兼容性：[.studio/AGENTS.md](.studio/AGENTS.md#python-路径兼容性)。参考发现须区分循环符号链接与普通缺文件，兼容 Python 3.13 的路径解析行为。
- 通用组件与规范：[.studio/spec/hyperframes-assets.md](.studio/spec/hyperframes-assets.md)、[.studio/spec/broll-assets.md](.studio/spec/broll-assets.md)、[.studio/templates/](.studio/templates/)。资产复用、组件创作与文档模板。
- 三方对接：[README.md](README.md)、[.studio/spec/hyperframes.md](.studio/spec/hyperframes.md)、[.studio/spec/runtime-interfaces.md](.studio/spec/runtime-interfaces.md)。TTS / ASR 接入、对齐数据完整性、HyperFrames 唯一宿主实现；生图角色登记的命令合同；公开工具不生成、不混合音频（音轨以 `data-audio-role="stem"` 入工程）。
- 业务规范：[.studio/workflow.md](.studio/workflow.md)、[.studio/spec/](.studio/spec/)。Work / Variant 生命周期、创作、视觉、隐私与交付规则；开发验证使用隔离副本。

### 知识落盘规范

- 根目录 AGENTS.md 和 CLAUDE.md 只保留索引概要（路径 + 1～2 句摘要），不在此堆细节。
- 当对话中出现可复用的规则、兼容性、排障结论或项目知识时，必须就近落盘到对应模块的 AGENTS.md，并同步更新根目录 AGENTS.md 和 CLAUDE.md 中的知识索引，以模块内容为准；已有详细规范保留原位，由模块 AGENTS.md 链接。
- 发现知识索引过期、路径失效或摘要不准确时，主动修正，并同步两个根索引。

Apple Silicon 本地部署入口为 `release deploy`，生产根使用 `./work`。准备与恢复见 [macOS 部署说明](docs/macos-deployment.md)。
