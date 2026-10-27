# 创作工作流与治理

环境、权限与运行边界见 [AGENTS.md](AGENTS.md)。创作指南见 [visual-design.md](spec/visual-design.md)，来源与修订见 [creative.md](spec/creative.md)。本文件按需加载，维护单一流程、独立人工门与生命周期；命令参数和合法状态以当前 CLI 帮助与错误信息为准。

制作走单一流程：Script → Research →（可选）优化 → 文案门 → Plan → Plan 门 → Draft+封面 → Draft 门 → MP4+封面。三道人工门由独立工作流开关分别控制；Draft 审查为建议式，不阻断登记或继续；没有单独的 Final 阶段。导出成功后 Variant 保持 active 与可继续修改，归档与重开显式执行；正式导出把 MP4 与封面复制到按系列 / Work / Variant 分类的聚合导出架，只追加、带 hash、幂等、复制失败可重试且不重渲染。

## 对象与用途

先区分讨论、继续现有 Work/Variant、同内容目标的独立 Variant、临时实验和新生产目标。普通修订留在当前 Variant；同一期新账号适配建立独立 Variant；只有用户明确要求旧归档实体只读、另建同一期实体时使用继任。用途有实质歧义才询问，不从 URL、缺账号或缺 Final 推断实验。

账号属于 Variant；Work 级 Script/Research 由各 Variant 共享，各 Variant 独立维护 Plan、工程与接受结果。显式内容分支按 CLI 定位。新视频显式指定 `--purpose standard|ip|test`，生产用途指定系列；账号与制作版本可以稍后确定。视觉主题、背景和画幅按所选设计卡配置，动作用工具动作与卡片动作包（卡内 `MOTION.md`）；设计身份由设计卡显式选择（公共包 `stage-full`、`stage-light`；其他设计由用户卡目录提供），旧身份只读并提示重选，不隐式套用 `explainer`。Theme 负责字体、语义色与表面，不决定模式、布局或 cue；Variant 使用冻结外观。

WorkStore 按系列物理分层：`works/<系列ID>/<Work>/`，临时实验在 `works/test/`，未登记系列的 Work 在 `works/_未归系列/`；归档与停放只是 Work 内标记，不移动目录，`series move` 会把 Work 目录一并移到新系列文件夹（存活 Studio 先 `preview studio stop`）。旧版 `works/active|parked|archive/` 布局以 `work migrate layout` 预览、`--apply` 执行一次性迁移，可重复执行；Studio 记录是写入它的运行时的绝对路径，生产根须用 Windows 侧 `work.cmd` 执行，WSL 下会拒绝；迁移报告列出仍写着旧绝对路径的工作文件，由使用者下次使用时改正，冻结快照与证据不改写。系列经验规则即系列文件夹内的 `works/<系列ID>/AGENTS.md`，以 `work series rules show <id>` 读取、`work series rules put <id> --file -` 从标准输入整份替换（也可给文件路径；`series put <id> --file -` 同样从标准输入读配置 JSON；不要在 WorkStore 根目录落请求草稿；旧版与历史留在 control-plane）、`work series rules delete <id>` 撤下当前规则（正文转入历史）；`work status` 的 `series_rules` 给出所属系列规则路径。读写一律经系列 ID 的 CLI，不从 Work 的上级目录或链接位置推断，开始 Script 前读取；复盘只写回已成立、可复用的结论，合并重复、修正被推翻条目，不堆日志或猜测，也不自动变成系列默认配置。不再使用的系列以 `work series delete <id>` 退役：仍有任何 Work（含归档）归属时拒绝，须先 `series move`；系列文件夹除 `AGENTS.md` 外仍有内容时也拒绝；其他系列文件夹里没有 `WORK.md` 的目录不算 Work，不阻断；配置、配置历史与规则整体移入 WorkStore `control-plane/deleted/series/` 并移除空系列文件夹，不硬删，同 ID 可重新创建且版本从 1 起。系列 ID 不可改名，需要新 ID 时新建系列、逐个 `series move` 后删除旧系列。不再使用的账号以 `work account delete <id>` 退役：任一 Variant（含归档）冻结了该账号、或任一系列的 `accounts` 列出它时拒绝；系列文件夹里没有 `WORK.md` 的目录不算 Work，不阻断；配置、配置历史与账号资产（封面角色库）整体移入 `control-plane/deleted/account/`，不硬删，同 ID 可重新创建且版本从 1 起。账号 ID 同样不可改名：新建账号、把系列 `accounts` 改挂新账号，已冻结旧账号的 Variant 与导出保持原样，旧账号保留作历史。

