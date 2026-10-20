# HyperFrames Production Workflow v2.1.0

这是 Magic Video 创作 Harness 的薄路由 Skill。产品工作流、规范、Recipe 和模板由 `.studio/` 管理。下载视频支持 DBS 或逐字保留路径；Research 提供候选，Plan 选材并写明实际屏幕文字。动画型/文字型独立于 Template/Profile。整片 Plan 与一个真实 Scene 动态参考一次方向批准，再扩完整占位 Draft；素材齐备后注册 Studio Draft、打开准确版本并接受，无整片 MP4 前置。Final 从接受快照正式渲染，编码 QA 与收据完成后归档准确 Variant，至少一个版本且全部已归档时汇总 Work；局部方案不自动套全片，按实际变化范围复核。

保留内容：

- `SKILL.md`：最小上下文与阶段路由；
- `profile-registry.json`：三套稳定 Profile 的接入表；
- `references/hyperframes-design-profile-pack-v0.1.0/`：Profile 真源；
- `scripts/validate_package.py`：结构和 JSON 校验。

v2 普通运行不加载图片生成、Prompt 库、Taste Skill、字幕、Examples 或 Migration。作品生命周期通过根目录 `./work` 管理。取消归档在原 Variant 继续，保留其他版本与历史；当前仅提供视频制作，空间盘点和缓存清理按需使用 CLI。
