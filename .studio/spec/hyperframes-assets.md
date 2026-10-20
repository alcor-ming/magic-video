# v4.2 卡内资产接线

资产属于设计卡或素材卡的 `assets/<asset-id>/`，身份为 `<card-id>/<asset-id>`。沿用单资产 `asset.json` 的 kind、entry、parameters、usage、example、license 等字段及实际文件闭包校验；可编辑源无需 pack、import 或 accept。

`component list` 从卡库发现资产；`component interface <card>/<asset>` 显示声明用法，`component validate` 校验当前内容。默认围绕所选卡创作，跨卡使用由该卡 references 显式声明，只读解析来源；需要修改时本地化为自有副本，borrowed.json 保存来源摘要与许可。素材卡不进入设计选择。卡库不扫描旧 AssetStore、components 或 backgrounds。列表行的 `usable_by` 与调用层一致：自有资产可由本卡及声明引用它的卡的 Variant 使用，references 行只对声明卡可用（`referenced-use`）；`component list --design <card>` 只列该卡 Variant 能用的自有资产与引用。单张卡无效或同 ID 冲突只停用该卡（以 `card_unavailable` 报错并在 `design list` 显示原因），不隐藏其他卡；冲突 ID 仍拒绝，不遮蔽。

账号中不含 `/` 的旧引用（如 `math-paper@v1`）仍从旧 AssetStore 的已接受包解析，不受所选卡 references 约束，也不出现在卡库列表。旧库未配置或包缺失时，新建、新增 Variant 与重绑明确报缺源，不改写账号或 Work；已冻结 Work 的 vendor/Lock 校验不读旧库。`work component trace [--design <card>] [--account <id>]`（可加 `--work/--variant`）只读报告卡—引用—账号—Work 关系，分开给出来源状态（available/changed/missing/not-accepted/store-unconfigured）与冻结副本（intact/damaged/not-installed）；来源缺失或变化记为 `frozen-intact-source-*` / `older-frozen-copy`，不判作品损坏。不写缓存、索引或 Work。

`asset_layer` 为 building-block、scene-template、content、reference，独立于 kind 与画面五层；沿用画幅、用途与标签筛选，不从名字猜能力。运行时依赖由卡声明、宿主提供，卡内禁止携带 GSAP 副本。

使用显式 Work/Variant 与 Binding 安装实际文件，工程继续持有 vendor、Binding 和 COMPONENT_LOCK.json；旧冻结 Work 的校验不读取当前卡库，来源离线也不失效。Draft 提交保存卡文件与引用资产摘要，status/预览被动提示来源变化。卡片编辑不升级已有 Work；更新卡片快照保留工程副本，列出待重新安装资产，不自动接受或跨 Variant 操作。

以下工程资产与外观合同继续适用。历史 pack/import/accept 实现保留供旧数据与用户迁移，不是 v4.2 活动入口；本任务不读取或迁移旧库。

module/media 使用 Binding schema 3 的 `component_ref`、`scene` 和 `usage`（role / required，可选 fit / focal_point），布局和动作留 Scene，不填旧 Slots。从卡内 `asset.json` 校验可编辑内容；独立样例按 CLI 明确目标用 `component install ... --project <sample>` 与 `component verify --project <sample>`，不注册伪 Work。实际文件仍复制到 `vendor/components/<id>/vN`，Lock schema 2 的 `components[]` 用 `asset_kind` 标记类型。

音频首轮仅支持原生 MP3 media entry，一个音效一个条目；集合关系留外部索引，保留原文件 ID、来源、许可及字节 hash，不伪装成 JS module。沿用 validate/list/install/verify，使用现有 ffprobe/ffmpeg 检查真实格式、时长、编码、采样率、声道及全量解码；缺工具、损坏或伪装文件明确失败。音频入库不等于听感、响度、cue、混音或成片声音接受，不改变宿主唯一时钟。