设计身份与可改默认值以所选设计卡为准（内置卡或用户卡目录）：Plan 模板、阶段规则、Brief 字段、主体默认值、资产范围与豁免随卡片维护；Variant 创建时记录身份，制作中读取实时卡片；提交 Draft 时复制卡片文件及引用资产并记录摘要。status 与预览提示卡片变化，`variant design-update` 显式更新本 Variant 快照，保留工程副本并报告待重新安装资产；重新提交 Draft 后沿用原接受流程。已有旧 JSON 快照继续按原语义读取。旧 `explainer/math-rap` 及其他仍支持链路的冻结身份按原语义读取，不自动迁移。card 已移除制作与渲染支持，历史文件、接受快照与成片保留；继续内容须显式采用到受支持的新版本，不配送兼容实现。`talking_head` 是 Template。本版本只提供视频制作；已退役或未知 Work 不继续制作，也不阻断无关视频的定位。

主镜头资源按设计卡资产范围和获批 Asset Brief 制作，用户接受边界保持；交接不改变 Current 或接受记录，不按模型划分制作权限。会话按 `--context` 与 `HYPERFRAMES_CONTEXT` 隔离，不同对象可并行、同一准确对象互斥，见授权规则。

实验采用结果先复制或冻结到目标 Work；来源关系不等于接受。保留稳定 Scene/Anchor ID、正式声音、已有成果和冻结历史。更换主题、叙事结构或确认观点属于方向变化，只确认受影响部分。

## 1. 内容准备

复用合格 Script、录音、对齐与材料。Script 只来自用户提供的文稿或用户撰写；Script 为空时整理用户文稿，不提供下载或转录提取，正文改动须用户批准。用 `work script text` 排除 Scene 索引，避免重复对齐处理。Script 稳定后通过 `work name` 补语义标题。

英语使用原创教学稿和公共 TTS。TTS 提供方通过配置选择、不静默回退；先生成候选，再明确采用正式声音，最后以提供方可信原生时间证据完成字词对齐，缺少原生时间证据时明确报告缺失。未对齐处不估时，候选生成不等于声音采用或内容接受。正文或声音变化仅重做受影响的新制作范围，保留旧接受快照。

Research 按段落或 Anchor 记录事实与来源、B-roll 候选（可定位位置及取得状态）、比喻与例子。先理解完整段落，再定点补具体材料缺口；它不是另一份脚本或必上屏清单。事实冲突交用户判断相关表达，不擅改原音。共享输入变化只更新受影响研究及引用。

文案讨论与 Plan 按决策类型分工：Script 定说什么，Research 定有什么，导演意图定想要的感觉，Plan 定怎么呈现。Research 每段可写“素材可供性”，只说明材料能撑起什么画面（可对比数据、已取得实拍、强比喻），不写布局、镜头或动画。用户构想写入 Research 的“导演意图”，标 `锁定`（必须实现）、`倾向`（默认采纳，可改写并说明）或 `灵感`（参考）；讨论或研究产生的布局想法只记为 `灵感`。导演意图属于 Work 级共享输入，随 Research 修订冻结进 Plan。

`PACKAGE.md` 仅按交付需求生成，**不是视频设计、制作或接受的前置**；新建版本不生成空包装占位，材料和运行目录在首次需要时创建。

## 2. 整片设计

Plan 模板与适用检查从冻结档案读取；形式豁免不扩大为接受豁免。
Plan 阶段按用途运行 `work component list --query <用途> --include-references` 查包、场景源与配方，按结果的 `detail.argv`（在本根 work 入口后传入参数）查看准确接口，再选择复用、派生或自制。单查场景源或配方可直接用 `--kind scene-source` / `--kind recipe`；裸 list 保留参考项默认隐藏的包目录行为。场景源与配方不可安装，按详情中的源入口或配方说明使用，不猜派生命令。组件可在隔离开发任务或生产会话授权的可编辑源编写；生产内容制作保持根规则边界。

