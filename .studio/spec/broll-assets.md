# 动效 B-roll 与风格资产创作

本指南适用于用户设计卡或素材卡内的动效 B-roll 镜头模块创作。模块是 B-roll 的一种资产。任务需求使用 [BROLL Brief](../templates/BROLL_BRIEF.template.md)，资产身份为 `<card-id>/<asset-id>`。

## 创作与校验

1. 明确语义、关键时刻、插槽、适用设计与限制，按用户需求选择方向。
2. 在用户卡的 `assets/<id>/` 制作 module、完整 usage 与独立 sample；跨卡复用声明 references，需要改造时先 localize。
3. 在官方 Studio 查看样例，覆盖声明画幅、冷启动、重复 seek 与倒跳；按实际需要检查 Theme、容量与最短/默认/最长时长，不导出 Draft 视频。
4. 按单资产合同与卡片合同校验，不设库级 pack/accept；许可、署名与 borrowed.json 来源链随本地化保留。
5. Work 采用后通过 vendor/lock 持有副本；卡片变化不覆盖工程，更新快照后报告需要重新安装的资产。

## 外观复用

- 账号外观：完整 Theme + Background + Motion，定义某个账号的整体样子。
- 风格叠加：appearance 文件只写 background / motion，省略 theme，继承账号 Theme；Motion 按槽合并，适合矩阵账号。
- appearance 文件写了 theme 就会覆盖账号 Theme，不会自动跟随账号。接口卡说明适用哪种用法和限制。
- 颜色和字体只读 `--appearance-*`。先制作并校验风格叠加，再做镜头；普通入退场、强调和转场引用 Motion，只有整段语义表演留在 module 内。

Motion v3 支持 pop、stamp、wipe、glitch-in；pulse、shake、wobble、glow；pop-out、wipe-out、glitch-out；wipe、push、glitch-cut。`back-out` / `spring` 为固定缓动，`hold_fps` 为 1..240 整数；低帧量化只影响过程，不移动 cue/endCue。每个新 effect 配 reduced 等价形式，规则见 [资产合同](hyperframes-assets.md)。

## 镜头接口