`asset.json` schema 2 在相同管道加入声明式 theme/background/motion。共同字段为 `contract_version:1`、`parameters`（可覆盖点路径到 type/default/minimum/maximum/enum）和 `compatibility`（ratios）；`asset_dependencies` 保存 `{ref,kind,package_sha256}` 精确依赖，不复用本地 `dependencies` 文件字段。当前静态声明资产跨包仅依赖 media，其他跨包组合明确拒绝；module 背景和 character 按上文合同。Theme entry 为 tokens/fonts JSON，Motion 为 slots/reduced_motion，Background 为 solid/transparent 与自身参数；字体和许可均在文件闭包。Theme 不声明 mode，mode 不参与 Theme 身份校验。

纯声明资产的 Binding schema 3 不要求 Scene，`usage.role` 为该 kind；递归依赖可标 `scope:dependency`，但必须从正常绑定根资产的精确依赖图可达，不构成绕过依赖校验的入口。工程沿用准确 hash 和本地 vendor 校验。JSON 预设不冒充可执行组件，也不因纯 JSON 强加动态 runtime 审片。

新 Account 的 theme/background 为精确引用；motion 字段只为旧账号保留，四个槽位 reveal/emphasis/exit/transition 只能为 null（账号级 Motion 已退役，见下）；省略继承、null 禁用。`overrides` 按 theme/background/motion 分组，组内采用 manifest 声明的点路径，0/false 不视作缺值。新 Variant 的 `appearance_lock` 保存规范化 JSON SHA-256、账户 revision/hash、精确闭包、最终参数与来源、宽高/fps/seed。账号默认不追改旧 Variant；宿主读取 `project/appearance-lock.json` 及 vendor，不重读当前服务默认值。锁校验失败明确停止。

`work appearance resolve --account <id> --appearance-file <json>` 只读解析；`new`/`variant add` 可用相同 `--appearance-file`，其中 `parameters` 为本次参数覆盖，优先级高于账号 overrides。`--theme <id@vN>`、`--background <id@vN>` 固定当前准确接纳 hash，不跟随 latest；`--mode`、`--ratio` 独立，`--fps`/`--seed` 可显式给定。source 画幅必须提供 width/height 后冻结。创建在暂存对象完成 vendor 与 Lock 校验再公布；未知字段、缺依赖或错误 hash 不留下半冻结 Variant。preview 的快照和 metadata 包含该锁及实际闭包；断开源库后仍能验证，不覆盖旧 Draft/Final。

已有 Variant 的显式更新使用 `work --work <id> --variant <id> appearance rebind`，可指定 `--account`、`--theme`、`--background` 或 `--appearance-file`；默认只预检并显示差异，确认目标与差异后 `--apply` 才提交。原位更新不改变 Variant ID 或账号全局默认；保留正文、历史 preview/Final 和旧依赖，外观变化清空当前视觉接受、Draft 接受及 Final 关联，旧文件不代表新外观已接受。相同请求不重复修订。只在明确目标的可编辑 project 中用 `--upgrade-runtime` 升级已知旧 runtime，未知或用户修改版本拒绝覆盖，冻结快照不动。异常 journal 阻断目标的继续使用，运行同目标 `appearance recover` 恢复后再重试，不能手删 journal 绕过。

冻结时复制当前 `runtime/appearance.js` 到工程本地，宿主先校验锁与闭包，再 `await HarnessAppearance.load()`，随后同步 `apply(stage, resolved)`；不引用安装根活跃源码。Theme 输出 `--appearance-*` CSS 变量，`data-appearance-text/card` 是可选宿主标记，不替 Scene 决定布局和文字。字体声明的 family/path/license 必填，文件与许可属于包内 dependencies；style 可为 normal/italic/oblique，weight 可为 1..1000 整数、对应数字字符串、normal/bold 或升序范围字符串（如 `"100 900"`），缺省 normal。load 等待本地字体加载后才返回，布局测量与宿主 ready 必须在其后；缺失、损坏、越界或重定向明确失败，不静默退回系统字体。Typography 字体族 token 映射为实例私有别名，Scene 通过这些 CSS 变量使用字体；重复 apply 不重复加载，结束时调用返回对象的 `dispose()`，仅释放自身字体，不影响其他同名字体实例。

