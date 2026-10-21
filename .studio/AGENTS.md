# Harness 开发纪律

## 工作边界

- 开发仓管理工具源码、规则、模板、Skill、依赖与安装器；生产根保存用户作品、卡片、资产、输出和运行状态。开发与生产按会话角色区分，不按操作系统区分：WSL 制作会话也是生产会话，通过同根 `work-wsl.sh` 操作已授权 Work；开发任务只使用隔离夹具，不读取或修改生产 Current、Work、Variant、接受记录、资产或默认配置。
- 用户卡与工具分开维护；旧 Work 的 vendor、Binding、Lock 与 Accepted Snapshot 保持闭合，不原地覆盖。工具复现使用独立最小副本，不用 hardlink / symlink 暴露冻结源。
- 三仓分工（仓库所有者自用部署）：公开仓管工具与固定的两张公共卡；私有工具来源管自用工具与部署锁，其 `release-sources.json` 的 `cards` 锁定私有卡仓的完整 commit 与卡片 ID；私有卡仓是私人卡唯一真源。personal 包从锁定 commit 的 Git 对象把私人卡装进 `.studio/designs/<id>/` 作为受管理文件，该自用部署的生产侧不再编辑卡片。公共包使用者（含在 Windows 侧编辑的第三方）不受此限，仍在 `design_root` 直接创作用户卡。开发会话在卡仓 clone 上、通过 `design_root` 指向该 clone 的隔离夹具创作与校验卡片，不写生产 `design_root`。工具不封装 Git 写操作。私有来源替换的根规则与入口须在 `bases` 登记对照的公共模板摘要，公共模板一变构建即拒绝，先合并公共改动再更新摘要；`compatibility.product` 须等于产品版本。公共卡只保留脱敏标准版，不写具体 Work、生产历史、运行环境、模型或账号约定；所有者的定制放私有卡仓的 `<公共卡 ID>-my` 个人卡，用 `references` 与公共阶段文档复用公共卡，只写差别。
- 开发仓不保存生产文稿、媒体、工程或真实作品盘点。个人路径、会话接线和模型偏好见私有来源 `personal/dev-notes.md`（如存在则读取）；该说明不配送。

## 授权边界

- 不公开发布、不上传内容、不购买额度；不得读取 Cookie、调用未公开接口或点击发布。外部或付费服务必须单独取得用户授权；私有内容转交新外部提供方也须明确授权。
- Plan 列明生成素材用途、数量、风格与 Asset Brief 后，方向批准一并授权这些素材；未列用途或明显超量再确认。`design-taste-frontend` 仅在获批 Asset Brief 明确要求时介入，不查询图片 Prompt 库。
- Draft 与 test-work 不导出视频，包括带声短段、逐帧编码和预渲染镜头；仅生产 Variant 的 Finalize 交付链可生成视频。Studio 受限时记录未验证项，不以导出绕过。
- 部署、安装切换、应用交付、删除不可替代内容以及 commit/tag/push 需要覆盖准确目标的用户授权；测试接受不转为生产接受。Review 不修改生产 Current、源、接受记录或默认配置，不进行生产 Finalize、归档完成或平台草稿。

## 入口与治理

生产阶段定位只见 [.agents/skills/hyperframes-production-workflow/SKILL.md](../.agents/skills/hyperframes-production-workflow/SKILL.md)，生命周期与人工接受见 [.studio/workflow.md](workflow.md)。本版本只提供视频制作；已退役或未知类型只报告，不套用视频操作。

Work 管一期内容，Variant 管独立制作版本，生命周期通过 Work CLI；后台显式绑定 Work/Variant，同一对象同时只允许一个执行者。保留原始来源、正式声音、稳定 Scene/Anchor ID、未受影响内容与接受/Final 快照。登记版本只在独立复制的审阅副本打开，不用 hardlink / symlink 暴露冻结源。

只报告实际结果、变更、阻塞和必要决定；程序、规则、WSL、Windows 原生与生产验收分别报告。Plan 首版可完整展示，后续聚焦变更范围。

## Release 与生产根部署

- 生产会话以生产根为工作目录，读取根规则与 `hyperframes-production-workflow` Skill；WSL 会话通过 `work-wsl.sh` 转发，Windows 原生通过根 `work.cmd` 根据自身路径运行同根 `runtime/` 与 `.studio/`；配置从 `.studio/.runtime/` 读取，不经过 `.harness/releases/current`、workspace 或 session，不生成自动 session。生产会话不编辑受管理工具文件。
- 一次命令解析配置一次；长进程固定本次 Work、Variant、资产、依赖与配置输入。继承的旧 session、HOME、AssetRoot 不得重定向工具或 Review；保留必要 Provider 凭据。配置修改仅影响后续命令。
- WSL 从当前受控工作树构建本机包。正式 `harness-YYYY.MM.PATCH` 发行仍要求干净、tag 与 upstream 一致；dirty 候选不冒充稳定发行。
- 获得目标部署授权后，WSL 使用固定 `./release deploy --root <Windows-root>`，不再编写一次性部署脚本。锁一致时发送绑定准确运行时 hash 的工具包，首次安装/锁变化发送完整包；只备份和重写变更文件。成功后默认保留最近两次回滚和当前及前两版登记产物，仅回收新机制拥有且完整的成功副本；历史、失败、未知内容及 Work/资产不自动清理。参数与恢复方式见 README 根目录部署。
- 严格发行包校验检查全部文件、hash、依赖与路径；部署根校验只检查 manifest 拥有的文件，不将 Work、配置或用户 Skill 视为损坏。生产更新只覆盖管理文件；未修改且旧清单拥有、新版本移除的文件才可删除；修改过的退役文件保留字节、记录原路径和摘要并退出活动发现路径，可随备份回滚。继续管理文件的修改仍拒绝覆盖；只有字节已与待部署包完全一致时可接纳，回滚保留原有修改与删除状态。未管理内容不覆盖，不全根 mirror/delete。personal 来源的 `exclude_skills` 同步裁剪技能文件、锁与部署目标，见 README 根目录部署。
- 更新先验证 staging、备份旧管理文件与迁移信息，再更新并最后写完成标记；中断可检测和恢复，损坏组合拒绝启动。复用现有进程记录与最小互斥，更新前停止相关 Studio/render/build 进程，不热换依赖，不新建 daemon。
- 候选部署在独立根，拥有同样的直接入口、独立配置与 Work/Asset/source-copy。Review 不写生产源、Current、接受记录或默认配置，不允许正式 Finalize、归档完成和平台草稿。不将隔离测试变成日常生产前置门。
- 资产遵循 module/media 合同；vendor / Binding / Lock 固定准确依赖，卡库离线不影响已有闭合作品，同身份版本不同内容拒绝覆盖。
- 工具缺口交冻结最小复现给开发会话；组件按工作边界开发。程序回滚不降级 Work schema、不重绑资产；不兼容时保留新数据与可用工具。授权见本文件授权边界。

- 更新完成后重启相关工具进程，Agent 重读根规则；下一条根命令用新版本，无需创建 Harness session。单次命令/长进程固定输入，不宣称整次聊天跨命令固定版本。
- 日常使用统一根目录的 `work.cmd` / `work.ps1`，WSL 生产会话使用 `work-wsl.sh`；`doctor` 报告实际部署身份、规则、内容路径与 Review 范围。新命令或参数仅在实现后写入可执行帮助；Windows 原生结果与 WSL/mock 分别报告。
