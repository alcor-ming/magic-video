# Runtime Interfaces

按接口卡取用已冻结的助手与组件，不读源码；只有派生实现时才读源码。下列示例中的 DOM 节点、lock、appearance 与 cues 均由当前工程提供，不能从活跃安装根加载。画幅默认支持 16:9、9:16；组件选择其已登记的对应画幅包。

## cues.js

用途：正式对齐的语义时间查询；画幅：16:9、9:16；占层：无。参数：`load(url?)` 或 `from(data)`；`find(token,{nth,within,edge})`。`load` 默认按 `document.baseURI` 解析 `runtime/cues.json`，只允许页面同源且不跟随重定向。返回 `data/find`，不创建播放时钟。

已生成节拍网格时支持 `find({bar, beat})`：小节和拍从 1 编号；拍号和首个强拍必须明确，弱起不计入第一小节，缺网格或越界时报错。不要将小节/拍查询与词 cue 的 nth/edge 混用。

```js
const cues = await HarnessCues.load();
const at = cues.find('主机', {nth: 1, edge: 'start'});
```

## captions.js

用途：字幕分组与逐字高亮；画幅：16:9、9:16；占层：5。参数：`mount(host,cues,{ratio,enabled})`，host 必须声明 `data-hf-layer="captions"`；返回 `groups/renderAt/dispose`。

```js
const captions = HarnessCaptions.mount(captionHost, cues, {ratio: '9:16'});
captions.renderAt(at);
```

## figures.js

用途：角色或图片的确定性动作；画幅：16:9、9:16；占层：2 或 3，由挂载节点归层。参数：`load(lock,{projectURL?,cues?})`；`figure(el,ref)` 或 `image(el)`；动作 `enter/exit/idle/bounce/squash/pan/zoom/point(cue,options)`、`state(cue,id)`、`talk(intervals?)`。options 可设 duration/x/y/scale/amplitude/cycles/angle；返回 `renderAt/dispose`。

```js
const figures = await HarnessFigures.load(lock, {cues});
figures.image(imageHost).enter('主机', {duration: 0.3});
await figures.renderAt(at);
```

## rolls.js

用途：A/B 切换、冻结与返回；画幅：16:9、9:16；占层：A/B 文字 4、装饰和媒体 2。参数：`mount({cues,scenes,reducedMotion?})`，每场 `id/startCue/endCue/a/b/continuation?`；返回 `renderAt/dispose`。A 的 items 必须是 text 内不重复的子元素，不能用 text 宿主本身。

```js
const rolls = HarnessRolls.mount({cues, scenes: [{id: 'S01', startCue: '主机', endCue: '结束',
  a: {text: textHost, items: [{id: 'I01', cue: '主机', element: titleElement}]}, b: []}]});
rolls.renderAt(at);
```

新版冻结运行时对 A/B 交接采用固定错相窗口：媒体在 B 起点前最多 0.2 秒开始，在起点落定；A 组在其后退场/虚化，B 文字稍后出现。返回时 B 文字先退、A 在返回 cue 恢复、媒体最后淡出。窗口在 Scene 边界与相邻 B 段之间裁剪，短 B 段按比例压缩。B 对象可加 `handoff: "cut"`，减少动态同样瞬切。A 时间只在原始 B 区间暂停。

Rolls 独占 A/B 宿主的 opacity、visibility、filter；与 Motion 或其他动画冲突时挂载失败，给内容单独的子容器。时间状态与节奏事件均按实际目标起点计算；dispose 恢复原样式。旧工程冻结的 runtime 不升级，仍保持原交接行为。

## appearance.js

用途：冻结外观 token；`bindMotion` 只供旧 Work 冻结锁里的四槽账号 Motion 使用，新作品的动作见上文 motion.js；画幅：16:9、9:16；占层：沿调用节点，不生成额外层。参数：`load(projectURL?)`、`apply(stage,appearance)`、`bindMotion(el,appearance,slot,{cue,restoreCue,endCue,overlap,reducedMotion})`；动作返回 `seek/dispose`。

