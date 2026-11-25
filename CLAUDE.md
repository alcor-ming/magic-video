# Magic Video 仓库开发（Claude Code）

## 知识索引

- 开发前读取会话角色、生产隔离、授权和入口治理规则。[.studio/AGENTS.md](.studio/AGENTS.md)
- 个人开发说明见私有来源 `personal/dev-notes.md`（如存在）。该说明仅记录本机接线和偏好，不随产品配送。
- Apple Silicon 使用 `dev-macos` 配置原生工具、隔离 Review 与执行检查。宿主浏览器驱动和 Studio 启动排障见开发纪律。[本机开发](docs/PRD/macos-development-preview.md) · [宿主浏览器驱动](.studio/AGENTS.md#宿主浏览器驱动) · [Studio 启动与预览排障](.studio/AGENTS.md#studio-启动与预览排障)
- 开发分支、CI、公开边界和第三方 Skill 同步按开发纪律执行。Apple Silicon 本地安装使用 `release deploy`，生产根使用 `./work`。[分支、CI 与公开边界](.studio/AGENTS.md#分支ci-与公开边界) · [Release 与生产根部署](.studio/AGENTS.md#release-与生产根部署) · [第三方 Skill 上游同步](.studio/AGENTS.md#第三方-skill-上游同步) · [macOS 部署说明](docs/macos-deployment.md)
- 开发产物回收和舞台卡分享包导出各有独立入口与保护边界。[开发仓存储盘点与回收](.studio/AGENTS.md#开发仓存储盘点与回收) · [舞台卡分享包导出](.studio/AGENTS.md#舞台卡分享包导出)
- 用户卡的三仓分工、临时开发夹具和 Git 授权见模块说明。[用户卡仓与隔离夹具](.studio/AGENTS.md#用户卡仓与隔离夹具)
- 产品能力、当前需求和历史方案按主题查阅。[README.md](README.md) · [PRD 主索引](docs/PRD/PRD_MASTER.md)
- 架构、资产、部署和运行时接口以 PRD 主索引标明的当前合同为准。[PRD](docs/PRD/) · [运行时接口](.studio/spec/runtime-interfaces.md)
- 参考发现须区分循环符号链接与普通缺文件，兼容 Python 3.13 的路径解析行为。[Python 路径兼容性](.studio/AGENTS.md#python-路径兼容性)
- 资产复用、组件创作和文档模板见通用规范。[HyperFrames 资产](.studio/spec/hyperframes-assets.md) · [B-roll 资产](.studio/spec/broll-assets.md) · [模板](.studio/templates/)
- 三方对接涵盖 TTS / ASR、对齐数据、HyperFrames 宿主与生图角色登记。BGM 和 SFX 使用工程内本地音轨。[README.md](README.md) · [HyperFrames](.studio/spec/hyperframes.md) · [运行时接口](.studio/spec/runtime-interfaces.md)
- Work / Variant 生命周期、创作、视觉、隐私与交付遵循业务规范，开发验证使用隔离副本。[工作流](.studio/workflow.md) · [业务规范](.studio/spec/)

### 知识落盘规范

- 根目录 AGENTS.md 和 CLAUDE.md 只保留索引概要（路径 + 1～2 句摘要），不在此堆细节。
- 当对话中出现可复用的规则、兼容性、排障结论或项目知识时，必须就近落盘到对应模块的 AGENTS.md，并同步更新根目录 AGENTS.md 和 CLAUDE.md 中的知识索引，以模块内容为准；已有详细规范保留原位，由模块 AGENTS.md 链接。
- 发现知识索引过期、路径失效或摘要不准确时，主动修正，并同步两个根索引。
