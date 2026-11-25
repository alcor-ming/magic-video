# Harness 开发纪律

## 工作边界

- 开发仓管理工具源码、规则、模板、Skill、依赖与安装器；生产根保存用户作品、卡片、资产、输出和运行状态。开发与生产按会话角色区分，不按操作系统区分：WSL 制作会话也是生产会话，通过同根 `work-wsl.sh` 操作已授权 Work；开发任务只使用隔离夹具，不读取或修改生产 Current、Work、Variant、接受记录、资产或默认配置。
- 用户卡与工具分开维护；旧 Work 的 vendor、Binding、Lock 与 Accepted Snapshot 保持闭合，不原地覆盖。工具复现使用独立最小副本，不用 hardlink / symlink 暴露冻结源。
- 开发仓不保存生产文稿、媒体、工程或真实作品盘点。个人路径、会话接线和模型偏好见私有来源 `personal/dev-notes.md`（如存在则读取）；该说明不配送。

## 用户卡仓与隔离夹具

- 三仓分工（仓库所有者自用部署）。公开仓管理工具和三张公共卡（`stage-full`、`stage-light`、`history-map`）。私有工具来源管理自用工具及部署锁，`release-sources.json` 的 `cards` 锁定私有卡仓的完整 commit 和卡片 ID。私有卡仓是私人卡的唯一真源。personal 包从锁定 commit 的 Git 对象把卡装进 `.studio/designs/<id>/` 作为受管理文件，部署后仍在卡仓修改。公共包使用者可在自己的 `design_root` 直接创作用户卡。
- 公共卡仅保留脱敏标准版，排除具体 Work、生产历史、运行环境、模型和账号约定。所有者的定制写入私有卡仓的 `<公共卡 ID>-my` 个人卡，通过 `references` 和公共阶段文档复用公共卡，仅记录差异。
- 开发时在临时工具根的 `.studio/.runtime/assets.json` 设置 `design_root`，指向工具根之外的卡仓 clone 或其副本。将 `HYPERFRAMES_AI_ASSET_CONFIG` 指向该文件，清空 `HYPERFRAMES_AI_CONFIG`、`HYPERFRAMES_AI_RESOLVED_CONFIG` 与 `HYPERFRAMES_AI_HOME`，设 `HYPERFRAMES_AI_REVIEW=0`，并清除继承的 `HYPERFRAMES_AI_WORK_ROOT`。通过 `work.main(["--json", "design", ...], root=临时工具根)` 绑定夹具。先用 `design root` 和 `design list` 确认范围，再以 `design validate <id>` 检查 `ok`，用 `design compare <id> --since <rev>` 核对卡片改动和版本。已配置锁定宿主且有可运行示例时，用 `design preview <id>` 检查预览。[隔离夹具回归](../tests/test_design_cli.py) · [命令入口](work.py)
- 参考视频拆解放在卡内 `study/` 或卡仓根级 `studies/<slug>/`。仅收录文字和自制图表，原片以 URL 和时间点引用，排除视频、抽帧和转写全文。研究笔记留在卡仓，卡内 `study/` 不进入 Draft 快照或 personal 包。[用户卡仓说明](../README.md#私有内容)
- `design root` 和 `design compare --since` 只读。卡仓 commit、push、pull 由会话按次获授权后直接执行，工具不封装 Git 写操作。拉取仅用 `--ff-only`，工作树脏或已分叉时报告并停止。发布私人卡先提交卡仓，再更新私有来源的 `cards.commit` / `cards.ids`，部署须另有目标授权。[卡仓版本控制合同](../docs/PRD/PRD_MASTER.md)

## 授权边界

- 不公开发布、不上传内容、不购买额度；不得读取 Cookie、调用未公开接口或点击发布。外部或付费服务必须单独取得用户授权；私有内容转交新外部提供方也须明确授权。
- Plan 列明生成素材用途、数量、风格与 Asset Brief 后，方向批准一并授权这些素材；未列用途或明显超量再确认。`design-taste-frontend` 仅在获批 Asset Brief 明确要求时介入，不查询图片 Prompt 库。
- Draft 与 test-work 不导出视频，包括带声短段、逐帧编码和预渲染镜头；仅生产 Variant 的 Finalize 交付链可生成视频。Studio 受限时记录未验证项，不以导出绕过。
- 部署、安装切换、应用交付、删除不可替代内容以及 commit/tag/push 需要覆盖准确目标的用户授权；测试接受不转为生产接受。Review 不修改生产 Current、源、接受记录或默认配置，不进行生产 Finalize、归档完成或平台草稿。

## 入口与治理

生产阶段定位只见 [.agents/skills/hyperframes-production-workflow/SKILL.md](../.agents/skills/hyperframes-production-workflow/SKILL.md)，生命周期与人工接受见 [.studio/workflow.md](workflow.md)。本版本只提供视频制作；已退役或未知类型只报告，不套用视频操作。

Work 管一期内容，Variant 管独立制作版本，生命周期通过 Work CLI；后台显式绑定 Work/Variant，同一对象同时只允许一个执行者。保留原始来源、正式声音、稳定 Scene/Anchor ID、未受影响内容与接受/Final 快照。登记版本只在独立复制的审阅副本打开，不用 hardlink / symlink 暴露冻结源。

只报告实际结果、变更、阻塞和必要决定；程序、规则、WSL、Windows 原生与生产验收分别报告。Plan 首版可完整展示，后续聚焦变更范围。

## 分支、CI 与公开边界

- 开发使用 `dev/<task>` 分支，经授权推送分支并开 PR。`main` 通过 PR 整合，必需检查通过后由用户合并。
- 公开 CI 在 Ubuntu 和 macOS 矩阵安装测试依赖及 Windows 锁派生的解析器，执行 `python3 -m unittest discover -s tests -q`。[CI 工作流](../.github/workflows/ci.yml)
- 公开边界测试只在 Git 检出上运行。它检查公共卡目录、禁止追踪私人入口和新增旧任务材料、扫描已知个人标记（既有历史文件有白名单），并校验公开源清单仅引用现存、无链接的公开产品文件。公开文档不得加入本机绝对路径、生产根名称或个人账号信息。[公开边界测试](../tests/test_public_boundary.py)
- `validate_package.py` 由 `release` 在打包暂存区执行，以装配后的生产规则和链接为准。正式包在本机使用锁定依赖构建，部署由本机在授权后执行。CI 只运行开发检查。[包校验脚本](../.agents/skills/hyperframes-production-workflow/scripts/validate_package.py)

## Release 与生产根部署

- 生产会话以生产根为工作目录，读取根规则与 `hyperframes-production-workflow` Skill；WSL 会话通过 `work-wsl.sh` 转发，Windows 原生通过根 `work.cmd` 根据自身路径运行同根 `runtime/` 与 `.studio/`；配置从 `.studio/.runtime/` 读取，不经过 `.harness/releases/current`、workspace 或 session，不生成自动 session。生产会话不编辑受管理工具文件。
- 一次命令解析配置一次；长进程固定本次 Work、Variant、资产、依赖与配置输入。继承的旧 session、HOME、AssetRoot 不得重定向工具或 Review；保留必要 Provider 凭据。配置修改仅影响后续命令。
- WSL 从当前受控工作树构建本机包。正式 `harness-YYYY.MM.PATCH` 发行仍要求干净、tag 与 upstream 一致；dirty 候选不冒充稳定发行。
- 获得目标部署授权后，WSL 使用固定 `./release deploy --root <Windows-root>`，不再编写一次性部署脚本。锁一致时发送绑定准确运行时 hash 的工具包，首次安装/锁变化发送完整包；只备份和重写变更文件。成功后默认保留最近两次回滚和当前及前两版登记产物，仅回收新机制拥有且完整的成功副本；历史、失败、未知内容及 Work/资产不自动清理。参数与恢复方式见 README 根目录部署。
- 严格发行包校验检查全部文件、hash、依赖与路径；部署根校验只检查 manifest 拥有的文件，不将 Work、配置或用户 Skill 视为损坏。生产更新只覆盖管理文件；未修改且旧清单拥有、新版本移除的文件才可删除；修改过的退役文件保留字节、记录原路径和摘要并退出活动发现路径，可随备份回滚。继续管理文件的修改仍拒绝覆盖；只有字节已与待部署包完全一致时可接纳，回滚保留原有修改与删除状态。未管理内容不覆盖，不全根 mirror/delete。
- 私有来源替换的根规则和入口须在 `bases` 登记对应公共模板的摘要。公共模板变更后，构建会拒绝旧摘要。先合并公共改动，再更新摘要。`compatibility.product` 须等于产品版本。
- 更新先验证 staging、备份旧管理文件与迁移信息，再更新并最后写完成标记；中断可检测和恢复，损坏组合拒绝启动。复用现有进程记录与最小互斥，更新前停止相关 Studio/render/build 进程，不热换依赖，不新建 daemon。
- 候选部署在独立根，拥有同样的直接入口、独立配置与 Work/Asset/source-copy。Review 不写生产源、Current、接受记录或默认配置，不允许正式 Finalize、归档完成和平台草稿。不将隔离测试变成日常生产前置门。
- 资产遵循 module/media 合同；vendor / Binding / Lock 固定准确依赖，卡库离线不影响已有闭合作品，同身份版本不同内容拒绝覆盖。
- 工具缺口交冻结最小复现给开发会话；组件按工作边界开发。程序回滚不降级 Work schema、不重绑资产；不兼容时保留新数据与可用工具。授权见本文件授权边界。

- 更新完成后重启相关工具进程，Agent 重读根规则；下一条根命令用新版本，无需创建 Harness session。单次命令/长进程固定输入，不宣称整次聊天跨命令固定版本。
- 日常使用统一根目录的 `work.cmd` / `work.ps1`，WSL 生产会话使用 `work-wsl.sh`；`doctor` 报告实际部署身份、规则、内容路径与 Review 范围。新命令或参数仅在实现后写入可执行帮助；Windows 原生结果与 WSL/mock 分别报告。

## 第三方 Skill 上游同步

- 第三方 Skill 安装在 `.agents/skills/` 下被 Git 忽略的目录。同步同一批上游 Skill 时核对安装目录、`skills-lock.json` 的来源和 `computedHash`、以及 `release` 的 `LOCAL_SKILLS`，使需入包的条目按名称对应。打包实际用 `directory_sha256` 校验 `LOCAL_SKILLS` 锁定的目录内容，该摘要与安装器的 `computedHash` 各自维护。[安装锁](../skills-lock.json) · [构建脚本](../release)
- 同步后对照上游目录，清理已下线的本地目录及相应锁项。`dbs-video-extract` 排除在安装与打包之外。重算打包摘要后核对私有来源的 `exclude_skills`，仅保留 `LOCAL_SKILLS` 中唯一且有效的名字，以 `release check-personal --personal-source <私有来源>` 校验。排除清单同步裁剪技能文件、安装锁和部署目标。[部署说明](../README.md#根目录部署)
- 生产按 `capabilities.yaml` 路由。`packaging` 要求 `dbs-title-cover-intro` 处理标题、封面文案与开头，`media-publish-check` 是可选写作能力。冻结的生产包避免通过 `/dbs` 联网查版本或拉取提示词。[能力表](capabilities.yaml)
- 部署时以旧管理清单判断 Skill 文件归属。整项退役的 Skill 目录仍有未受管文件时，部署以 `Unmanaged retired Skill content` 中止。先按授权核对 `.studio/.runtime/deployment.json`，明确迁移残留后再更新。[部署实现](root_deploy.py)

## 开发仓存储盘点与回收

- `python3 dev-storage inspect` 报告 `dist/`、`.studio/.runtime/`、`.git` 与历史兼容区 `.trellis/tasks` 的字节数，以及历史任务占用和回收候选。该历史目录仅为兼容扫描。`cleanup` 默认预览，只有 `cleanup --apply` 才删除，执行时会复查检出范围、符号链接和任务状态。[盘点脚本](../dev-storage)
- 历史任务须同时满足 `work_state` 为 `completed` 或 `cancelled`、`archive_state` 为 `logical_archived`。仅回收 `.zip`、`.zip.sha256`、`unpacked/`、`node_modules/`，保留这些产物之外的收据、日志、`retained.json` 和文档等证据。未归档或状态不可读的任务跳过并报告原因。
- `dist/` 顶层仅回收命名规则匹配的 Windows 发布 ZIP 及其校验文件，`harness`、`candidate`、`local` 按文件名分组，各留修改时间最新的 ZIP。未匹配的包，包括 macOS 和分享包，均保留。`dist/deployments/` 由 `release deploy` 按收据维护。`.studio/.runtime/` 和 `.git` 仅盘点。[回收回归](../tests/test_dev_storage.py)

## 舞台卡分享包导出

- `python3 export-stage-cards [--output DIR] [--zip] [--force]` 默认输出 `dist/magic-video-stage-cards`。按 Git 跟踪清单复制工作树中的 `stage-full` 和 `stage-light`，裁掉 `example/` 与 `example-manifest.json`，不带字体。附 `runtime/motion.js`、`runtime/scene-binding.js`、`spec/visual-design.md`、`spec/hyperframes.md` 和 `LICENSE`。README 与 AGENTS 取自 `share/stage-cards/`，README 的 `@@<卡 ID>@@` 替换为卡片版本。导出脚本和分享模板仅供开发仓使用。[导出实现](../export-stage-cards)
- `rewrites.json` 的每条 `old` 必须在指定文件恰好命中一次。改动卡文档后如有失配，更新精确规则。暂存包扫描 Markdown、JSON 和 JS/MJS 中的已知本机路径、Work 编号、模型与生图服务标记，以及悬空示例引用。`CHANGELOG.md` 仅豁免历史示例引用。任何扫描命中均使导出失败。[重写规则](../share/stage-cards/rewrites.json)
- 已有输出目录仅在指定 `--force` 且 README、AGENTS、`designs/stage-full/design.json` 齐备时替换。`--zip` 生成同名 ZIP，覆盖已有 ZIP 也需 `--force`。归档使用固定文件顺序、时间戳与权限，以相同包名和相同内容重跑得到相同字节。[导出回归](../tests/test_export_stage_cards.py)

## macOS 开发与预览

使用根 `dev-macos` 与 [本机说明](../docs/PRD/macos-development-preview.md)。原生工具、配置与 Review 夹具在忽略的 `.studio/.runtime/macos-preview/`；Python 在 `.venv/`。临时根先解析系统符号链接，内容内链接仍禁止。开发测试中的 Windows runtime 夹具需明确包身份；不以本机宿主替代包目标。Apple Silicon 本地安装使用 `release deploy`；运行时、个人包与验证边界见 [macOS 部署说明](../docs/macos-deployment.md)。

## 宿主浏览器驱动

- 在发行宿主运行的 Node 脚本从锁定 HyperFrames CLI 解析 `puppeteer-core`。`text_inventory.mjs`、`design_preview.mjs` 与 `cover.mjs` 使用 `createRequire(process.env.HYPERFRAMES_CLI)('puppeteer-core')`，`visual_probe.mjs` 用显式传入的 `input.cli` 同样解析。`.studio/parser` 的 `playwright-core` 仅供 `tests/*.mjs` 开发回归使用，宿主不配送解析器的 `node_modules`。[视觉探针](visual_probe.mjs) · [文字盘点](text_inventory.mjs) · [卡片示例](design_preview.mjs) · [封面](cover.mjs)
- 拦截允许内嵌资源的页面请求时，`data:` 直接 `continue()`。可单独 `abort()` Chromium 自取的 `/favicon.ico`，避免把它当成作品的缺失资源。读取 PNG 字节做比较或 Base64 编码时，用 `Buffer.from(screenshot)` 转换 Puppeteer 返回的 `Uint8Array`。seek 完成且资源就绪后再等两帧 `requestAnimationFrame` 截图，确保合成层已呈现。

## Studio 启动与预览排障

- `private_browser_profile` 每次启动前为项目旁的 `.runtime/studio-browser/Default/Preferences` 恢复 `enable_do_not_track: true`，保留可读取的其他偏好。Chrome 回写丢失此标记时无需手工迁移 profile。
- 同一项目的 `preview --background` 复用仍在运行的服务。显式指定与现有服务不同的 `--port` 时，官方 CLI 报 `PreviewServerPortMismatchError`。未指定端口时包装层省略 `--port`，以启动返回的实际端口校验上下文和本机 URL。
- 服务日志在项目父目录的 `.runtime/studio-state/hyperframes/previews/*.log`。Current 的项目父目录是 Variant，注册预览使用审阅副本的父目录。缩略图生成失败仅影响缩略图，服务启动按绑定的项目、上下文和 HTTP 就绪结果判断。[启动适配器](studio_preview.py) · [启动回归](../tests/test_studio_preview.py)

## Python 路径兼容性

旧资产库参考发现的 manifest 对已有目录项使用严格真实路径解析；entry 先严格解析整个路径，只在 `FileNotFoundError` 且末端目录项不存在时允许缺文件回退，并继续检查是否越界。循环链接（含中间目录循环）归 `unsafe_reference_path`，普通不存在的入口仍归 `missing_reference_file`。Python 3.13 的非严格 `Path.resolve()` 不再对循环链接抛错；中间目录循环时 `lexists(entry)` 也可能为假，不能据此跳过严格解析。回归见 [test_asset_discovery.py](../tests/test_asset_discovery.py)，逐项核对直接与中间循环、合法链接、越界及缺文件告警。
