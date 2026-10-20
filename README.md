# Magic Video Harness

v4.2 开放设计卡脚手架：一张设计卡包含设计指导、阶段配方、范例和自己的资产库；素材卡只提供资产，不进入制作设计选择。公共包内置 `stage-full`、`stage-light` 两张只读卡；用户卡保存在工具之外的 `design_root`，由使用者直接编辑。

Work 管一期内容，Variant 管独立制作版本。设计卡在制作中实时读取，提交 Draft 时复制卡片文件与引用资产并记录摘要；已有 Draft、接受快照和 Final 保持独立。当前只提供 `hyperframes_video` 制作。Windows 原生、打包与生产验证单独记录。

## 快速开始

资产选型使用 `component list` 查询卡内资产，按用途、类型、标签或画幅筛选，再通过 interface 阅读用法。来源卡缺失或引用断链时明确报告；单张无效或同 ID 冲突的卡只停用自身。`--design <card>` 只列该卡 Variant 可用的资产，`usable_by` 与安装/绑定的实际范围一致；`component trace` 只读核对卡—引用—账号—Work 关系，分开报告缺源、未安装与旧冻结副本。设计卡声明 Plan、阶段指导、资产范围和豁免；素材卡只被引用或本地化，不能用作 Variant 的设计。

五层宿主与 A/B-roll 按所选卡的合同取用，不以四模式或执行模型限制设计选择。字幕、音效和封面由设计默认值与各层覆盖决定；英语等用户设计的专属规则随卡维护。旧 `explainer`、`showcase`、`science`、`card`、`math`、`explainer/math-rap` 身份提示重选，不静默回退。

公共 TTS 默认火山引擎，可配置替代脚本；切换提供方不改 Script / Plan。候选音频、正式声音采用与字词对齐分开记录，只采用提供方原生时间证据；缺少原生时间证据时明确报告缺失，不以估时或替代流程补齐。凭据不进入源码、日志、缓存与发行包，服务失败不自动换供应商。真实合成与听校须有各自证据。

card 链路从 repo 和产品配送中删除，不保留制作、编辑或渲染兼容实现。旧作品、接受快照和成片保留；继续内容须显式采用到受支持的新版本。显式或配置中的旧 card 值报告来源，不静默改为 explainer；普通卡片式画面仍可用于其他链路。

按音乐拍点编排时，正式声音已有且 cue 已建立后，使用 `./work --work <id> --variant <id> beats build --audio <Work相对音频路径> --beats-per-bar <每小节拍数> --first-downbeat <零基拍点索引>`；锁定上游提取拍点，拍号和首个强拍须人工明确，弱起不猜测，生成的网格绑定音频摘要，cue 可用 `{bar, beat}` 引用拍点。

`./work --work <id> --variant <id> review package <审查ID> --manifest <Work相对JSON路径>` 将当前 Plan、字级时间/节拍和声明文件复制到 WorkStore 的 `review/<审查ID>`。声明格式为 `{"scenes":["variants/<版本>/project/scene.html"],"screenshots":[{"time":1.5,"path":"materials/frame.png"}],"contact_sheet":"materials/contact-sheet.png"}`；截图先通过官方 Studio/snapshot 取得，命令只复制，不导出视频、不扫描未声明素材。审查输出使用【图】【码】【未实现】证据、严重度表与推荐分镜表。

生产会话以安装根为工作目录，读取根 `AGENTS.md` 和 `.agents/skills/hyperframes-production-workflow/SKILL.md`，通过根 CLI 操作已授权 Work。Windows 原生调用 `work.cmd`；WSL 生产会话调用 `./work-wsl.sh`，转发到同一根的 Windows 运行时。`doctor` 输出实际部署身份和调用路径。根入口不创建或依赖 Harness session。开发会话无论运行在哪个操作系统，都只使用隔离夹具；生产会话按授权绑定 Work/Variant。执行模型与设计卡分别选择。

```bash
./work root show
./work account list
# 先准备共享内容，不强制选账号或创建 Variant
./work new "作品标题" --workflow hyperframes_video --purpose standard --series <series-id>
./work status
# 制作生产 Variant 时使用已登记账号
./work variant add douyin-9x16 --account <account-id> --ratio 9:16
```

开发仓与外部 WorkStore 分开维护；开发绑定保存在 Git 忽略的 `.studio/.runtime/work-root`，通过 `./work root set <absolute-path>` 显式切换。Windows 安装根的本机配置位于 `.studio/.runtime/local.json`，不随包配送。

`work new` 创建视频 Work。CLI 在命名锁内分配 `work-hyperframes_video-<序号>-<初始标题slug>`，与系列号独立且不封顶于 999。后续改标题不改 ID 或目录。视频制作通过 `--design <id>` 选择设计卡，视觉主题、背景与画幅按卡片默认值和显式覆盖解析，不要求前置 Profile。Theme 不隐含选择背景和运动。

```bash
./work new "人物口播" --workflow hyperframes_video --purpose standard --series <series-id> --account <account-id> --variant-id talking-head --template talking_head --subject-position left
./work wait recording
./work resume
```

后台任务使用 `--detached` 创建 Work，并始终显式绑定自己的 Work / Variant。Current 只代表操作焦点；独立作品可并行推进，同一对象保持一个执行者。Script 稳定后用 `work name` 补充语义标题，不改变 ID 或目录。