通用 explainer 的新 `plan_format=3.7.0` 按 [创作指南](spec/visual-design.md) 填导演 Brief 与按 A/B 段的分镜表，每段一个观看任务。Research 有导演意图时，Brief 后的“意图回应”逐条写采纳、改写或未采纳及理由；`锁定` 不可未采纳，不可行时向用户报告准确冲突；本 Variant 专属意图来源写 `Variant`。锁定项是否落实由用户在 Plan 门审查，不新增工具检查。编排中发现材料缺口时回 Research 定点补材料；只补材料、不改 Script 正文时不重开文案门。逐 Scene 保留 `screen`、素材、声音与刻意停顿例外，不再写事件表。showcase、math 与 english 使用专属 Plan，不强加通用 Brief、角色／生图或 A/B 配额；数学保留符号和图形职责，英语保留教学要素、拼写合词与阅读节奏。参考机制 ID 见 [机制目录](mechanisms.yaml)。正式声音与字词对齐仍是时间依据。CLI 冻结元信息，3.5.2 Plan 继续可读，不自动转换。拟生成素材列用途、数量、风格与 Asset Brief，权限见 [AGENTS.md](AGENTS.md)。

通过 `work workflow show --json` 读取三道独立人工门与 Draft 建议式审查。流程值按系列 → Work → Variant（仅 Plan/Draft）解析，设计卡和账号不能关闭流程门。通过 `work workflow put --layer series|work|variant --file FILE.json` 配置；文案、Plan、Draft 门默认开启，分别由 `workflow.human_confirmation.script/plan/draft` 控制。开门时推进确认准确输入，关门时直接继续，任一开关不影响其他门。`work settings show --json` 读取表现/critic 设置，不形成第二套审批来源。

派工只传 Plan 路径、Scene ID、负责范围与写入边界，由执行者按引用读取同版全片方向和对应 Scene，不重复复制正文；不附加比 Plan 更严的禁止项，不可行时回报准确冲突。对应对象只加载已选资产接口卡与必要合同，不再派发全库研究。主模型负责内容结果。模型不产出模板之外的设计说明或自写检查脚本；检查使用 CLI 与诊断，Work 与工程中确需的文件不受影响。

## 3. Studio 制作与验收

是否要求 Q1 或节奏闭环由档案 exemptions 决定；ready、seek、离线闭包、授权始终保留；完整 Draft 人工接受取决于该门是否开启。
完成当前 Plan 门设置要求后扩成全片 Draft；按短自检单核对 ready、seek、资源闭合与正式声音。占位到素材齐备是同一阶段的准备度变化：用稳定 ID 补齐媒体，只重定时受影响范围，保持全部 Scene、A/B、动作与阅读安排。最终接受前正式声音与必需效果齐备。

使用 CLI 返回的锁定官方 Studio URL。登记版本在独立审阅副本打开；依照 [hyperframes.md](spec/hyperframes.md) 验证 ready、seek、闭包与技术 QA，按链路适用的观看检查带声连续观看。阅读区域稳定，节奏事件与声音对应；Windows 原生连续播放、暂停、任意 seek、回拖和跨 Scene 证据单独报告。

要求诊断闭环的链路在交付 Draft 前对准确版本运行 `preview diagnose`；showcase 按专属豁免处理。逐项处理适用的 `rhythm_gap` 与未验证区间：修正工程后重新诊断、在 Plan 写例外行并随对应方向或完整 Draft 接受确认，或在交付说明逐项解释原因。交付说明附诊断报告位置与未处理项；诊断只定位，不判通过、不替代观看，不新增审批门。默认读取摘要，确需完整结构时用 `--json`，不读取 `probe.json` 等原始采样。

`preview register` 冻结准确 Draft，`preview open <id>` 审阅，Draft 门开启时再由用户接受准确 full Draft；关闭时正常继续。技术 PASS、素材 complete 与方向确认不替代开启的人工门。反馈绑定版本、Scene 与时间范围：信息缺口回 Plan，证据缺口回 Research，布局或实现问题就地修复；等义、换行、easing、安全区与性能修复无需重新批准方向。新增事实或改变原意回权威来源。工程文字同步逐 Scene 的实际 `screen` 表达。

`work --work <id> --variant <id> critic round [draft-id]` 复用登记、独立 Studio 审阅副本与诊断，一次生成准确 Draft 的截图、contact sheet、逐帧页、Scene 交界前后帧和 Scene/A/B 帧条，追加 Variant `critic/ledger.json`。不导出视频。省略 Draft ID 时先登记当前完整工程；失败不追加成功轮次。`--automatic` 在轮数上限停止；不带该参数可手动继续。