```js
const appearance = await HarnessAppearance.load();
HarnessAppearance.apply(stage, appearance);
const motion = HarnessAppearance.bindMotion(titleElement, appearance, 'reveal', {cue: at});
motion.seek(at);
```

## scene-binding.js

用途：接宿主 hf-seek，统一生命周期；画幅：16:9、9:16；占层：无。参数：`bindScene({start,duration,timeline?,renderAt,ready?,dispose?})`，renderAt 收到 Scene 本地时间；`bindExplainer({duration,captions,background,figures,ready,renderAt})` 收到全片时间；返回 `ready/seek/dispose`。

```js
const binding = HarnessScene.bindScene({start: 0, duration: 8,
  renderAt: t => diagram.renderAt(t), dispose: () => diagram.dispose()});
await binding.seek(at);
```

## motion.js

用途：工具级标准动作（出现、退场、强调、移动到、落定、换场）；画幅：16:9、9:16；占层：沿调用节点。参数：`create({card?})` 返回实例，动作为 `appear/exit/emphasize/moveTo/settle/transition(targets, {at, duration?, strength?, stagger?, to?})`，再加卡片独有动作；`menu(card)` 列出合并后的动作清单；返回实例的 `apply(t)` 收全片时间，`dispose()` 恢复样式。卡片动作包（如 `stage-full/stage-motion`）用 `registerCard` 替换实现或加独有动作，不改参数；须在 `runtime/motion.js` 之后加载。同一物体同一属性的时段重叠会直接报错。账号四槽 Motion 已退役，不经过本接口。

```js
const motion = HarnessMotion.create({card: 'stage-full'});
motion.appear([box1, box2], {at: 2.4, stagger: {span: 0.3}});
motion.apply(at);
```

## Background

用途：冻结模块背景；画幅：16:9、9:16；占层：1。参数：`mountBackground(stage,appearance,cues)`，声明 renderer/entry/parameters；模块 `create(el,params,{seed,width,height})` 返回 `renderAt/dispose`。

```js
const background = await HarnessAppearance.mountBackground(stage, appearance, cues);
await background.renderAt(at);
```

## Sound

用途：从唯一批准 Plan 导出音轨；画幅：16:9、9:16；占层：audio group，不占视觉层。参数：Plan sound JSON 的 bgm/ref/start_cue/end_cue/gain 与 sfx/ref/cue/event/tier/gain；事件必须与可见变化对应。

```sh
work --work <id> --variant <id> sound build
```

## Icons

用途：取用冻结图标集中的精确图标；画幅：16:9、9:16；占层：随语义内容通常 2/3，按所选组件合同挂载。参数：图标精确引用 `lucide:<name>@<version>`、工程内 SVG 目标路径、主题 color/stroke token。取用保留 data-icon 来源与路径几何，使用 currentColor；不联网，不手绘替代标准图标。自制示意使用 `custom:` 引用并纳入闭包。

需要继承宿主主题时将取用的 SVG 内联到语义节点，保留来源标记；独立 `<img>` 文档不能继承宿主 CSS 变量。Plan 简写如 `lucide:plug` 只在冻结闭包内恰有一个版本时有效，多版本必须显式指定。图标引用、语义 cue 和上屏内容记录在所选链路的 Plan 中，实际 SVG 随工程冻结。

```sh
work --work <id> --variant <id> icons use lucide:plug@1.45.0 --output icons/plug.svg
```

## broll.js

用途：为冻结 B-roll 镜头校验插槽并映射时间；画幅：16:9、9:16（以资产声明为准）；占层：第 2 层 stage 与独立第 4 层 text；参数：冻结 manifest、appearance、slots、params、语义 startCue/endCue 与 cues。

```js
const shot = await HarnessBroll.mount(metadata, options, build);
shot.renderAt(globalTime);
shot.moments();
shot.dispose();
```

