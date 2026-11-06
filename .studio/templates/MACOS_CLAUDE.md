# HyperFrames Claude 入口

本文件适用于 Claude Code 使用本根，不增加发布、外部服务、部署或接受权限。完整的通用使用、流程与授权规则见 [.studio/AGENTS.md](.studio/AGENTS.md)；生命周期与三道人工门见 [.studio/workflow.md](.studio/workflow.md)；创作指南见 [.studio/spec/visual-design.md](.studio/spec/visual-design.md)；运行接口见 [.studio/spec/runtime-interfaces.md](.studio/spec/runtime-interfaces.md)。根目录存在 `AGENTS.local.md` 时同时读取。

只使用本根 Work CLI 操作 Work/Variant，不手改生产 Work、Current、接受记录、配置或已部署工具，不另起 Studio 或渲染器；同一 Work/Variant 同时只允许一个执行者。资产创作在用户卡的 `assets/` 中完成，直接编辑并校验；跨卡引用只读，改造先本地化；Draft 快照与接受由 CLI 管理；画面与内容复盘只写各自允许范围，不导出视频、不调用外部服务。报告实际结果与未验证项。

生产会话以本根为 cwd，读取 `.agents/skills/hyperframes-production-workflow/SKILL.md`。macOS 原生使用 `./work`；开发会话只使用隔离夹具。执行者可能无法看图：返回诊断 JSON、seek 检查结果及截图路径，需要人工动态观看或试听的项目标为未验证。
