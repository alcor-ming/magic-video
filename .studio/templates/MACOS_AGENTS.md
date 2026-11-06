# HyperFrames 创作根

本目录是可移动的 HyperFrames 创作根。Agent 使用本根 `./work`，运行同根 `runtime/` 与 `.studio/`，配置读取 `.studio/.runtime/local.json`；`./work doctor` 查看实际身份与 Review 范围。根目录存在 `AGENTS.local.md` 时同时读取其中的本机服务与用户规则。

完整的通用使用、流程与授权规则见 [.studio/AGENTS.md](.studio/AGENTS.md)；生命周期与三道人工门见 [.studio/workflow.md](.studio/workflow.md)；五层、A/B-roll、字幕与声音见 [.studio/spec/visual-design.md](.studio/spec/visual-design.md)；运行接口见 [.studio/spec/runtime-interfaces.md](.studio/spec/runtime-interfaces.md)。本文件只保留可移动入口，不复制授权边界。

设计身份来自内置卡与用户卡 Catalog，素材卡不进入选择列表。随包安装的卡位于 `.studio/designs/`，是受管理文件、只读，公共包内置 `stage-full`、`stage-light` 两张；用户卡由根配置 `design_root` 定位，默认 `asset-library/designs`。同 ID 冲突拒绝，旧身份只读并提示重选。 单一流程为 Script → Research →（可选）优化 → 文案门 → Plan → Plan 门 → Draft+封面 → Draft 门 → MP4+封面；导出成功后 Variant 保持 active。

## 资产开发

在用户卡 `assets/<asset-id>/` 编写资产与 `asset.json`，按单资产合同校验；不要求 pack/accept。跨卡使用先声明 `references`，要改造时本地化并保留许可与来源记录。已有 Work 使用工程 vendor/lock；更新卡片快照保留工程副本，报告待重新安装资产。创作入口见设计卡创作 Skill，命令以当前 CLI 帮助为准。

生产会话以本根为 cwd，读取 `.agents/skills/hyperframes-production-workflow/SKILL.md`。macOS 原生使用 `./work`；开发会话只使用隔离夹具。执行者可能无法看图：返回诊断 JSON、seek 检查结果及截图路径，需要人工动态观看或试听的项目标为未验证。