```bash
./work new "另一作品" --workflow hyperframes_video --purpose standard --series <series-id> --detached
./work --work <work-id> --variant <variant-id> status
./work list --tree
```

视频 `SCRIPT.md` 的口播正文可附成对 `scene-index` 注释包围的非口播 Scene 索引；配音、统计或对齐使用 `./work script text`。Research 按呈现需求准备候选材料，不规定实现；Plan 写清实际采用的屏幕文字、来源与声画取舍，不复制 Script/Research 全文。文字主导与动效主导独立于工程 Template；实际语义起点、同卡累积、三种场景策略和观看检查见 [表达合同](.studio/spec/visual-design.md)。PACKAGE 仅按交付需求生成，不是视频前置。

视频沿用现有 Script、Research、音频与 M2–M3 画面，先完成整片 Plan，再选一个真实 Scene 动态参考。一次方向批准后直接生成完整 planned-placeholder Draft，素材齐备后生成最终 Draft，沿用原完整接受和 Final 流程。不逐 Scene 审批，不新建 Shotbook，不把样段或占位 Draft 当成具备 Finalize 权限的 full Draft。

复用优先选择承担明确含义的视觉对象，保留内部联动和既有 helper。Plan 按所选链路列清逐 Scene 的叙事职责、语义对象、素材占位 ID 与人声 cue 意图；音乐分析可选，已有 timestamps/section_map 优先复用。最终 Draft 必需素材齐备，计划内占位不阻塞此前全片预览。新登记参数只在实现并验证后加入帮助；旧 reference/layout 记录保持原含义。具体约定见 [创作工作流](.studio/workflow.md)。

日常预览默认启动锁定版本的官方 HyperFrames Studio，返回实际项目 URL；当前工程可编辑，登记版本只在隔离副本打开：

```bash
./work preview open current
./work preview context current --fields selection,lint --detail compact
./work preview open draft-v001
./work preview stop current
# 仅显式历史查看保留自制审阅页
./work preview open draft-v001 --legacy
```

Studio 对 current 的修改同步原文案真源或暂停对应再生成，旧 MP4 / QA 不继续代表新源码。登记版本的独立审阅副本文件只读，不支持 Studio 保存；打开时先校验，副本变化则新建目录并保留旧副本，不放宽诊断完整性检查。`reference` Plan 没有虚构的可播放工程，直接审阅其资产引用。

数学卡已于 2026-10-20 退役，`math build`、数学图积木与数学 Plan 检查一并删除。旧数学 Work 只读：状态、列表、预览列表与诊断照常，制作、登记、导出等命令报错；要继续做，用 `variant reselect` 换到其他卡。账号不受影响，换绑别的卡后照常使用。