冻结 module 的入口为 `mount({stage,text?,appearance,slots,params,startCue,endCue,cues})`，返回 `renderAt(t)` / `moments()` / `dispose()`。stage 为第 2 层 B media，text 为独立第 4 层 B 文字组；宿主按全片秒数调用，既有 HarnessRolls 决定 B 区间和 A 的冻结/恢复。时长越界、类型/容量不符、外部 URL 与闭包外媒体明确失败，不把插槽写进 Binding。

`runtime/broll.js` 的 `HarnessBroll.mount(metadata,options,build)` 可复用严格输入检查、Theme/冻结字体容量、stretch/hold-end 时间映射与运行时事件注册。build 返回 time-pure renderAt、带实际 target 的默认相对秒数 events、文字 labels 与 dispose。`moments()` 返回 `{key_moments:[全片秒数],sfx_cues:[{time,purpose}]}`；关键时刻来自实际注册事件，manifest 描述不直接计数。dispose 注销自身事件并释放节点；完整取用示例和 schema 见 [broll-assets.md](broll-assets.md)。

## 详细接线

A/B 接线使用冻结到工程的 `runtime/rolls.js`：`HarnessRolls.mount({cues, scenes})` 返回 `renderAt(t)` / `dispose()`，由宿主按时间求值。每个 Scene 提供 `id/startCue/endCue`、`a:{text, decorations?, items:[{id,cue,element}], renderAt?}` 与 `b:[{startCue,endCue,retreat:"hide"|"blur",media,text?}]`。A text 与 B text 属于第 4 层，decorations 与 media 属于第 2 层；跨 Scene 使用 `continuation:{from,readItems}`。B 期间 A 的本地动作时间暂停，返回与直接 seek 均恢复同一状态；退出时释放实例。组件按自身合同声明占用层，不自带根背景或字幕宿主。

`work --work <id> --variant <id> cues build --alignment <characters.json>` 读取已批准的 `work script text` 口播文本，与 `characters[]` 字符级对齐，生成 `project/runtime/cues.json`，冻结文本/对齐来源 SHA-256、逐字符 start/end/aligned 与不一致报告。未匹配字符标为 `aligned:false`，不插值。将本地 `cues.js` 纳入闭包，通过 `await HarnessCues.load()` 后的 `find(token, {nth, within:[start,end], edge})` 查询全局秒数；nth 从 1 起，edge 为 start/end。缺词 `cue_not_found`、未指明重复词 `cue_ambiguous`、命中未对齐字符 `cue_unaligned` 均明确失败。

`captions.js` 按标点与画幅最大字数分组，以 `renderAt(t)` 直接求当前字幕与逐字高亮。未对齐字跟随下一个已对齐字的起点，不捏造时间；主题 `--appearance-*` token 控制样式，安全区位于各画幅 title-safe 底部。通过 `scene-binding.js` 的 `hf-seek` 驱动，关闭开关时不创建 captions 宿主，不能另挂播放时钟。

`work --work <id> --variant <id> sound build` 必须从已批准 Plan 中恰好一个 `sound` JSON 代码块导出 `project/sound.json`；缺失、重复或未批准均失败，不回退读取可变的 sound.json。结构为 `bgm: {ref,start_cue,end_cue,gain}` 与 `sfx: [{ref,cue,event,tier,gain}]`，cue 为字符串或 `{token,nth,within,edge}`。构建器更新 index.html 中命名标记包围的音轨与 audio group，SFX `data-start = cue - hit_offset`，负起点明确失败，需调整素材/计划而非静默裁切。BGM 利用锁定 0.8.150 的 `hf-audio-group` / automation 在人声区间 ducking；只引用 appearance lock 或已安装 Binding 的本地 media 闭包，越界报 `sound_asset_outside_closure`，预览与 Final 共用输入。