critic 提供方为 off 时仍生成证据和 ledger，不生成提示词。开启时由外部只读评审者读取评审包并实际看 PNG；`critic.model` 默认为空，仅记录评审来源，不证明看图能力。没有实际图像读取或人工观看证据时报告未验证，不用纯文本替代。CLI 不调用模型 API。`critic record --file <verdict.json>` 校验准确轮次/快照、新问题和上一轮未解决问题的 FIXED / PARTLY / STILL；意见不阻止登记或接受。

## 4. 导出、封面与归档

封面按账号配置组成（风格 + 角色 + 标题 + 一句话，见 [creative.md](spec/creative.md)），Draft 登记时用已采用的标题、一句话和角色渲染。生产 Variant 从准确 Accepted Draft 的闭合快照进入 Finalize，输出最终 MP4 与封面；test-work 不进入任何视频导出链。成功编码、QA、成片提升及收据完成后，MP4 与封面复制到导出架（`<账号>/<系列>/<系列>_E012_<账号>_v01.mp4`，封面同名，旧版本移入 `_superseded/`，根目录 `publish-log.csv` 一期一行跟踪上传，见 [hyperframes-final](spec/hyperframes-final.md)），Variant 保持 active 可继续修改；归档与重开显式执行，不改等待事项或兄弟版本的归档状态。零版本与部分归档不算整期完成。导出与归档不包含上传/发布。

编码 QA 检查规格、原音时长、全量解码、代表帧及必要听音；首次跨引擎输出核对构图、中文边缘、字体、颜色、透明合成与声音。失败不归档，保留复现及旧 Final。成片已成功而导出复制或收据写入中断时，从同次收据恢复，不重复编码或增加历史条目。历史成片与当次 manifest 一起保存；旧散装 MP4 缺收据时标明历史来源未知，不猜配、不自动删除。

## 归档、恢复与停放

Work 是内容容器，各 Variant 平级；`required_variants` 不再作为第二套完成判据。取消归档用 `work reopen <Work-ID> --variant-id <Variant-ID>`，在原版本继续修改，保留上次导出和接受快照。重新激活或显式新增任一 Variant 后 Work 回到 active，其余版本保持原生命周期；多版本不隐式全部重开。已有继任链前身仍只读。

`work --work <Work-ID> archive --variant-id <Variant-ID>` 可手动收起未导出的版本，显示未导出，不冒充交付成功。归档和恢复保持物理路径稳定。`park` 只暂停 Work，`resume` 解除暂停；二者不搬目录、不改等待事项或兄弟版本的归档状态，已打开的 Studio 会话继续定位原路径。旧搬移布局只在能保持会话、Current 与原状态完整的兼容路径中处理。

`list` 默认展示 active（含 parked），`list --archived` 查看归档，`list --all` 查看全部；`list --tree` 与可重建的 `浏览目录.md` 使用同一展示数据；`浏览目录.md` 按系列分组，附系列文件夹与系列规则链接，归档 Work 在所属系列内标为已归档。按标题、系列号、版本归档数、当前焦点及最近导出定位，工程与成片链接指向准确对象。查看归档不等于重新激活。

`work storage inspect` 按 Work 盘点空间，`work storage cleanup` 默认仅预览，加 `--apply` 才执行；均可用 `--work <Work-ID>` 限定目标。容量按需统计，无法读取时报告未知。回收只处理已证明归属、可重建、无引用且相关进程已停止的缓存；Studio 私有浏览器配置（`.runtime/studio-browser`，含审片副本内的）单列 `browser_profiles` 容量，仅在该 Variant 的 Studio 已停止、浏览器不再占用配置时回收其中的 Chrome 缓存目录，`Preferences`（DNT）等配置保留，跳过原因列在 `skipped`；源、原媒体、接受快照、历史成片、未知内容及失败证据保留，归档本身不触发删除。

`work storage plan --tier {1,2,3} (--work <Work-ID> | --all) [--output <file>]` 只写计划，`work storage apply <plan>` 校验摘要、资格与文件统计后逐项删除：第 1 档在定稿完成后自动回收临时副本，第 2 档对发布日志确认已发布的 Work 回收未采纳预览和已判 critic 帧（后续复盘重新采样），第 3 档禁止 `--all`，仅对 abandoned 且未发布的 Work 保留 `WORK.md`、`.runtime/archive.json`、`.runtime/storage.json`、`variants/*/variant.yaml` 与 `variants/*/retro/`。

## 复用与交接

采用相应复盘配方的设计卡在接受后使用 `VISUAL_RETRO.template.md` 记录积木、动作配方或规则、内容资产和仅属于本片四类。只提炼最小模块/接口/配方，不向其他线交整页代码；提炼到卡内 assets 的可编辑资产不引用 Work 路径，按资产合同校验。规则提案交开发仓，开发会话不读取生产 Work。

