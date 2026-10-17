# Magic Video v4.2 PRD Master

状态：v4.2 开放设计卡与卡内资产脚手架；开发实现与验证以当前任务记录为准，未打包、未部署，Windows 原生和生产验收另记。

当前设计：内置卡＋用户卡双根 Catalog、设计卡/素材卡、跨卡引用与本地化、Draft 文件快照与按 Variant 更新。更新保留工程副本并报告待重新安装资产。现行使用合同见 [README](../../README.md)、[工作流](../../.studio/workflow.md) 和 [资产合同](../../.studio/spec/hyperframes-assets.md)。

开发设计记录（本地、不配送）：[本任务 PRD](../../.trellis/tasks/10-10-hyperframes-docs-discipline-extension/prd.md) 与 [脚手架细则](../../.trellis/tasks/10-10-hyperframes-docs-discipline-extension/scaffold-design.md)。P9 卡片迁移、P10 历史清理另行授权。

现行生产入口与恢复协议见 [生产会话接口](production-session-interface.md)。历史 ledger（含 `component-authoring-m0-m1.md` D8）、v3.x Skill 旧名及客户端/模型分工已被该接口取代；历史原文仅保留背景，不构成现行入口或执行限制。

## 历史版本索引

以下 v3.x 说明保留当时背景；v4.0/v4.1 的设计身份、工作流开关与声线增量继续适用，其旧自用包装配规则由 v4.2 替代。

状态：v3.8.2 独立制作链路、正式 TTS 与 card 删除已在开发仓实现；v3.3 为其余既有制作/工程基线。部署、真实数据迁移、Windows 原生、云合成和听校分别记录，不以开发实现替代。

风险：T3 Parent PRD

日期：2026-09-22；当前范围更新：2026-10-06

