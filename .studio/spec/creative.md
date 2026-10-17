# 创作契约

## 文案

- `source.md` 保存主要原始基线，任何改写不得覆盖它。
- `SCRIPT.md` 保存当前 Variant 引用的唯一口播正文；正文只来自用户提供的文稿或用户撰写，不提供下载或转录提取。新视频 Work 默认通过 `shared_inputs` 引用 Work 的 `shared/`，显式内容分支使用 CLI 定位的文件。正文可附明确排除出口播的简短 Scene 索引，使用 `<!-- P001 -->` 形式的稳定 Anchor；批准后新增 Anchor，不重排全部编号。索引用成对的 `<!-- scene-index:start -->` / `<!-- scene-index:end -->` 包围，只记录 `Scene | Anchor 范围 | 时间预算 | 本段内容 / 观众重点`，不进入纯文本阅读、字数统计、配音或语音对齐。
- `hyperframes_video` 的 `PACKAGE.md` 仅在交付要求包含发布包装时生成，保存最终标题、封面文字、一句话简介和内容概括，不进入口播正文，也不作为视频前置。
- 封面由账号决定的四部分组成：**风格**（账号 `cover.layout` 版式、字体、颜色与背景）、**角色**（账号 `cover.characters` 角色库中的一张）、**标题**（`PACKAGE.md` 封面文字）与**一句话**（`PACKAGE.md` 一句话简介）。每个账号配置不同；不再是"图片加写字"。用 `work cover render --title <封面文字> --tagline <一句话> [--character <角色名>]` 渲染，角色库只有一张时可省略 `--character`。未配置 `cover.layout` 的旧账号仍按标题 + Logo 渲染；已冻结的封面不迁移。账号配置写在账号 `overrides.cover`：`layout`（`character-left` / `character-right` / `character-bottom`）、`font`、`color`、`background_color` 或 `background_image`、`characters`（`{角色名: {path, sha256}}`）、可选 `logo`、`width`/`height`、`font_size`、`tagline_font_size`；渲染检查标题与一句话不溢出、不压角色和 Logo。
- 已要求的包装标题基于实际交付需求生成候选并选择 Top 1；封面文字、一句话简介与内容概括基于最终 Script 和 Research，不编造正文没有支撑的承诺。内容概括按主要对象或主题简短分项；介绍多个 Skill、工具、功能或案例时逐项单独说明。

## Research 与信息归属

- 视频 `RESEARCH.md` 在 Work 级，由各 Variant 共享；记录 Script / Research revision，按段落或 Anchor 组织事实与来源、B-roll 候选（位置与取得状态）、比喻与例子。只在真实缺口存在时记录待补问题，研究不规定布局、动画或成片秒数。
- Research 是候选材料，逐 Scene Plan 内嵌的 `screen` 是采用后屏幕正文的唯一真源，不为等义编辑回写第二份 Research 文案。来源线索不等于已取得素材；源视频证据时间点不是成片显示时间。
- Studio 改稿同步 Plan 实际表达。换行、分组、等义精简与表现标签直接调整；因果、比较对象、必要数值、单位、归属或证据边界变化先核对权威来源。新增事实定点补研究，只把改变确认结论或叙事的部分交用户判断。
- 共享 Script revision 变化后检查引用 Variant 的实际影响，只更新受影响条目及引用元数据；保留未受影响资料与接受快照。已归档版本的接受快照和旧成片不随共享稿变化；恢复该版本后按新输入检查，不沿用旧接受作为新内容批准。

## 录制对齐

- 实际视频或音频是时间轴权威，`SCRIPT.md` 是批准文案真源。
- 区分三类时间：SCRIPT Scene 索引只给规划预算；正式音频与 `section_map.json` 保存实测时间；工程时间线决定画面实际出现与持续。Plan 只记录时间依据和必要节奏意图，不维护另一份精确时间表。
- 对齐 JSON 必须保留每个非空白字符的 `characters[]`；有发音的字符包含 `start`、`end`，未对齐标点显式标记为 `aligned: false`。
- `section_map.json` 继续表达 Script Anchor 的语义分段，但边界从字级时间证据聚合，不得丢弃或覆盖原始 `characters[]`。
- 自然口语差异继续执行；改变事实、论点、段落结构或 Scene 映射时暂停。
- 需要重新说出口的正文修改会使对应 Recording、Section Map 与引用画面失效；仅同步受影响 Scene 及必要衔接。旧 Accepted Draft 保持不变，新 Draft / Final 仍须经过现有适用性与快照校验。

## 正式 TTS

公共工具从准确 Work / Variant 引用的 Script 正文及稳定 Anchor 生成声音，排除 Scene 索引和制作备注。公共包默认提供方为火山引擎；提供方可通过配置明确选择，不静默回退，不改变文稿或 Plan 格式。一次请求固定正文与生效参数，缓存区分提供方、模型及输入；失败不自动调用其他服务。

生成音频先作为候选，记录输入和参数摘要、提供方、模型、音频摘要与实测时长；明确采用后才成为正式声音。正式声音、`section_map.json` 和 cue 使用提供方可验证的原生字词时间；缺少原生时间证据时明确报告缺失，不能用段落时长或字符均分冒充对齐。音频或正文修订使受影响的新制作对齐与画面失效，旧 Accepted Draft 与 Final 保持原样。凭据通过环境或受保护配置读取，不进入正文、源码、日志、缓存或发行包。云合成、Windows 原生调用和人声听校分别记录证据。

## Animation Plan

`ANIMATION_PLAN.md` 以全片方向加逐 Scene 一节维护设计，元信息由 CLI 从 Variant 与 lock 生成；概览只作索引，每场的 `screen` 保留信息 ID、来源、理解目标与揭示 cue。声音使用 `sound` JSON 导出。按冻结链路选用 [创作指南](visual-design.md) 的 A/B-roll、五层与节奏合同，阅读区域稳定。

专属 Plan、Research 字段与豁免由所选设计卡声明，不以四种模式作为创作入口。数学卡保留符号、图形与歌词时间依据；英语卡保留教学目标、准确拼写、发音依据和阅读节奏，不强加舞台卡的角色、生图或 A/B 配额。旧 `explainer/math-rap` 保留冻结读取语义。用户专属指导随用户卡维护，不依赖自用工具包配送。

Scene 数量、顺序、目标、Hero State、Template、整体主题、文案结构或核心内容实质变化时更新 Plan revision，只重新确认受影响 Scene 及必要衔接。精确 timing、easing、换行、安全区、性能和不改变 Hero State 的布局修复无需新的方向确认；成果与稳定 ID 保留。工程不是另一份文案真源。

生命周期见 [workflow.md](../workflow.md)，权限见根 [AGENTS.md](../../AGENTS.md)；实现与 QA 在 Draft 阶段加载 [hyperframes.md](hyperframes.md)。