Background 的 `renderer:"module"` 供受支持链路共用，声明包内 JS `entry` 与 `parameters`（可含 `moods:[{cue,tint}]`）。`HarnessAppearance.mountBackground(stage, appearance, cues)` 加载导出的 `create(el, params, {seed,width,height})`，返回 `renderAt(t)` / `dispose()`；背景由时间纯函数求值、按 cue 变色，经 scene-binding 接宿主，不依赖历史帧或自行 RAF。文件与参数进入冻结闭包。

`character` 是 schema 2 声明式资产，entry `character.json` 包含 `name`、`profile`、`series_style`、`reference`、`states:{id:{file,anchor:[x,y],facing:"left"|"right"}}`、`default_state`、`provenance`。状态图必须为带 alpha 通道的 PNG，锚点在图像范围内，默认状态存在，参考与状态文件都在包内。沿用 pack/validate/accept/install/verify，Binding schema 3 的 `usage.role` 为 character；同身份同版本不同内容拒绝覆盖。

`await HarnessFigures.load(lock)` 从闭包加载角色，提供 `figure(el, characterRef)` / `image(el)`，支持 enter/exit/idle/bounce/squash/pan/zoom/point/state(cue,id)/talk(intervals)。动作按 `{start,duration,fn(localT)}` 登记，由 `renderAt(t)` 合成 transform 与状态图，不依赖 tween 回调。talk 使用 cue 数据中相邻已对齐字符间隔小于 0.35 秒合并的人声活动段，不做骨骼或口型。Helper 与所用资源复制进工程并随快照冻结，不读取安装根活跃源码。

`work component import-sfx --from <hyperframes 包根> --source <AssetSource 根>` 读取本机 `dist/skills/media-use/audio/assets/sfx/manifest.json` 与 `CREDITS.md`，生成带 purpose/tags/license/hit_offset 的可编辑 media 源，不自动 accept。ffmpeg `silencedetect` 的 -40 dB 门限求首个非静音点；检测失败用 0 并标注 `hit_offset_estimated:false`。第三方音效不进入仓库或发行包，WSL 测试仅使用合成夹具。

优先复用 timestamps 与 `section_map.json`。语义 cue 定位 Anchor、字符范围或明确 occurrence，未可靠对齐的字符不均匀插值。源片段采用半开区间，按 `timeline_in + (source_time - source_in) / rate` 映射；多 take 明确选择，被删除词无有效 cue。单 Scene 预览减去 crop 起点而不改原对齐，仅在输出 fps 时量化。

文字新增按所对应短句或核心词的实际起点快速揭示，不能等整句结束或提前透露后文；非文字视觉事件再按语义选择动作开始、完成或结果可读。SFX 按内部 hit offset 反算起点，负起点明确 preroll/裁切/替换。Preview 和 render 共用 cue/mix 输入，不以 seek 回调即时播放音轨；关键画面同样可按目标时间重建。音乐分析只在需要时按 hash/参数离线缓存，不依赖实时 WebAudio；缺 BGM 或 Blender 不阻塞非依赖场景。

在 Studio 验证源声音、工程映射、命中前后帧及连续播放；未试听明确说明，计算误差不冒充声学测量精度。已有音轨不重复对齐。

## Work 语音与 showcase 素材工具

`tts generate` 从当前 Script 生成候选；`tts adopt <hash> --alignment <Work-relative.json>` 只采用全稿及工具测得的字符对齐（`provider-native` 或带 `engine` 的 `forced-alignment`），接入已有 voice / cues / section_map，并写入 `runtime/alignment-report.json`（硬错误拒绝采用，可疑项供逐字核对）；`tts audit` 只读预检。提供方配置、替代脚本请求／结果和失败边界见 [README](../../README.md#showcase-补充工具与正式配音)。

`showcase stage --output <project-relative-dir>` 与 `showcase cast --input <Work-relative-image> --output <project-relative-dir>` 生成可选素材；返回 manifest 含工具版本、参数与文件 hash。生成后将使用的 PNG 作为普通本地媒体接入 Scene，按既有闭包冻结；不自动改 Plan 或接受状态。