同对象、同依赖的有效检查沿用；变化仅检查受影响 Scene 和必要衔接，共享宿主或时间线变化按依赖扩大。Studio 内容检查、编码 QA 和归档完整性各自报告。

生产会话制作 Work 内容；开发会话负责工具与开发计划内的组件。工具缺口通过准确 Work/Variant 的 `request freeze` 保存预期/实际行为、冻结最小复现、允许修改文件与只读上下文；`request export` 后在 WSL 私有副本复现，工具修复形成 Harness candidate。生产会话在独立候选根用 `request review` 验证准确交付，反馈绑定 revision；应用入口为 `request accept`，权限见根规则。交付不等于 Plan/Draft 接受，不自动升级其他 Work。程序、规则、WSL、Windows 原生与生产验收分别报告。

## 画面复盘与样片记忆

找问题由用户指定，优秀只由用户标记。复盘不修改作品源、Plan、Current 和接受记录。只使用登记 Draft 快照与 PNG，不导出视频，不调用外部服务。

显式传 `--work <Work ID> --variant <Variant ID>` 后运行 `retro open <Draft ID>`；有匹配且 hash 完整的 critic 包时复制证据，否则加 `--hyperframes-cli` 和 `--browser` 从冻结快照采样，不写 critic ledger。记录在 `retro/<Draft ID>/VISUAL.md`，重开保留内容，不同 Draft 独立保存。`retro check <Draft ID>` 校验字段和枚举，不判断归因。

用户确认段和借鉴理由后，`sample add <样片ID> --draft <Draft ID> --segment S03·B1 --reason <借鉴维度> [--mechanism <机制ID>]` 独立复制帧；没有 A/B 段时使用 `S03`。每个样片 ID 表示一整片，可多次添加不同段。`sample list` 默认本产品线，`--all-lines` 列全库；也可显式 `--line <产品线>`。`sample show <完整段ID>` 读取证据；`sample retire <ID> --reason <理由>` 与 `sample consolidate <ID> --into mechanism:<ID>`（也支持 asset:/rule:）只改状态，不删证据。样片不自动过期。

制作时在 Brief（showcase 概念节）的 `**参考机制：**` 引用完整段 ID，跨线写 `跨线:<ID>`。`plan check` 读两层机制库，报告退役、巩固、已知行为变化提示；发行机制仍可引用。`plan refresh` 将有序帧、理由与 samples 设置冻结在 `reference-memory/<revision>/`，制作必须用 `sample show <ID> --plan-revision <N>` 看这组帧。引用或设置变动经 refresh 创建新 revision，Draft 继承独立副本；之后退役、巩固或设置变化不改变旧 Draft。禁止手改这些冻结文件。

`samples.max_references` 默认 3，`samples.frames_per_reference` 默认 6；用户层与 Variant 层可覆盖。旧 Variant 补默认值而不重绑档案，无 line 的旧 Variant 仅允许新增 samples 设置，不改旧开关语义。通用 explainer 总引用仍 1–3；showcase、math、english 按专属档案选用，不继承通用配额。每段帧不足时取全部，超过时均匀选取；不补造帧。

已知缺陷先在复盘问题行填写 `已知缺陷 ID`，用户确认后 `defect add <ID> --draft <Draft ID> --description <描述> --frame images/<帧>.png`（可重复 --frame）。`defect list` 默认本产品线；`defect retire <ID> --blocked-by <规则或诊断>` 保留证据。critic 只读本线有效缺陷，附在档案检查项后；每轮记录生效 ID。参考样片逐项评“达到 / 部分 / 未达”，按 reason 限定维度，不评相似度；`critic record` 拒绝遗漏、重复、未知引用和非法结论。

`retro summary` 只读扫描已登记 Work，写生产根 `retro-summary/summary.json` 与 `SUMMARY.md`，不改 Work。资产按 Work/Variant/ref/version 去重，时间取 Variant 元数据（未知为 null）；样片按 Work/Variant/Plan revision/ID 去重，同 revision 多 Draft 不重复计数。问题按显式缺陷 ID、归因层、去向和产品线聚合；样片按显式机制 ID 分组，缺失关联记未关联。手写重复由人填写，只计数，不比对跨片代码。资产候选、规则与诊断提案不自动接受或执行。

## 内容复盘