v3.8.2 支持 `explainer`（默认）、`showcase`、`math` 与 `english` 四条专属入口、规则、Plan 和检查，共用 Work / Variant、Studio、资产及导出。showcase 舞台／白底角色处理是脱离单期作品的可选工具；数学保留原声／说唱与图解；英语采用原创教学＋TTS，更多文字 Motion、幽默例句、谐音与拼写记忆方法保留为后续方向。公共 TTS 默认火山，提供替代脚本入口，候选生成、正式声音采用与可信对齐各自记录；本期不宣称已接通未选定的本地或其他云引擎。card 专属代码、路由、模板、文档与配送内容删除，不保留兼容实现；生产历史文件和快照不删除，继续内容须显式采用到受支持的新版本。旧配置中的 card 不静默回退。当前合同见 [README](../../README.md#快速开始)、[创作契约](../../.studio/spec/creative.md)、数学链路（仅自用包）和英语链路（仅自用包）。

v3.8 化繁为简的生命周期合同见[制作工作流](../../.studio/workflow.md#归档恢复与停放)、[Final 合同](../../.studio/spec/hyperframes-final.md)及 [README](../../README.md#归档反悔与导航)。本版退出播客制作，保留 Work / Variant 两层；正式导出归档准确版本，全部非空版本集合归档后汇总 Work，可在原版本取消归档。历史成片与收据共同保留；停放保持路径和会话稳定；容量与缓存清理按需执行。退役更新保留用户修改并退出活动入口，运行时按实际消费者裁剪。部署与生产结果仍单独记录。

v3.6.1 增量见 [Opus 动效 B-roll 与 Motion v3](./hyperframes-v361-motion-broll.md)（Motion v3、混合版本闭包、B-roll 插槽与节奏合同已实现并完成 WSL 隔离验证）与 [资产库镜头创作指南](./hyperframes-v361-broll-asset-authoring.md)（已定稿为管理包指南及需求单）。用户已授权部署到统一 Windows 根，实际结果见本次部署收据；生产内容验收与首批库制作不在本任务内。

v3.4.3 增量见 [信息承载、选择性配图与流程更新](./hyperframes-v343-text-imagery.md)：完整上屏信息单元、逐 Scene 配图取舍、Plan 阶段查库与检查、D1 反向核对、场景源/配方发现及只读漏登审计。WSL 实施与隔离回归已完成；未部署，Windows 原生与生产未验证，不包含生产 Work 修正或 Windows 资产补登记。

v3.4.2 基线见 [上屏提炼与持续视觉变化](./hyperframes-v342-visual-outcomes.md)：A1/B1/Q1 与 D1/D2 保留，Plan 信息格式、检查路由与默认配图策略由 v3.4.3 更新（未部署，Windows 原生与生产未验证）。

既有增量合同见 [v3.4.1 补充方案](./hyperframes-v341-supplement.md)：归档同号继任、零 Variant 内容准备与平级账号版本；覆盖 RC2 中必须先绑定账号及 main 优先的旧假设。[RC2 执行方案](./hyperframes-rc2-execution-plan.md) 与 v3.3 制作工程合同仍为其余既有基线。下方 R0–R5 保留 v3.2 实施路径与理由，不重启历史阶段；新制作仍采用三项入口、四阶段与独立 Finalize，归档和恢复按 v3.8 当前合同执行。Remotion 原生验证与生产闭环不得由规则或 mock 测试代替。

## 历史 v3.x 路径

Windows 在 Work-local Scene 安排本期叙事，优先复用带意义且内部联动完整的视觉对象与媒体；既有 helper 和完整 Scene 均可保留，不强制拆解、合并或迁库。内容复杂度不改变 Windows 归属。

Research 记录素材可供性与带强度（锁定 / 倾向 / 灵感）的导演意图，不写布局；Plan 由编排方决定呈现并逐条意图回应。Script / Research 就绪后先整片 Plan，再一个真实 Scene 动态参考，一次方向批准后扩成完整 planned-placeholder Draft，素材齐备后生成最终 Draft。局部布局不自动推广全片，不逐 Scene 审批，不增加占位 Draft 强制接受；单 Scene 参考不授予 full Draft 的 Finalize 权限。

官方 HyperFrames Studio 继续负责预览和渲染；Work 管理身份、版本、反馈和接受。Plan、正式音频 / section_map、Draft、Final 的职责与已有内容权限不变，不新增播放器、内容数据库或审批层。本文件是产品索引，不增加日常必读材料。

## 历史 v3.x 范围

接续本地 M2–M3 源码和画面，不回退公开 HEAD，不重跑 M0–M1。先与 Windows 对齐所选 Work、已有对象和真实工具缺口，在现有任务记录保存保留/轻量封装/延后/局部修复分类，不建设资产数据库。

| 阶段 | 目标与边界 |
|---|---|
| R0 | 核对实际 Work/成果，Windows 修订当前可编辑 Plan，保留原 ID、录音、对齐和接受快照 |
| R1 | 最小真正根候选：runtime/.studio/根配置与直接 work.cmd，无 session；原生检查、管理文件更新及恢复 |
| R2 | Windows 复用一个 Scene 做动态参考；WSL 仅修 cue 解析、剪辑映射、裁取或实际宿主缺口 |
| R3 | 方向批准后 Windows 扩成完整占位 Draft；WSL 仅修 planned placeholders 和范围权限等真实工具问题 |
| R4 | Windows 补素材/最终音频，生成最终 Draft，沿用整片接受与 Final |
| R5 | 原生候选通过后按授权更新生产根、检查数据兼容及当前作品闭环 |

M1 已有 module/media 合同保留，Template/Recipe/Blender 或全库迁移不是本轮前置。音乐分析可选、离线缓存，先用既有 timestamps/section_map；缺音乐或 Blender 不阻塞正常制作。

## 职责

| 对象 | 拥有 | 环境 |
|---|---|---|
| Scene | 当前内容、布局、对象关系、所需 Beat、媒体和相邻衔接 | Windows Work-local |
| Module | 图形对象、GSAP 动作、Three.js / shader 等可复用视觉实现 | Windows Work-local 或已登记 AssetSource |
| Media | 原件、派生物、格式能力及来源 | Windows 资产源或 Work 媒体目录 |
| Template / Recipe | 已声明的布局限制或受控构建输入 / 输出，按需实现 | Windows 资产源；构建协议由工具提供 |
| Harness / 宿主 | 加载、ready / seek、依赖装配、CLI、根配置、安装器 | WSL 唯一工具仓 |
| Plan / Binding / Lock | 视觉决策、工程接线、准确资产与依赖引用 | 现有 Work 生命周期 |

判定依据是职责，不是文件扩展名、复杂度或是否复用。Windows 可开发效果代码，不修改已安装 Harness。WSL 只在明确工具请求的冻结最小私有副本中复现，不直接改生产 Work 或资产源。

## 设计约束

- Scene 只组织需要的节拍，不强制 Opening / Build / Hero / End / Handoff 五阶段或标题、卡片、结果区。
- 通用模块不绑定双画幅；Scene 可重排或计算布局，必须验证真实文字、媒体与阅读时间，不能只拉伸后宣称适配。有限画幅模板保留自身限制。
- 图标、图片、截图和模型可直接成为主体、证据、纹理或辅助对象，不统一限制到固定 Surface；旧组件仍遵守原合同。
- 能独立的背景 / 前景可分开，共享相机、遮挡、光照的空间舞台保持内聚，不强制透明根层。
- 主题只拥有前景字体、配色与卡片外观，与叙事模式、背景、运动和布局独立；不强制双模式 Theme 或前置 Profile，旧 Profile 仅作可选兼容参考，详见 v3.3 合同。
- GSAP 模块写入宿主有限 timeline，不拥有独立播放权；任何时刻可从显式参数与时间重建。模块用法与 preview 宿主不是同一接口。
- 媒体、依赖与字体按实际使用闭合，不把未授权内容放进公开 Harness，不承诺尚未测试的运行时或画幅。

## 资产与冻结

优先登记已有 Windows AssetSource，不创建第二份可写权威源。AssetSource 可编辑；候选、已接纳 AssetStore 包、Work vendor 和 Accepted Snapshot 不可原地改。需要变化时在源中派生并冻结新身份 / 版本。

视觉资产在 Windows 独立打包、验证与精确接纳，不随兼容内容变动重发 Harness；真正改变宿主、合同、依赖装配或工具能力才走 WSL candidate。包只带所选入口、实际依赖、必要用法和证据，不包含私人 Work、凭据或无关全库。

Work 沿用 vendor / Binding / `COMPONENT_LOCK.json`，schema 2 扩展通用资产，旧 schema 1 保留兼容读取；不建平行锁或第二套接纳台账。同身份、同版本不同内容必须拒绝，外部更新不热改已绑定 Work，库离线时闭合副本仍可渲染。Work-local 新代码只做当前作品 QA，不强制先公共化。

## 根目录部署

入口根 `.studio/.runtime/local.json` 是配置真源；一次命令解析并固定本次输入，长进程不随配置变化漂移。不创建 Root Session，也不依赖旧 session 文件。

候选同时隔离 WorkStore、AssetStore、必要试验源副本及缓存；不写生产源、包、接纳记录或全局默认配置，不覆盖稳定 workspace / current / previous。模拟资产接纳只留 Review；候选不允许正式 Finalize、归档完成或平台草稿。

工具根直接部署 runtime/.studio，根配置归 .studio/.runtime；单次命令和长进程固定输入，不创建或要求 Harness session。更新前停止相关进程，复用最小互斥，禁止热换；严格包校验与部署管理文件校验分离，不覆盖用户修改、不删 Work/资产/用户 Skill。候选独立根配置与内容副本，回滚分别检查程序、资产及 Work 兼容；不自动 commit/tag/push 或公开发布。

## 兼容与历史

- 旧公共组件及 Work 的 hash、vendor、Binding、Lock、Accepted Draft、Final 原样保留。
- `migration-ready`、目录出现或技术夹具通过不等于生产接纳；精确资产按当前真实输入和目标环境独立验收。
- 旧 Profile / Background / Component 双画幅整组设计及 42 项 Gallery 只作为历史 backlog，按真实需求提取能力，不再是新资产白名单或本轮交付清单。
- 历史决策保留在[原决策台账](./_ledger/component-driven-motion-vnext.md)；不回写过去记录，不将已替换的五阶段、双画幅或透明根层规则继续施加给新模块。

## PRD 索引

- v3.8.2 独立链路、正式 TTS 与 card 删除：[入口与制作范围](../../README.md#快速开始)、[声音与 Plan 合同](../../.studio/spec/creative.md)、数学链路（仅自用包）、英语链路（仅自用包）。开发仓实现；开发计划留在本地 Trellis，不随产品配送，未声明部署、云合成或原生验收。

- v3.8 化繁为简：[Work / Variant 生命周期与导航](../../.studio/workflow.md#归档恢复与停放)、[Final 与历史收据](../../.studio/spec/hyperframes-final.md)。开发任务计划留在本地 Trellis，不作为产品配送内容。

- [v3.7 流程优化与复盘](./hyperframes-v37-simplify-retro.md)：v3.7.0（产品线档案、导演 Brief 与按 A/B 段分镜、A/B 错相交接、静止与延续测量、可切换 critic、三层设置）已在 WSL 开发仓实现并通过隔离验证；Windows 原生、宿主指定 critic 模型与生产验收未执行；v3.7.1 画面复盘（单片复盘、样片记忆、已知缺陷、跨片汇总、数学诊断修正）已按审查补定在 WSL 开发仓实施并通过隔离验证；Windows 原生、指定 critic 模型看图与生产验收未执行；v3.7.2 内容复盘（第 6 节 C1–C8 与 AC1–AC8，含实验变量、跨期对照与 6.6 数据利用）已在 WSL 开发仓实现并通过合成 fixture、包校验与浏览器 / Studio 验收；Windows 原生与生产验收未执行，未部署；简化设计移到 v3.8。
- [v3.6 showcase 模式、技术提炼与数学系列正式链路](./hyperframes-v36-showcase-math.md)：showcase、math-chain 与 math-kit 开发源码已落地，自动化验收见各自 Trellis 任务；未部署，Windows 原生与生产效果待验。
- [v3.4.1 补充方案](./hyperframes-v341-supplement.md)：已批准并由 WSL 采用的归档同号继任及取消 main 特权；保留完整设计与合成验收，不包含真实生产对象清单。实现、测试和部署结果分别报告。

- [HyperFrames RC2 执行方案](./hyperframes-rc2-execution-plan.md)：仅限视频的创建分流、系列编号、旧 Work 名称/身份迁移、可读导航、账号版本、临时实验及文字节奏；WSL 实现已完成，生产数据迁移仍需单独授权。
- [v3.3 制作与工程合同](./hyperframes-v33-production-contract.md)：既有基线、规则归属、历史兼容与尚需原生/生产证据的边界。

- [Scene 与独立资产合同](./hyperframes-component-motion.md)：类型边界、Windows 内容开发、最小 module/media、精确冻结与旧合同兼容。
- [逐 Scene 复用、缺口 Plan 与官方 Studio](./hyperframes-visual-plan-motion-reuse.md)：保留内容质量、轻量 Plan、局部反馈与真实验收。
- [Windows 工作台与 WSL 工具交接](./hyperframes-windows-workbench-wsl-handoff.md)：固定上下文、Review 隔离及两条交付回路。
- [rnskill 动效分层研究](./_research/rnskill-motion-layering.md)：仅按当前问题读取，不作为强制制作公式。

本 PRD 不扩大生产 Work、资产源、Open Design、Git 或外部发布授权；资产、Plan 与 Draft 分开记录，一句明确回复可以覆盖多个准确对象。


### v4.2 能力与外部来源补充

设计卡以 capabilities 声明所需层、A/B、绑定和专属检查；旧 mode 只读兼容。上游绘制代码固定 commit 后进入独立只读来源区，许可逐文件核对；适配产物是普通用户卡，不引入第三方系统或提示词库。外部 borrowed 来源只能比较，不能自动同步。

非 DOM module 提供完整 texts()；独立 embedded 文字按资产声明的 text_type 授权。字体由卡声明并闭合，第 4/5 层与引擎统一使用；缺字不能接受。Draft 保存文字清单，embedded 文字逐 Scene 人工确认，排版检查标为已委托而非通过。可执行字段与参数以 [.studio/spec/broll-assets.md](../../.studio/spec/broll-assets.md#非-dom-文字与字体) 为准。

### v4.2 personal 包的卡片锁（任务 card-repo-deploy，2026-10-13）

自用版本不再在生产侧编辑卡片：私有来源的 `cards` 锁定私有卡仓的完整 commit 与卡片 ID，personal 包从该 commit 把卡片装进 `.studio/designs/` 作为受管理文件，生产改动在下次部署时拒绝覆盖。首次部署把 `design_root` 中逐字节一致的同 ID 旧副本移到 `designs-retired-<日期>/`，不一致则拒绝。public 包与下述用户卡版本控制根的合同不变。

### v4.2 用户卡的版本控制根（任务 personal-card-source，2026-10-12）

用户卡与工具分三层：公共工具包、自用工具覆盖、用户卡内容。两种工具包都不再配送用户卡；`design_root` 可以直接是一个版本控制工作树（如嵌套在 `asset-library/designs` 内的 Git 仓库），工具发布不触碰它。Catalog、`validate` 与 Draft 快照忽略 `.git/`、卡内 `study/` 与根级 `studies/`，参考视频的拆解笔记可随卡入库而不进入作品。`design root` 与 `doctor` 只读报告该目录的分支、未提交数与远端差异；`design compare <card> --since <rev>` 列出自某修订以来的卡片变化并指出 `design.json.version` 是否递增；受版本控制的卡缺 `CHANGELOG.md` 只警告。工具不执行任何 Git 写操作：提交、推送、拉取由使用者逐次授权执行，拉取只允许快进，脏或分叉的工作树只报告不合并。既有 Work 仍按 Draft 快照与 `variant design-update` 跟随卡片；首次把现有用户卡目录纳入版本控制是使用者单独授权的一次性操作。