对已打开的准确目标运行 `./work --work <id> --variant <id> preview diagnose <current或Plan/Draft-ID>`，支持 executable 登记（`plan-vNNN` / `draft-vNNN`），拒绝静态 `reference` 和 `layout`。只读输出上屏照搬、Plan 信息缺失/截短、其他实现偏离和静止疑点，不作 QA 通过判断。Plan 支持新 `screen` 信息块与旧表格格式。登记 Plan/Draft 使用同版冻结的 Script、Research、Plan 与工程，当前文稿的跨版本差异另列；输入在诊断期间变化则报告过期。单 Scene Plan 参考沿用登记的 `sample_scenes`，其他 Scene 列入 `d1.out_of_scope`（不在本参考范围），不报缺失或未验证。文字按 `data-info-id` 或与唯一信息块的精确文本匹配归属；无法唯一归属时按元素列为待核验，相关信息不报缺失。多信息 Scene 可在信息块容器上标注可选的 `data-info-id`。参数及明确引用例外见 `preview diagnose --help`。制作中可用 `--range` / `--times` 只采样正在做的段，`--frames` 把采样帧存到 Variant `.runtime/diagnose-frames/` 供执行者自看（不作交付证据，交付前仍全片诊断）。范围内未采样状态、无法确认 ready 的媒体/子画面及图片内文字保留未验证，仍需按 [Draft QA](.studio/spec/hyperframes.md#draft-qa) 连续观看；诊断不导出视频或修改接受状态。

画面复盘使用 `./work --work <id> --variant <id> retro open <Draft-ID>` 与 `retro check`。记录按 Draft 保存；用户确认的样片和缺陷分别通过 `sample`、`defect` 管理，跨片机械统计用 `retro summary`。制作在 Plan 中引用样片段，`plan refresh` 固定参考帧与设置，Draft 和 critic 继承同组证据。详情及完整命令见 [画面复盘与样片记忆](.studio/workflow.md#画面复盘与样片记忆)。生产根 `sample-library/`、`known-defects/`、`retro-summary/` 属于用户内容，不进入 Git、发行包或部署管理清单。

Draft 与 Final 生命周期：

```bash
./work preview register
./work preview open draft-v001
./work preview accept draft-v001
# 仅生产 Variant：从接受源编排渲染、编码 QA 与版本化交付
./work finalize
```

无文件参数注册素材齐备的 Studio executable Draft，冻结来源和闭合工程；须打开准确登记版本的隔离副本再接受，无整片 Draft MP4 前置。生产 Variant 可独立 Finalize，不等待其他账号；从接受快照渲染、保留正式收据并完成编码 QA，不重审未变设计。Draft 与 test-work 不导出视频，Studio 受限时也不以短段或预渲染镜头绕过。成功 Finalize 归档目标 Variant；至少一个版本且全部归档后 Work 才整体归档。编码或 QA 失败不归档；成片已提升但归档记录中断时，重试从准确收据恢复，不重复编码。Finalize 不包含发布/上传。

## 归档、反悔与导航

`work list` 默认展示 active（含 parked），`--archived` 看归档、`--all` 看全部；`--tree` 和 WorkStore 的 `浏览目录.md`（按系列分组）展示同一份标题、系列号、版本归档数、焦点、等待事项与最近导出。工程、最新和历史成片均链接到准确对象，容量按需盘点，未知不当成 0。

```bash
./work list --archived --tree
./work reopen <work-id> --variant-id <variant-id>
./work --work <work-id> archive --variant-id <variant-id> --outcome abandoned
./work --work <work-id> storage inspect
./work --work <work-id> storage cleanup
# 核对上一步清单后执行可回收缓存清理
./work --work <work-id> storage cleanup --apply
# 旧导出（<系列>/<Work>/<Variant>/）迁到 <账号>/<系列>/ 的新位置：先预览，再 --apply
./work exports migrate
./work exports migrate --apply
```

成片与封面导出到 `<导出根>/<账号>/<系列>/`（上传按账号进行，所以账号在第一层），文件名 `<系列>_E012_<账号>_v01.mp4`（封面同名 `.png`），用系列与账号 ID、期号是系列号而不是 Work 号。一个版本是一整个上传包：视频或封面变了，整期一起升到 v02，上一版按原名移入 `_superseded/`，文件夹里留下的就是要上传的版本。导出根的 `publish-log.csv`（Excel 可直接打开）一期一行：工具维护编号、账号、系列、期数、版本与文件名；状态、发布日期、链接、备注和你自己加的列工具不动，已发的期出了新版本状态变为「待重发」。

对成片不满意，取消原 Variant 归档继续改，不新建 Work 或 successor。新增版本或重开任一版本后 Work 回 active，其他版本保持归档；零版本不自动完成。未导出版本可手动归档并显示未导出。归档与恢复不搬目录；`park` 只暂停 Work，`resume` 解除暂停，不改等待事项、兄弟版本归档或 Studio 路径。

历史条目共同保留成片与当次收据；旧散装成片缺少可证明来源时显示历史来源未知。归档保留反悔所需文件。`storage cleanup` 默认仅预览，`--apply` 才清理证明归属、可重建、无引用且进程已停止的缓存；原媒体、源、接受快照、历史成片、未知内容和失败证据保留。

已退役或未知 Work 会明确报告，不再执行旧制作流程，也不阻断无关视频创建；本版本不自动删除旧作品文件。

## 账号、系列与制作版本

系列、用途与账号通过 Work CLI 管理。新 Variant 用 `--design <id>` 明确选择设计，可用 `--account <id>` 或 `--no-account`；素材卡不能作为设计选择。账号、系列、Work 与 Variant 的覆盖值按既有优先级解析，设计身份不绑定执行模型。旧身份只读并提示重选，不默认选择 explainer。

Theme/Background 使用单资产合同与工程内的精确 vendor/lock；账号级 Motion 已退役，动作用工具级 `runtime/motion.js` 与设计卡的卡片动作包（卡内 `MOTION.md`），旧冻结 Work 里的四槽 Motion 照常校验与播放。外观变更仍使用 `appearance rebind`，旧冻结工程不因卡片编辑而自动换配。字段与参数见 [资产合同](.studio/spec/hyperframes-assets.md)。

Motion v3 增加风格入退场、一次性强调与转场、back-out/spring 及 cue 相位 hold_fps；允许不同槽混用 v2/v3，新 lock 采用最高能力版本，旧冻结 Work 不自动升级。完整账号外观指定 Theme/Background；跨账号风格叠加省略 theme，保留各自账号 Theme。B-roll module 可通过 `component list --broll-role hook|concept|transition --tag <style>` 查询，接口卡显示完整挂载示例和插槽；Scene 手动接既有 A/B 编排，Binding schema 不变。合同与生产源自检见 [镜头创作指南](.studio/spec/broll-assets.md)。

封面按账号模板合成；舞台卡账号的角色库图片由生图 MCP 生成，`account character add <账号> --name <角色名> --image <PNG> --prompt <提示词> --model <模型>` 登记到账号。声音：BGM 只用开源曲库现成曲目（`component import-bgm` 带许可导入，舞台卡由账号 `bgm.enabled` / `bgm.policy` 开启并写偏好），不合成；音效可用 earshot 音效库渲染（`component generate-sfx --engine earshot`，外部 `earshot` 由 `HYPERFRAMES_EARSHOT` 指定）、SuperCollider / jsfxr 或 HyperFrames 自带音效。命令细节见 [运行时接口](.studio/spec/runtime-interfaces.md)。

所有新视频 Work 默认把 Script/Research 放在 `shared/`，各 Variant 通过 `shared_inputs` 引用同一源，Plan/工程/接受/Final 各自独立。`variant add --from <variant-id>` 显式创建内容分支，不是仅为了新增账号而必需；旧 Variant 内文稿仍按原位置读取。创建隔离测试可用 `work new "联动测试" --workflow hyperframes_video --purpose test --batch <batch-id>`，只进行 Studio 验证，不导出视频。

RC2 视频 Work 的全局 ID 与系列号独立递增且不封顶于 999；Work 目录按系列分层为 `works/<系列ID>/<Work>/`（实验 `works/test/`，未归系列 `works/_未归系列/`），归档只是标记；`name` 不改 ID/目录，`series move <id>` 把 Work 目录移入新系列文件夹，旧系列号保留为查询别名。旧 `works/active|parked|archive/` 布局用 `migrate layout [--apply]` 迁移，默认只预览。`list --tree`、`find --series <id> --number <n> [--account <id>]`、`account get <id>` 和可重建的 WorkStore `浏览目录.md` 用于定位。系列经验规则用 `series rules show|put <id>` 按系列 ID 读写 `works/<系列ID>/AGENTS.md`（`put --file -` 读标准输入），历史留在 control-plane；`series rules delete <id>` 撤下当前规则，`series delete <id>` 把无 Work 归属的系列连同历史与规则归档到 `control-plane/deleted/series/`。旧视频 Work 的一次性改名只经 `migrate dry-run --output <map.json>` 审阅映射，再由 `migrate apply --mapping <map.json>` 显式执行；缺用途或含糊标题可用 `--purpose-overrides` / `--title-overrides` JSON 映射重做 dry-run。若一项被阻断，可用重复的 `--only <old-id>` 生成安全子集映射；同系列须按旧 ID 顺序迁移。映射文件必须新建于 WorkStore 外。迁移只在 WSL 合成 WorkStore 验证，尚未对生产 WorkStore dry-run/apply；工具部署状态以目标根的部署收据为准。

三项入口、四阶段及历史兼容见 [v3.3 合同](docs/PRD/hyperframes-v33-production-contract.md)，RC2 范围见 [RC2 执行方案](docs/PRD/hyperframes-rc2-execution-plan.md)。HyperFrames 是唯一时间轴、预览与渲染宿主；工具安装不等于 Windows 原生 Studio 预览、真实生产 Finalize/缓存复用或新 Work 内容验收；这些结果须分别取得证据，不以 mock 或文档冒充完成。除 RC2 明确的一次性旧视频 Work 身份迁移外，不批量迁移旧作品、接受快照与 Final。

## 历史合同

v3.x 生命周期与旧资产库合同、v4.0 设计身份及 v4.1 增量见 [PRD 主索引](docs/PRD/PRD_MASTER.md)。历史对象保留原读取语义，不按当前文档批量迁移。

## Showcase 补充工具与正式配音

以下命令在获授权的创作根执行，必须明确 Work / Variant。舞台仅首批 16:9；抠图只支持近白底三视角色图（`sheet`）或已有透明动作图（`pose`）。输入路径相对 Work，输出目录相对当前 Variant 的 project；已有输出需换目录，或显式 `--overwrite` 替换完整且未被修改的同工具产物。源码随工具配送，不依赖真实作品目录。

```bash
./work --work <work-id> --variant <variant-id> showcase stage --output assets/stage
./work --work <work-id> --variant <variant-id> showcase cast --input materials/actor.png --kind sheet --output assets/cast/actor
./work --work <work-id> --variant <variant-id> tts generate
./work --work <work-id> --variant <variant-id> tts generate --config <provider.json> --anchor P001
./work --work <work-id> --variant <variant-id> tts audit <candidate-sha256> --alignment materials/alignment.json
./work --work <work-id> --variant <variant-id> tts adopt <candidate-sha256> --alignment materials/alignment.json
```

TTS 读取已批准或无需批准的当前 Script 正文与稳定 Anchor，排除 Scene 索引。默认火山 `seed-audio-1.0`，凭据只从 `VOLCENGINE_TTS_API_KEY` 环境变量读取。配置 JSON 可含 `provider`、`model`、`options`、`anchors` 和环境变量名 `key_env`，不能包含凭据值；`anchors` 按 P001 等 ID 覆盖本段选项。火山选项为 `instruction`、`speaker`、`speech_rate`、`pitch_rate`、`loudness_rate`、`sample_rate`，按[官方接口](https://docs.volcengine.com/docs/DoubaoVoice/audio-generation-http?lang=zh)校验。中英文可分 Anchor 指定发音意图；谐音提示不替代标准发音。调用云服务仍需已有的内容及费用授权。

替代提供方配置示例：`{"provider":"script","model":"your-model","command":["/absolute/python","/absolute/adapter.py"],"options":{}}`。命令为程序或解释器＋脚本的参数数组；宿主追加 `--request <json> --result <json>`，不经过 shell。请求含 `schema_version:1`、`anchor`、`text`、`model`、`options`、`output:"audio.wav"`，工作目录为本次临时段目录；脚本写入 PCM WAV，并在结果文件返回 `{"audio":"audio.wav","model":"your-model","options":{}}`，实际模型与参数须等于请求（不同则拒绝采用）。越界路径、软／硬链接、坏音频、混合采样格式或非零退出都失败，不切换其他服务。凭据由脚本从环境读取；本期不安装其他语音引擎。

候选仅保存在 Variant 的 `materials/tts/<hash>/`，按提供方、模型、正文与生效参数区分。单 Anchor 可试听；正式采用须覆盖当前全稿，并提供由工具测得的对齐 JSON，顶层 `audio_sha256` 必须等于候选音频 hash，`method` 为 `provider-native` 或 `forced-alignment`（须带 `engine` 记录对齐引擎与版本）；手工测量的 `manual-measured` 不再接受，缺少提供方原生时间证据时明确报告缺失、不以估时补齐；`characters[]` 含单字符 `text`/`char`、以全片秒数记录的 `start`、`end`。采用前对照候选音频做机械审计：字时长呈均分特征直接拒绝；落在静音里的字、无字覆盖的长语音段、过短或过长的字列为可疑项，写入 `project/runtime/alignment-report.json`，逐字核对只处理这些可疑项。`tts audit` 只读输出同一份审计结果，供采用前自查。采用会接入 voice 音轨、cues 与 section_map，将 Plan 退回待检查状态并清空当前接受关联；旧快照不变。Script、正式音频或时间数据变化须重新采用和检查。坏请求、合成失败与采用失败保留已有结果。

## 外观、资产与研究入口

同一 Variant 可显式原位换配，不必新建版本身份。先检查差异，再用 `--apply` 提交；已知旧 runtime 另加 `--upgrade-runtime`，未知或用户修改的 runtime 不覆盖。中断遗留 journal 时用同目标 `appearance recover` 恢复，不手删记录。账号默认、正文与历史 preview/Final 保留，变化后的外观清空当前接受及 Final 关联，不能沿用旧交付作为新外观接受。

若升级后没有 pending rebind，但 Variant 外观锁相对工程锁仅增加了 `capabilities.checks`（及相应摘要），停止该 Variant 的 Studio 后运行 `./work --work <work-id> --variant <variant-id> appearance recover --sync-checks`。命令校验两锁和已安装资产，备份旧工程锁后原子同步至 Variant 锁；保留工程其他文件、vendor、历史快照及现有接受记录。删减检查项、其他外观差异或损坏的锁均拒绝同步；有 pending rebind 时先运行不带此选项的 `appearance recover`。

```bash
./work --work <work-id> --variant <variant-id> appearance rebind --theme <theme-id>@vN
./work --work <work-id> --variant <variant-id> appearance rebind --theme <theme-id>@vN --apply
./work component list --query <用途或别名> --kind module --ratio 9:16
./work research --root <登记根> register --kind tool --title <标题> --path <原文.md>
./work research --root <登记根> query --kind tool
```

创作查询用 `component list --include-references --query <用途>` 同时查包、场景源与配方；普通 list 保持参考项默认隐藏。列表 `detail.argv` 可直接传给本根 work 入口查询详情，`full_result` 可取完整 JSON；截断时保留总数和准确目标。`component interface` 区分当前状态、入口、限制与真实下一步，歧义必须按路径选择；参考项没有安装权或虚构派生命令。`list --audit` 和 interface 均不写缓存、索引或报告。

发现结果支持类型、画幅、标签与推荐状态筛选；区分已接纳、候选、源和仅供参考，metadata-only 不等于完整校验。采用时仍验证精确版本/hash/闭包，缓存可用 `--rebuild` 重建；查询、推荐和研究更新都不改已有 Work。研究支持 create/register/query/update/sync/link/reference，正文为真源，修改记录使用当前 revision，摘要更新校验当前正文 hash；过期或失败不覆盖正文、不自动改 Plan 或接受状态。详见 [技术合同](.studio/spec/hyperframes.md)。

本地 Theme 字体由 `await HarnessAppearance.load()` 等待加载，再同步 apply；通过 Typography CSS 变量使用隔离字体族，实例结束 dispose。MP3 使用原生 media 合同与真实 probe/decode 检查，入库不代表听感或成片声音接受。文字与辅助图形的制作默认只见 [visual-design](.studio/spec/visual-design.md)：图形内容由生产会话制作，组件也可纳入隔离开发计划；开发会话负责工具和入口，不随包宣称已接纳图形预设。

## 公开内容

- `AGENTS.md`：环境与权限边界。
- `.studio/`：工作流、能力表、规范、Recipe、模板和生命周期 CLI。
- `.agents/skills/hyperframes-production-workflow/`：阶段路由 Skill 与可选的旧外观参考。
- `work`：无第三方依赖的本地 Work CLI。

## 私有内容

外部 WorkStore 的 `works/`、旧 `tasks/`、媒体、工程、Draft、Final 和运行状态不进入开发仓或 Git。公开 Harness 不提供下载或转录服务，Script 只来自用户提供的文稿或用户撰写；用户自行导入的普通媒体、音乐与视频进入对应 Variant 的 `media/`。不购买额度、不读取 Cookie 或凭据、不点击发布；外部或付费服务必须单独取得用户授权。

组件也可纳入 WSL 开发计划，验证仅用隔离夹具。创作使用卡内 `assets/<asset-id>/asset.json` 与实际文件。资产身份为 `<card-id>/<asset-id>`；按所选卡使用自有资产或 `design.json.references` 中声明的跨卡引用。引用只读且实时；本地化复制为自有资产，`borrowed.json` 保留来源摘要、许可与署名，后续差异由使用者决定如何合并。

根配置 `.studio/.runtime/local.json` 的 `design_root` 可指定绝对路径，默认 `<work_root>/asset-library/designs`。默认目录不存在时只发现内置卡；双根同 ID 明确报错，不覆盖。素材卡不需要设计配方。内置卡只读，使用者新建或复制的卡写入用户目录。旧 AssetStore 的 pack/import/accept/root 已退出日常入口；旧 vendor 与 `COMPONENT_LOCK.json` 继续支持离线校验。

`design_root` 可以直接是版本控制工作树（例如在 `asset-library/designs` 内初始化的嵌套 Git 仓库），工具发布不会覆盖其中内容。Catalog、校验与 Draft 快照忽略 `.git/`、卡内 `study/` 与根级 `studies/`，参考视频的拆解笔记可随卡入库而不进入作品。`work design root` 只读报告该目录的分支、未提交数与远端差异；`work design compare <card> --since <rev>` 列出自某修订以来的卡片变化并指出版本是否递增。工具不执行任何 Git 写操作，提交、推送与快进拉取由使用者自行执行。

对话创作使用 `hyperframes-design-authoring` Skill。先新建骨架或复制范例，再编辑指导、阶段配方与资产：

```text
work design list
work design new my-stage --from stage-full
work design new my-materials --type material
work design validate my-stage
work design preview my-stage
work design localize my-stage other-card/asset-id
work design compare my-stage
work --work <Work-ID> --variant <Variant-ID> variant design-update
```

新设计卡以 `capabilities` 描述能力，不必填写 `mode`：`layers.required/optional` 声明 background/stage/overlay/text；`rolls` 决定是否安装 A/B 运行时（为 true 时需声明 subjects）；`bindings` 分别声明 theme/background/motion 的 required/optional/none；`checks` 选择已注册的检查，`research_template` 和 `plan_template` 优先读取卡内同名模板，再使用工具默认模板。字幕默认值只读 `defaults.captions.enabled`。

`optional` 继承账户但允许留空，`none` 不继承账户但允许显式选择；两张内置舞台卡的三个绑定均为 optional。`bindings.motion` 只对旧锁有意义（账号级 Motion 已退役，新 Work 不再选动作槽）；`showcase stage/cast` 可由任意设计卡显式调用。旧卡、旧 Lock 和旧 Variant 仍按固定兼容映射读取，不原地改写。新外观 Lock 保存能力声明及其摘要，诊断只报告 required 层的缺失。

`localize` 要求先在本卡 `design.json.references` 声明引用，复制后记录在 `borrowed.json`。`compare` 只列差异，不自动合并。`preview` 的范例与摘要见输出目录；新建空骨架须先补齐范例及 `example-manifest.json`。卡内安装使用 `component install <card>/<asset> --binding-file <JSON>`；Binding 可以写卡资产身份，安装后 lock 记录准确版本与内容摘要，不要求库级 accept。

第三方代码来源固定需要本机 Git，使用 `work design source-add <https-repository-url> --commit <完整40位SHA>`，只缓存到用户卡根 `.sources/`，不执行上游脚本、不安装为卡、不配送。`source.json` 保存每个文件的摘要与许可文件线索；`unreviewed` 必须经过逐文件许可核对，不能当成可复用许可。卡中 `borrowed.json.assets.<asset>.source` 可记录 `kind: "external"`、`url`、`commit`，以及按来源路径索引的 `files`（每项含 `sha256`、`license`、`attribution`）。先缓存新 commit，再用 `work design compare <card> <asset> --commit <SHA>` 查看已借用文件的变化；工具不自动同步。提示词合集仅作来源参考，不使用此命令收录。

设计卡可用 `fonts` 声明卡内字体和许可文件；第 4/5 层与 embedded 文字统一使用。引擎型 module 提供完整 `texts()`，独立 embedded 文字的 `text_type` 必须命中该资产的 `text_ownership.kinds`。Draft 固定清单，接受时对实际包含嵌入文字的 Scene 逐项传入 `--confirm-embedded <Scene>`，仅用于记录用户真实确认。格式和检查边界见 [文字合同](.studio/spec/broll-assets.md#非-dom-文字与字体)。



卡片声明 `runtime`，GSAP 与插件由宿主锁定的 npm 依赖提供，卡片不携带 GSAP 文件。校验检查运行时版本、插件来源、引用闭包与非确定性写法；范例需检查冷启动、重复 seek 和倒跳，截图结果不代表声音或成片接受。第三方许可见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。

卡片变化只提示，不自动更新工程。按 Variant 更新卡片快照时保留工程副本，列出待重新安装的资产；新 Draft 沿用原接受流程，不跨 Variant 更新。

## WSL 解析器开发依赖

`python3 .studio/prepare_windows_runtime.py dev-parser` 从 `windows-npm.lock.json` 派生并安装本地 Acorn/esbuild，写入忽略目录 `.studio/.runtime/dependency-parser`，不创建第二份受管依赖清单。缓存齐全时可加 `--offline`。Windows 产品包使用同根 `runtime/npm` 的锁定解析器；扫描只解析输入代码，不执行待检查工程。

## Windows 安装与升级（GitHub Release）

公共安装包以 GitHub Release 发布：每个 `harness-YYYY.MM.PATCH` 版本附带 `magic-video-harness-<版本>-windows-x64.zip` 与同名 `.sha256`。这是带锁定运行时的完整包，在纯 Windows 上即可安装和升级，不需要 WSL。以下用 `D:\HyperFrames` 作安装根、`D:\HyperFrames-Data` 作作品与用户卡目录、`D:\hf-packages` 作解包目录，可换成任意本地路径；解包目录必须在安装根之外，并尽量取短路径。

```powershell
# 1. 下载两个附件后核对摘要：输出须等于 .sha256 文件的第一列
(Get-FileHash .\magic-video-harness-2026.10.0-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
Unblock-File .\magic-video-harness-2026.10.0-windows-x64.zip   # 去掉下载标记，避免包内程序被拦截
Expand-Archive .\magic-video-harness-2026.10.0-windows-x64.zip -DestinationPath D:\hf-packages

# 2. 仅首次安装：先建 WorkStore 与用户卡目录，再写根配置（work_root、asset_root 必填，均为绝对路径）
New-Item -ItemType Directory -Force D:\HyperFrames-Data\works\active, D:\HyperFrames-Data\asset-library\designs
[IO.File]::WriteAllText('D:\HyperFrames-Data\local.json', '{"work_root": "D:\\HyperFrames-Data", "asset_root": "D:\\HyperFrames-Data\\asset-library\\store"}')
powershell -NoProfile -ExecutionPolicy Bypass -File D:\hf-packages\harness-2026.10.0\release.ps1 deploy -Root D:\HyperFrames -Config D:\HyperFrames-Data\local.json

# 3. 日常使用
D:\HyperFrames\work.cmd doctor
```

配置在首次安装时复制到 `D:\HyperFrames\.studio\.runtime\local.json`，之后不再被安装覆盖；`design_root` 不写时默认 `<work_root>\asset-library\designs`，用户卡就在这里用 Windows 编辑器直接创作（见上文设计卡创作）。

升级：先关闭本根的 Studio、预览与渲染进程，下载并核对新版本，解包后不带 `-Config` 再运行一次 `deploy`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\hf-packages\harness-2026.11.0\release.ps1 deploy -Root D:\HyperFrames
```

升级只替换安装清单拥有的工具文件，不动 Work、用户卡、根配置与用户 Skill；被改过的工具文件会使升级拒绝并列出路径。同一解包目录还提供 `status`（查看已安装版本）、`verify`（校验解包内容）、`verify-root`、`rollback`（回到上一版）与 `recover`（中断后恢复），用法同上，把 `deploy` 换成对应命令并保留 `-Root`。公共包内置卡固定为 `stage-full`、`stage-light` 两张，升级不会新增内置卡，因此不会与 `design_root` 中的用户卡撞 ID。

维护者发布新版本（WSL，需要 GitHub 访问与 `gh` 登录；构建要求工作树干净、tag 指向 HEAD 且已推送）：

```bash
git tag harness-2026.10.0
git push origin main harness-2026.10.0
python3 release build harness-2026.10.0 --runtime-cache .studio/.runtime/windows-runtime-cache
gh release create harness-2026.10.0 \
  dist/magic-video-harness-2026.10.0-windows-x64.zip \
  dist/magic-video-harness-2026.10.0-windows-x64.zip.sha256 \
  --title "Magic Video harness 2026.10.0" --notes "<本版变化>"
```

正式构建总是 public 内容，不接受 `--personal-source`；GitHub 单个附件上限 2 GiB。

## 根目录部署

Windows 日常直接打开 `D:\HyperFrames`；工具实际位于同根 `runtime/`、`.studio/`，根配置位于 `.studio/.runtime/`。直接 `work.cmd` 按自身位置选择工具，不经过 `.harness/releases/current` 或 session，不自动生成 session。已有 Work、资产、用户 Skill 与请求不迁移。

一次命令解析配置一次，Preview/render 固定本次输入；更新前通过已有进程管理停止相关进程，以最小互斥防止启动和更新交错，不热换依赖。配置变更只影响后续命令，Agent 更新后重读根规则。

待安装 ZIP/staging 严格校验全部清单、hash 和路径；部署根只校验拥有的管理文件，保留合法用户文件和本地配置。更新先备份再覆盖管理文件；仍管理的文件有修改时拒绝覆盖；若当前字节已与待部署包完全一致，可直接接纳，仍备份实际部署前状态。退出管理的文件未修改才删除，修改过的原字节保存到不会被发现为 Skill 的退役保留位置，记录原路径和摘要，更新可继续且回滚可恢复。未管理同名内容不覆盖，无法安全安置则报告冲突；不全根 mirror/delete。回滚会恢复原有用户修改和已删除状态并列出路径；这类根仍可能无法通过严格 `verify-root`，需处理修改后使用，不能把原包摘要改成用户文件摘要来绕过校验。

WSL 固定部署入口（执行即更新指定根，必须已有该目标的部署授权）：

```bash
./release deploy --root 'D:\HyperFrames'
```

默认使用 `.studio/.runtime/windows-runtime-cache` 中锁定的依赖，缺失时报告而不联网安装。

personal 包通过 `--personal-source <私有来源>` 构建；私有 `release-sources.json` 可声明 `exclude_skills`，值为已锁定本地技能名的去重列表。排除项同时从技能目录、`skills-lock.json`、包模块清单及部署预检目标中移除，后续更新不补回；未声明时保持原集合，public 包不受影响。排除清单属于私有来源并参与候选摘要，不能靠编辑安装清单掩盖删改。

私有 `release-sources.json` 还可声明 `cards`：`{"source": "<相对私有来源的卡仓路径>", "commit": "<完整40位SHA>", "ids": [...]}`。构建只从该 commit 的 Git 对象读取所列卡片（不看卡仓工作树，跳过卡内 `study/`），在工具测试之后装进 `.studio/designs/<id>/` 作为受管理文件并以 `design validate` 校验（工具测试集不随私人卡内容变化），参与候选摘要并记入 `.release.json` 的 `personal_source.cards`；ID 不得与公共卡重复，链接与特殊文件拒绝。部署时 `design_root` 中同 ID 的用户卡若与包内卡逐字节一致（忽略 `study/`、`.git/`），在受管理写入成功后移到同级 `designs-retired-<YYYYMMDD>/<id>`；不一致则在任何写入前拒绝并列出差异文件。回滚不会移回退役副本，结果的 `user_cards` 报告实际移动。

私有来源可以用同名文件替换根文件 `AGENTS.md`、`CLAUDE.md` 与 `work-wsl.sh`（本机入口接线），并须在 `bases` 中逐项登记该文件所对照的公共原件摘要（分别为 `.studio/templates/WINDOWS_AGENTS.md`、`.studio/templates/CLAUDE.template.md` 与 `work-wsl.sh`）。公共原件变化后构建拒绝，须先把公共改动并入私有文件，再更新摘要；`compatibility.product` 必须等于当前产品版本。部署前已存在、未登记但与待部署字节完全一致的文件直接纳入管理；字节不同仍按未管理冲突拒绝。

Windows 入口固定本根的 `NODE_OPTIONS` 预加载器，通过锁定的 Koffi 按绝对路径加载包内 ONNX DLL，并由 Node 子进程继承；不沿用外部预加载配置，不修改系统 DLL 或 `PreferSystem32Images` 安全策略。
构建仍只包含受控文件；新增产品文件逐项用 `--include <path>` 指定，私有文件和开发 Harness 不可进入包。
首次安装用 `--config <Windows-JSON-path>` 指向已有配置，目标 WorkStore 目录需先存在；已有配置不被覆盖。
命令在 WSL 构建，传输到目标同级 `.hyperframes-deploy/deploy-*`，用独立的锁定 Windows Python 执行原生校验和部署。
无需临时编写 PowerShell、处理 UNC 执行或创建 session；活跃的根进程导致拒绝更新，不自动杀进程。

运行时锁与安装清单一致时构建 `tools` 包，不包含 `runtime/`，并绑定准确运行时文件 hash；首次安装、依赖锁变化或 `--full` 时构建完整包。
原生部署仍验证全部已有管理文件；只备份和重写内容变化的文件，旧清单中删除的文件也进入回滚备份。
工具包不能独立安装，运行时不符时拒绝，不静默采用其他版本。

默认 `--keep 1`：保留最近一次回滚备份；新入口按目标登记的产物位于 `dist/deployments/`，保留当前及前一版。
只回收新机制登记、成功且 hash 完整的过期备份/产物；未知内容、用户修改、旧机制副本和失败现场保留。
本次 Windows staging 在原生进程成功退出后删除，失败时返回 staging 和日志路径；恢复沿用独立包内
`.studio/root_deploy.py recover/rollback --root <Windows-root>`，由根外的 Windows Python 执行，未保留的更早回滚不可用。
清理随成功部署触发，不是定时任务；不清理生产 Work、资产、浏览器缓存、旧 `dist/` 或历史 staging。
结果返回版本、包类型、传输包大小、变更数量、备份字节和清理结果；清理失败不把已成功的部署伪装成回滚。

本机候选基于当前受控工作树，不回退公开 HEAD，不重跑 M0–M1，不自动 commit/tag/push。候选根使用独立配置与 Work/Asset/source-copy，真实入口形态与生产一致，不写生产 Current 或接纳状态。先交付 R1 根候选，再按 Windows 所选 Work 暴露的问题修 R2/R3；不把候选通过冒充已更新生产。

`release local` / `release candidate` 仍区分本机构建身份；正式 `release build` 使用 `harness-YYYY.MM.PATCH`，要求干净、tag 与 upstream 一致。完整包固定 Windows Python、Node、HF、GSAP/Three、浏览器及音视频依赖，普通制作不浮动安装。准确安装参数仅以实现后的帮助为准，不将设计目标写成可执行命令。

产品包不携带本机开发用 Trellis：候选源选择排除开发目录与 Skills，显式 include 不可绕过；正式发行发现这些文件时拒绝构建，最终 ZIP 再检查一次。保留项目自身 Work CLI、轻量状态机与创作 Skills，Windows 根规则仍来自独立模板，运行不依赖开发仓。

旧稳定包与历史 session 保留回退资料，不再作为新根的依赖。回滚程序不自动降级 Work schema、改资产绑定或删旧数据；旧工具无法读取时保留新数据与可用版本。实现、WSL/mock、Windows 原生 CLI、Studio、WebGL、带声短片及真实生产验收分别记录。

生产会话直接制作视觉内容和效果；仅宿主、CLI、合同、加载、seek 或依赖装配缺口交给开发会话。`work request freeze` / `export` 冻结最小复现，开发会话在 WSL 私有副本修工具并交付安装候选，生产会话在 Review 验证；纯布局、图标或动作设计不走工具请求。完整参数见 [请求交接](.studio/workflow.md#复用与交接)。Review 不允许正式 Finalize、归档完成或保存平台草稿；模拟资产接纳仅留 Review，接纳交付不等于接受 Plan/Draft，不覆盖未受影响场景。

Windows 原生、交互 WebGL、抓帧 WebGL、视频硬件编码和真实复用分别验证。构建或 Linux 测试通过不表示 Windows 已部署或硬件路径通过。目标与验收边界见 [Windows 工作台 PRD](docs/PRD/hyperframes-windows-workbench-wsl-handoff.md)。

完整产品契约以 `.studio/` 和 `AGENTS.md` 为准。