只写 Variant 的 `retro/content/`（含导入原件）和生产根 `content-summary/`，不改 Work 源、Plan、Current、接受记录。所有单片命令显式 `--work <ID> --variant <ID>`，不取 Current；以下命令位于同根 Work CLI。

1. `content link <发布 ID> --draft <登记 ID>` 或 `--final`，同时提供 `--file <已发布文件> --platform <平台> --title <标题> --cover-text <封面文字> --published-at <ISO 时间> --ratio <画幅>`。账号来自 Variant；未绑定时必填 `--account`。只计算发布文件 hash 与时长，不复制或导出视频。
2. 本期实验变量必填：重复 `--variable '开头写法=本期取值'`，其他用 `--variable '其他:说明=取值'`；可加 `--compare <同平台账号对照发布 ID>`。同 ID 有多条时用 `Work/Variant/发布ID` 消歧。没改动显式 `--no-variable`。重新 link 同 ID 保留修改历史；文件、来源、时长、时间表等身份改变须新 ID。
3. 可选 `--timings <JSON>` 提供冻结工程导出的 `[{scene,anchor,start,end,characters:[{char,start,end}]}]`；须包含有效 Script Anchor，区间不重叠，末端与片长误差不超过 1 秒。优先使用来源快照 `section_map.json`（相同 rows 或 `{sections,characters}`）；没有则未对齐，CLI 不解析工程脚本。字级数据缺失不推测口播。
4. `content import <发布 ID> --dir <五份 xlsx 目录> --cutoff YYYY-MM-DD [--stage long-tail|early]`，或重复五个 `--file`。原件独立复制，sha256 留档；分段末端与片长差超过 1 秒拒绝。长尾由用户判断；不传 stage 为未标，输出 daily 供判断。导入全部保留。
5. `content open <发布 ID> [--import <导入 ID>]` 默认最新导入，刷新 CONTENT.md 生成区并保留手填部分；`content check <发布 ID>` 校验字段与枚举。找优秀仅用户标记，已有样片机制负责登记。数学不能使用 Script 开头与衔接去向。
6. `content summary` 按平台、账号、片长分组，只计每条发布最新长尾导入；少于 5 条不报偏离；输出开头样本、选题与实验变量表。其他阶段列出但不计基线。

读数依次为观看时间、2 秒与 5 秒、封面点击、完播。条件平均观看时长已从视频起点计时，平均离开点不再加 5 秒；输出取整区间和假设。无留存曲线，跳过 / 回看不等于离开；缺来源记未列出，不记 0。API 仅接口，无网络调用。原件、记录和汇总仅留生产根，不进开发仓与 Git。

## 精确采用、推进与历史项

- 现有版本可用 `work --work ID --variant VARIANT variant reselect --design CARD --no-account` 查看配置差异；确认要采用后加 `--apply`。选择账号改用 `--account ID`；省略设计或账号时保留当前准确采用，不追随最新账号版本。`--overrides FILE.json` 替换本 Variant 表现覆盖层，空对象清空此层。采用保留文稿、Plan 与历史产物，新 Plan/Draft 需重新检查。
- `work workflow stage plan|draft|export` 输出当前阶段文件；只加载返回列表。各卡的分阶段文件位于 `.studio/designs/<id>/stages/`。用 `python .studio/design_examples.py CARD --output NEW_DIRECTORY` 装配可编辑闭合示例；有改动的目标目录拒绝覆盖。
- 明确推进即确认准确输入：`work workflow advance script|plan --sha256 FILE_SHA256`；Draft 用 `work workflow advance draft --draft DRAFT_ID --sha256 SNAPSHOT_SHA256`。同输入重试不重复确认，字节或修订变化需要重新推进；不改 Script/Plan 正文。关闭某人工门只影响该门。
- 历史项映射使用 `work --work ID --variant VARIANT migrate design --design CARD --design-version N --account ACCOUNT --overrides FILE.json`（或明确 `--no-account`）。先预览，再用来源 `variant.yaml` 的 `--source-sha256 HASH --apply` 采用；每次只处理一个版本，不改名、不合并兄弟版本。未知来源配置单列，不将旧有效配置整体提升为显式覆盖。
- `migrate retire --note REASON` 同样先预览，再带准确来源摘要和 `--apply`；保留全部历史文件与定位，阻止继续制作。无 Variant 的 Work 只允许 Work 级退役，不强造空工程。Remotion 依赖会报告 `needs-native-adaptation` 并保留原件，配置映射不代表旧渲染器已兼容。