module 导出 `mount({stage, text?, appearance, slots, params, startCue, endCue, cues})`，返回 `renderAt(t)` / `moments()` / `dispose()`。宿主使用全片秒数，镜头不自启时钟，不依赖历史帧、随机数或 `onUpdate` 写状态。使用公开 Rolls 时，把第 2 层 `stage` 交给 `media`，把采用的 `text` 交给 B 屏幕文字组。取用前查 `asset.json` 的 `broll.slots`。有 `layer: text` 插槽就提供 `text` 宿主。Rolls 错相与 `handoff: "cut"` 按运行时接口接线。镜头不要写宿主 stage/text 的 opacity、visibility、filter，动画放在其子容器；窗口和属性所有权见 [runtime-interfaces.md](runtime-interfaces.md#rollsjs)。

`asset.json` 的可选 `broll` 块必填字段：

| 字段 | 合同 |
|---|---|
| role / takeover | hook、concept、transition / inline、full-frame |
| duration | `{min,max,default}`，秒，`0 < min <= default <= max` |
| timing | stretch 比例映射；hold-end 只延长末态，min 等于 default，不能截短表演 |
| key_moments | 默认时长下有序、唯一的相对秒数，范围 0..default；仅说明，不直接计数 |
| sfx_cues | `[{time,purpose}]`，默认时长下相对秒数与用途，按 timing 映射 |
| slots | 以插槽名为键；text/number 声明 type、layer（stage/text）、max_chars；icon/media 只声明 type |
| params | 与 manifest `parameters` 相同的点路径/type/default/范围，调用时以点路径为键传值 |
| carries_info | 布尔；false 不允许 text 层插槽、不新增可读信息 |
| caption_safe_zone | 每个 compatibility.ratios 对应归一化 `[x,y,width,height]`，矩形在 0..1 内 |
| usage / examples | 完整挂载代码字符串 / 至少一个字符串示例，接口卡全部展示 |

text 接受字符串，number 接受有限数字，`max_chars` 按 Unicode 码点计数。字体必须在冻结 Theme 中，最长内容按每个画幅实测，超容量明确失败，不缩字号或截断掩盖问题。

icon 传 `{ref:"lucide:plug@1.45.0",path:"icons/plug.svg"}`：先安装准确图标集，再由宿主 `work icons use` 取进工程；只接受精确引用与核对过来源、几何的本地 SVG。media 传已安装 media 的 entry 相对路径；外部 URL、路径穿越和未登记文件均拒绝。插槽值不放进 Binding，Binding schema 3 不变。

新工程冻结 `runtime/broll.js`。作者可复用 `HarnessBroll.mount(metadata, options, build)` 做输入和容量校验、时间映射与节奏注册；不另建挂载框架。`build(context)` 返回 `renderAt(localTime,globalTime)`、`events:[{time,target}]`、文字 `labels:{slotName:element}` 和 `dispose()`。它只创建自己的子节点，不改变宿主 roots 的结构；标签在正确层、使用冻结字体和真实插槽内容。`events` 使用默认表演的相对时间并绑定真实可见目标；`moments()` 返回这些运行时事件映射后的 `key_moments` 与映射后的 `sfx_cues`。dispose 删除自身节点与注册，失败也清理。

```javascript
// index.html first loads runtime/appearance.js, runtime/rolls.js and runtime/broll.js.
const appearance = await HarnessAppearance.load();
const {mount} = await import('./vendor/components/example/v1/main.js');
const shot = await mount({stage: bStage, text: bText, appearance,
  slots: {title: 'Broll signal', value: 42}, params: {},
  startCue: '示例开始', endCue: '示例结束', cues});
const rolls = HarnessRolls.mount({cues, scenes: [{id: 'S01',
  startCue: '场景开始', endCue: '场景结束', a: aGroup,
  b: [{startCue: '示例开始', endCue: '示例结束', retreat: 'hide', media: bStage, text: bText}]}]});
async function renderAt(t) { shot.renderAt(t); await rolls.renderAt(t); }
const {key_moments, sfx_cues} = shot.moments();
function dispose() { shot.dispose(); rolls.dispose(); appearance.dispose(); }
```

## 画面与节奏自检

- 整帧镜头仍在第 2 层，可盖背景；overlay 在上，captions 始终最高。主图与文字避开字幕安全区。
- 文字落点、上屏提炼规则、信息完整性与阅读保护按 [visual-design.md](visual-design.md#文字归属与阅读)；embedded 文字仍执行下述资产声明、文字清单与人工确认合同。使用 Rolls 返回 A 时，恢复离开时的状态。
- 纯注意力镜头不新增可读信息；事实约束不豁免，示意数据或界面标 `data-hf-schematic`。
- `hold_fps` 等低帧量化只用于原地拍章、pulse、wobble；平移、旋转、翻面、飞离与重排按宿主时间逐帧求值，缓入缓出、不用回弹过冲，同一时刻只做一个主动作。默认时长下运动件单帧位移不超过短边约 4%、旋转不超过 5°；移动件保持不透明，深色背景上的贴纸与线条要有可见切边，结论帧不压暗。
- 两个 Theme、全部画幅、最短/默认/最长时长都检查容量与 seek。顺播、直接 seek 与回拖结果一致，末帧有收束。
- 挂载时把带 target、实际秒数的事件注册到 `__hfRhythmSources`，dispose 时注销。探针仍验证可见变化，声明不能冒充事件；hold-end 尾部不自动补节奏，超过 2 秒需处理或声明合理例外。
- 接口卡写清语义用途、不适用情形、一个完整填槽例子和样例工程。验收标准是使用者不看实现源码也能按 usage 正确挂载。

首批建议先做贴纸拼贴（stamp / wobble；hold_fps 仅限原地动作），再做赛博 HUD（glitch / wipe / glow）和综艺花字（pop / shake / pulse / spring）。这是生产根的后续库制作，不是 Harness 开发或部署自动执行的内容。

## 非 DOM 文字与字体

Canvas/WebGL module 提供 `texts()` 完整清单；纯图形画布返回空数组，DOM 文字沿用扫描。`HarnessBroll.mount` 的 build 返回值提供 `texts()`，绑定也公开 `texts()`。每项为 `{id, text, start, end, kind, embedded, text_type?, region?}`：时间为片段本地秒，工具映射到 Work cue 窗；kind 为 attached/independent。独立 embedded 文字必须给出 `text_type` 并匹配该资产 `asset.json` 的 `text_ownership: {"mode":"embedded","kinds":["title"]}`。例如 Hook 3D 标题使用这一明确声明，不再享有隐式例外。region 可为归一化 `{x,y,width,height}`。

文字清单必须覆盖整个片段，不能只返回当前可见文字。运行时校验时间、唯一 ID 和归属，采集到 `__hfTextSources` 并在 dispose 注销。非 HarnessBroll 的 module 由宿主把完整 `texts()` 提供函数注册到该 Set（时间映射为 Work 秒并补 scene/asset/font_family），dispose 必须注销；无字画布也显式注册空清单。多个已安装资产同名时传入完整 `assetRef`，避免把文字归属到另一张卡。上屏提炼规则、数值事实核对和阅读时长使用同一清单；位置、遮挡、挤动标为 `delegated`，不能表示检查通过。未声明的独立 embedded 文字报告错误。

设计卡 `fonts` 使用 `[{"family":"CardFont","path":"fonts/body.woff2","license":"fonts/OFL.txt","weight":400,"style":"normal"}]`，路径均在卡内。卡字体优先于 Theme 字体，Lock 保存摘要和项目内安装路径；第 4、5 层与适配引擎统一使用 `appearance.fontFamily`。字体与许可进入快照闭包；TTF/OTF/WOFF/WOFF2 的 Unicode cmap 加浏览器实际字体检查验证用字，缺字不能接受。信息文字与字幕采用卡字体；完整字体或覆盖 Draft 实际用字的子集均可。

Draft 登记会固定 `module-texts.json` 及其摘要；包含 embedded 文字时，`preview accept <draft> --confirm-embedded S01 --confirm-embedded S02` 逐 Scene 记录用户已作出的确认，缺少任何 Scene 则拒绝。全局关闭 Draft 确认不会替代这项逐 Scene 确认。记录保存到 Draft 的 `embedded-text-acceptance.json` 和 Variant 接受状态。不得代替用户虚构确认。