load 默认以当前页面目录为 project；显式 projectURL 必须是同源项目目录并保留末尾 `/`，例如 `await HarnessAppearance.load("./project/")`，不能传外部 URL 或把文件 URL 当目录。

**账号级 Motion 已退役（2026-10-20）**：账号、`--appearance-file`、`new`/`variant add` 都不能再选择非空动作槽，写入即报错。新作品的动作用工具级 `runtime/motion.js`（见 [runtime-interfaces](runtime-interfaces.md#motionjs)）和所选卡的卡片动作包，清单在卡内 `MOTION.md`。只有旧 Work 冻结锁里已有的槽，在不换账号的 `appearance rebind` 中原样带过去，可用 null 关闭，不能新增或替换。旧锁的校验、安装与 `bindMotion` 播放保持不变；下面的四槽 Motion 合同只作为旧 Work 的兼容参考。

受支持链路共用 solid/transparent/module 背景合同。四槽 Motion 资产采用 manifest `contract_version:2` 和 entry `capability_version:2`，精确 ref/hash 不可覆盖。含 v2 Motion 的闭包生成 appearance lock schema/contract 2、resolver 1，旧宿主明确拒绝。工具安装不升级旧 Work 的冻结 runtime；明确目标的更新仍用上文 rebind/upgrade-runtime，不修改历史快照或自动接纳资产。

Motion v2 的 `slots` 与 `reduced_motion` 均须完整声明四槽，选择的 entry 必须等于槽名。公共字段为 duration（非负秒）、easing（none/linear/ease-in/ease-out/ease-in-out）。下例是 entry JSON；资产 manifest 仍按既有 schema 2 包装，只有声明在 parameters 的叶子可覆盖，effect/color_token 不可覆盖，0/false 保留原义：

```json
{
  "capability_version": 2,
  "slots": {
    "reveal": {"effect":"short-rise","duration":0.4,"easing":"ease-out","opacity_from":0,"opacity_to":1,"y":12,"hide_before":true},
    "emphasis": {"effect":"focus-restore","duration":0.2,"easing":"linear","restore_duration":0.2,"color_token":"colors.accent","outline_width":3},
    "exit": {"effect":"fade-out","duration":0.3,"easing":"ease-in","opacity_from":1,"opacity_to":0},
    "transition": {"effect":"crossfade","duration":0.4,"easing":"linear"}
  },
  "reduced_motion": {
    "reveal": {"effect":"fade","duration":0.1,"easing":"linear","opacity_from":0,"opacity_to":1,"hide_before":true},
    "emphasis": {"effect":"focus-restore","duration":0,"easing":"linear","restore_duration":0,"color_token":"colors.accent","outline_width":3},
    "exit": {"effect":"fade-out","duration":0.1,"easing":"linear","opacity_from":1,"opacity_to":0},
    "transition": {"effect":"cut","duration":0,"easing":"linear"}
  }
}
```

opacity_from/to 是相对绑定时基础 opacity 的 0..1 倍率；reveal 的 to 必须为 1，exit 为 0。reveal 可选 fade/short-rise，hide_before 默认 true；false 只取消 cue 前的 visibility 隐藏，不取消起始 opacity。short-rise 和 exit 可选 x/y/scale，组合基础 transform，不自动创建包装层。强调使用冻结 Theme token 的合法颜色形成 outline，restoreCue 由 Scene 显式给定，不推算阅读时间。cut 的 duration 必须为 0。reduced 入退场不得位移/缩放或比常规动作更长，强调两个 duration 为 0，转场为 cut；模式在 load 时固定，bind 的 reducedMotion 布尔值可显式选择，切换须重建实例。

```js
const appearance = await HarnessAppearance.load(); // 包括本地字体 ready，失败不得宣布宿主 ready
HarnessAppearance.apply(stage, appearance);
const motions = [
  HarnessAppearance.bindMotion(revealLayer, appearance, "reveal", {cue: 1}),
  HarnessAppearance.bindMotion(revealLayer, appearance, "emphasis", {cue: 2, restoreCue: 4}),
  HarnessAppearance.bindMotion(exitLayer, appearance, "exit", {cue: 6}),
  HarnessAppearance.bindMotion({outgoing, incoming}, appearance, "transition",
    {cue: 7, endCue: 7.4, overlap: [7, 7.4]})
];
function seek(seconds) { for (const motion of motions) motion.seek(seconds); }
function dispose() { for (const motion of motions) motion.dispose(); appearance.dispose(); }
```

以上元素均为 Scene 已挂载的显式图层。每个绑定返回 seek/dispose，只由宿主秒数定位暂停的原生 WAAPI，不自启时钟、音轨或场景。结束/回拖保留 DOM；零时长在 cue 精确切换；reduced 转场在原 cue 而非 endCue 瞬切。emphasis 的 restoreCue 不早于常规进入结束；transition 的 endCue-cue 等于常规预设 duration，crossfade 的 overlap 必须覆盖整个交接区间，不能自行延长 Scene 或音轨。Scene 必须保持两个不同目标及祖先可绘制，不能在交接前隐藏 outgoing，Motion 只控制目标自身 opacity/visibility。

属性所有权覆盖绑定完整存续期（包括前后填充）：入退场占用 opacity/visibility 及声明的 transform，强调占用 outlineColor/Width/Style，转场占用双目标 opacity/visibility；已有动画或其他绑定争抢相同属性时在创建前拒绝。reveal 与 emphasis 可同元素组合；同元素的 reveal/exit 或转场应使用 Scene 显式隔离的运动层，不依赖创建顺序，也不自动包装表格或 SVG。绑定只采样一次基础样式，宿主不得在存续期争写所属属性；dispose 可重复调用，仅 cancel 自身效果，露出当前基础样式，不覆盖宿主对无关属性的更新。先 dispose 所有 Motion，再释放 appearance 字体。

源侧可运行示例及截图检查为 `tests/motion-browser.mjs`，使用隔离资产/工程的真实 pack/resolve/materialize/load/apply/bind/seek 链路，不接触生产 Work、不导出视频；覆盖常规/reduced 的 16:9、4:3、9:16，不代表任意内容自动适配或 Windows 原生 Studio/音频/Final 已接受。

### Motion v3 与混合闭包

Motion v3 使用 manifest `contract_version:3` / entry `capability_version:3`，四槽和 reduced_motion 均必填，保留 v2 effect 和严格字段校验。各槽可混用 v2/v3 包；appearance lock schema/contract 是闭包中最高 Motion 版本，resolver 仍为 1，新宿主按各 entry 自身能力校验，旧宿主拒绝新 lock。冻结旧 Work 不自动升级；准确目标的升级仍须显式 rebind/upgrade-runtime。

新增 reveal 为 pop / stamp / wipe / glitch-in；emphasis 为 pulse / shake / wobble / glow；exit 为 pop-out / wipe-out / glitch-out；transition 为 wipe / push / glitch-cut。公共字段 effect/duration/easing；入退场仍必填 opacity_from/to，reveal 可选 hide_before。pop、pop-out 支持 x/y/scale，stamp 另支持 rotate（度）；glitch-in/out、shake 支持 x/y，pulse 支持 scale，wobble 支持 rotate；glow 必填冻结 Theme 的 color_token，可选 blur。wipe、wipe-out、push 可选 direction（left/right/up/down）。不属于该 effect 的字段拒绝；effect/color_token 不可作为参数覆盖。

v3 的缓动增加 back-out 与固定采样 spring；normal 可选整数 hold_fps（1..240），以 cue 为相位原点只量化中间帧，cue 与结束状态精确，不能移动 endCue/overlap。新 emphasis 为一次性动作，不需要 restoreCue，结束恢复采样的基础样式；focus-restore 保持原合同。新入退场 reduced 使用 fade/fade-out，强调时长 0，转场 cut，不使用 hold_fps 或过冲缓动。每个 effect 仅拥有实际使用的属性，争抢拒绝，不自动包装层。

新版 v2/v3 Motion 绑定在 `__hfRhythmSources` 注册带 target/cue 的 `motion_<slot>` 候选，dispose 注销；探针只计目标可见且状态实际变化的事件，不把 WAAPI 的存在当作通过。

账号外观可完整指定 Theme/Background；跨账号的风格叠加只指定 background、省略 theme。后者保留账号 Theme，前者覆盖，沿用当前解析合并规则，不新增资产 kind。

### 动效 B-roll module

可选 `broll` 块及挂载示例见 [创作合同](broll-assets.md)。资产校验检查角色、时长、timing、插槽/参数、各画幅安全区与完整 usage/examples；无 broll 的 module 不变。`component list --broll-role hook|concept|transition` 与 `--tag` 组合筛选，`component interface` 展示完整 broll。插槽由 Scene 源码传入，不改变 Binding schema 3、不新增 Plan 解析字段。

镜头导出 mount，按全片秒数 renderAt，返回实际 moments 与 dispose；stage/text 分别挂第 2/4 层并交给既有 HarnessRolls。可复用新工程冻结的 `runtime/broll.js` 做输入、字体容量、闭包路径和时间映射校验，module 自身资源仍走正常离线闭包。开发合成样例与双 Theme/双画幅/两种 timing 的真实管道检查见 `tests/broll-browser.mjs`，不携带生产库资产。

优先复用能独立解释一个含义的语义视觉对象及其内部联动，由 Work-local Scene 安排本期叙事和媒体。已有 helper 保留，只有真实独立变化或复用需求才抽取，不强制图形/动作/布局工厂拆分。组件可由 WSL 或 Windows 开发，空间舞台可内聚保存相机、遮挡和光照。布局适配须实测可读性，不以模块数量或双画幅完成率验收。

合同范围内的新资产通过自身元数据发现；新增合同能力须升级工具，不靠标题或 kind 改名绕过校验。官方 Registry 的 block / snippet 只在明确选中后导入候选，完成本项目接线与校验后使用，不向上游发送私有文案或缺口。Work 用既有 vendor / Binding / Lock 固定副本与依赖；不读 WSL 活跃源码、不链接 `latest`，同身份版本不同内容拒绝覆盖。没有匹配实现时记录 `custom:<slug>` 并在可编辑源实现，不覆盖冻结 vendor；仅工具或宿主缺口交 WSL。现有已实现资产合同之外的能力，不冒用 Component 合同。

### 固定第三方来源

`design source-add <https-repository-url> --commit <完整SHA>` 需要本机 Git，仅 fetch/archive 到用户卡根 `.sources/`，不执行上游、不配送来源缓存。逐文件摘要与许可线索在 `source.json`，默认 `unreviewed`；制作卡前逐文件确认许可并排除非开放角色/数据。外部 `borrowed.json` 记录 source.kind=external、url、commit、files（sha256/license/attribution）；新 commit 先缓存再 `design compare <card> <asset> --commit <SHA>`，不自动同步。提示词合集只记录参考机制，不缓存原文。

抽取结果是普通用户卡。风格进入 stages/Plan/GUIDE，色板进入 Theme，缓动/转场进入卡片动作包（替换工具动作的实现或加本卡独有动作，列进卡内 `MOTION.md`），绘制进入静态闭包 module。不得保留 eval、同步 XHR 或运行时外网加载；许可和本项目合同取舍写入 GUIDE。引擎型 module 的文字、字体与确认见 [B-roll 合同](broll-assets.md#非-dom-文字与字体)。
