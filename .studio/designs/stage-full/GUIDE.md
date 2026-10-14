# stage-full 设计卡指南（可编辑动态示例）

一句话：在一座小型纸舞台上，用**同一次折叠装置**把「观察 → 分组 → 解释」演成动作，
而不是一页页换幻灯片。示例是编排示范，**不是口播时间证据**：2 / 6 / 11 / 15 秒是可读检查点，
不是口播对齐或真实语音时间。

可运行示例：`example/index.html`（配 `example/style.css`、`example/scene.js` 与共享
`../shared/stage-rig.js`）。宿主在运行目录放入 `runtime/gsap.min.js`、`runtime/scene-binding.js`、
`runtime/stage-rig.js` 与 `media/SourceHanSansCN-Regular.otf`，示例不联网、不带位图与音频。

## 0. 分档：按执行模型选路

- **开阔档**：执行模型为 Claude Opus 级或更强。全卡适用，§1–§8 是机制与自由度；仍建议先写 §4 的镜头表。
- **轨道档**：其它模型，或无法判断。只走下面这一条路，只读本节、`stages/plan.md`、`stages/draft.md`；其余章节先不读：
  1. 写镜头表（`stages/plan.md`「轨道镜头表」合同），表前三行锁画风 / 色板 / 角色；
  2. 逐镜只从舞台动作菜单选积木（`assets/stage-kit/`，接口见各 `blocks/*.md`），参数进、画面出，不手写布局；
  3. 登记前自检（`stages/draft.md`「轨道档自检」）：跑类名覆盖脚本 `tools/check-classes.mjs`、抽查计算样式；缺失先修正，修不了的逐项写进交付说明未处理项；
  4. 登记 Draft，用 `critic round` 产出 Scene 帧条与 ledger，逐 Scene 看三帧（段首、中段、段尾）：主物不在画里或只剩文字卡就回改、重新登记；
  5. 用 `critic record` 记录实际结论。自检与审片只定位问题，不新增审批门；三道人工门以 workflow 为准。

## 1. 来源机制（授权提取）

| 来源 | 机制 | 本卡如何用 |
|---|---|---|
| 折叠装置机制 | `.set` perspective > slide > wall + floor + props：四块 480px 墙板铺满 1920；内对锚在中线 folding ±86°；外板挂在内板上、反向 ±172°；先内后外分级展开并锁定；地面桥绕上边从 -90° 立起；道具脚绕上边从 88° 立起。旧景道具先塌、外/内板再折、整台后退，新地点在视野里搭起。父级 rig 拥有铰链旋转，scene inner wrapper 拥有其他变换 | 共享机制全部落在卡内资产 `assets/stage-rig/stage-rig.js`，本卡 `example/scene.js` 只喂 `{inner, outer, floor, prop}` |
| 圆盘换景与逐件装配机制 | 一个刚性 4400 px 圆盘、两半各载一景、每次整盘转 180°、转正后按件类型（地板立起 / 天幕落下 / 墙板立起 / 梁架下降 / 道具侧入 / 悬挂件下降）0.65 s 冲击 + 0.16 s 回弹逐件装配 | 卡内资产 `assets/stage-kit/blocks/disc-scene.js`，机制来自卡主人自己的 Work 59 背景装置（已授权提取），布景位图不随卡配送 |
| 舞台方向 | 台口小、内容聚焦；幕布只做开场/收尾；无逐段整幕擦除、无常驻侧房；不拿整体淡出/平移替代折叠重建 | 幕布只在 0.80 开、15.40 合；重建是一次真实折叠 |
| 分层舞台机制 | 微型分层舞台（后墙 / 布景 / 主体 / 前景 / 标牌 / 灯光）；幕布开场收尾；因果道具交接与引导光池；剪贴白边 + 偏移投影 | 第 1–4 层分层、`#spot-a/#spot-b` 两支光池、托盘因果指示线、纸盒白边 + `drop-shadow` + 偏移 `box-shadow` |
| 交错入场机制 | 交错入场与空间对比，用实际动作完成转场 | 六个纸盒交错入场、两簇空间对比、重建由折叠动作完成 |

获授权只读提取的机制身份与许可见卡内资产 `assets/stage-rig/asset.json`；不配送原作品或私人媒体。资源及示例摘要统一由 example-manifest.json 保存。

## 2. 分层与固定画幅

- 根 composition：`#stage-full-example`，`data-composition-id="stage-full-example"`，
  `data-width/data-height=1920/1080`，`data-duration=16`。
- 第 1 层 `background`：剧场底色与暗角。
- 第 2 层 `stage`：折叠装置 `#rig`、墙面标识卡、两格托盘、六个纸盒、立牌道具、解释标签。
- 第 3 层 `overlay`：`#spot-a/#spot-b` 焦点光、六条因果指示线、吊灯横杆。
- 第 4 层 `text`：步骤标签、说明句、三步回顾。
- 无第 5 层：示例静音、无口播，故不生成字幕宿主。

## 3. 折叠与铰链归属

- `example/style.css` 只给纸艺皮肤；几何与角度全部来自 `../shared/stage-rig.js`。
- rig 拥有铰链旋转：`.hf-rig-wall-inner-left/right`（±86°）、`.hf-rig-wall-outer-left/right`（∓172°）、
  `.hf-rig-floor`（-90°→0°）、`[data-hf-prop-foot]`（88°→0°）。
- scene wrapper 拥有其他变换：`#rig` 只做后退 `y/scale`；纸盒、托盘、光池只做位移与缩放。
- 展开顺序：内板先开 → 外板随后 → 地面落下 → 道具立起，逐级锁定在 0°。

使用 `rig.rebuild` 积木时，重建区间内铰链角度与包装层位移都由该积木写，工程不得再对 `rig.root` 或 `wrapper` 写 `transform`。

## 4. Plan（详细）

| 段 | 时间 | actor 主体 | object 对象 | audience view 观众看到 | hinge owner 铰链归属 | reading window 阅读窗口 | transition cause 转场原因 | cue | audio |
|---|---|---|---|---|---|---|---|---|---|
| S0 开场 | 0.00–1.30 | 台口边条、幕布、标题卡 | 舞台外壳 | 台口滑入，标题卡出现，幕布从中线拉开 | 无（幕布/台口是场景层位移） | 0.30–1.00 标题卡 | 开演 | 0.05 台口 / 0.12 标题卡 / 0.80 开幕 / 0.95 标题卡让位 | 无 |
| S1 搭景 | 1.30–2.20 | 折叠装置 | 四块墙板 + 地面桥 + 立牌道具 | 内板先开、外板随后、地面落下、道具立起；六个纸盒交错落到台面 | rig | 1.95 起「① 观察」 | 开演搭台 | 1.30 内板 / 1.35 地面 / 1.45 外板 / 1.70 道具 / 1.55 起物件交错 | 无 |
| S2 观察 | 2.30–6.00 | 焦点光 + 六个纸盒 | 一排六个纸盒 | 光从左侧扫到右侧，逐个纸盒轻抬 | 无（第 3 层强调） | 保持「① 观察」稳定 | 逐件查看 | 2.30 光起 / 3.35+i·0.30 逐件点名 / 5.20 光收 | 无 |
| S3 分组 | 6.15–11.00 | 托盘 + 六个纸盒 + 指示线 | 两簇：暖色 3 / 冷色 3 | 托盘进入，光分成两池，纸盒沿指示线移到同色托盘 | 无 | 6.60–11.20「② 分组」 | 按颜色找共同点 | 6.15/6.25 托盘 / 6.40 光分池 / 6.70+i·0.42 移动 / 9.55 归位强调 | 无 |
| S4 重建 | 11.20–13.90 | 折叠装置 + 关键纸盒(amber) | 旧景与关键纸盒 | 道具塌 → 外板折 → 内板折 → 整台后退 → 新地点在视野里重新搭起；关键纸盒停在台上 | rig 折叠；`#rig` 只做后退位移/缩放 | 13.55–14.30「③ 解释」 | 换地点、保留共同点（动作完成转场） | 11.20 道具 / 11.45 外板 / 11.90 内板 / 12.45 后退 / 12.75–13.35 重搭 / 13.55 解释标签 | 无 |
| S5 收尾 | 14.30–16.00 | 三步标签 + 幕布 | 全台 | 三枚步骤标签进入并轻强调，幕布合拢 | 无 | 14.35–15.30 三步回顾 | 收束 | 14.35 标签 / 14.95 强调 / 15.40 闭幕 | 无 |

可读检查点：**2s** ① 观察 + 六个纸盒；**6s** ① 观察完成；**11s** ② 分组完成（暖色 3 / 冷色 3）；**15s** 三步回顾。

## 5. 精确资源

example-manifest.json 是文件、来源、版本、SHA-256、许可、用途和适用包的唯一清单。使用 design_examples.py 装配本地闭合工程；目标有改动时拒绝覆盖。

## 6. 阶段分工（Script / Research / Plan / Draft / Export）

- **Script**：本卡不产出；示例无口播、无字幕、无逐字对齐。
- **Research**：本卡不产出；机制来自已授权的只读提取（§1）。
- **Plan**：§4 表即 Plan；引用机制并声明铰链归属与阅读窗口。
- **Draft**：`example/index.html` + `style.css` + `scene.js` + 卡内 `assets/stage-rig/stage-rig.js` 即 Draft 级示范；`example/kit-demo.html` + `kit-demo.js` 是六个积木的出场示范。
- **Export**：由工作流与宿主渲染；本卡不持有成片、不导出、不做 Windows 验收。

## 7. 技术检查

- **确定性 seek**：唯一 paused 主时间线注册到 `window.__timelines["stage-full-example"]`，同一条交给
  `HarnessScene.bindScene`；`window.__example.seek(t)` 直接重建完整状态，`dispose()` 解绑并 kill 时间线。
  无 RAF / play / autoplay / Date / Math.random，不依赖 seek 事件或回调。正放、倒放、随机 seek、重复 seek 一致。
- **字体**：`document.fonts.ready` 就绪后才首次渲染；`@font-face` 只指向 `media/SourceHanSansCN-Regular.otf`，
  `font-display:block`；不使用网络字体或系统回退排版。
- **布局**：固定 1920×1080；五层各占一层，第 3 层不遮挡第 4 层正文；文字只在阅读窗口内保持稳定。
- **闭包**：只依赖宿主放好的 `runtime/gsap.min.js`、`runtime/scene-binding.js`、`runtime/stage-rig.js`
  与 `media/SourceHanSansCN-Regular.otf`；无图片、音频、字体下载与新依赖；所有道具与布景为原创内联 SVG/CSS 剪贴。

## 8. 声音

示例静音，便于对照编排。若某 Variant 需要音效：**只**为结构重击与关键 hit 配音效
（如 S4 折叠的落定、S3 归位的轻点），**不要**给普通入场自动配音效、不要 BGM；
所有 cue 必须对应同帧可见事件，并按 `data-start` 调度以保证 seek 安全。

## 9. 六种做坏方式（开工前、交付前各对一遍）

| 做坏方式 | 改法 |
|---|---|
| **翻页式 PPT**：第 4 层反复换同位置、同样式的文字卡，第 2 层只换贴图；镜头和台面没有动作。 | 每镜安排具体物的动作，用 rig、托盘或道具完成变化；A/B 按观看任务交接，第 4 层仍守阅读保护，首尾落在物上。 |
| **照搬示范**：把示例或别的 Work 的台口、幕布、吊灯搬来，当作全片常驻页框。 | 只借折叠与交接机制，按题材重写台面与道具；幕布用于开场收尾，换地点由 rig 折叠重建。 |
| **没有具体的物**：概念只有字卡和灰矩形，第 2 层没有可辨认的主体。 | 镜头表逐行写出物与动作；用纸艺道具承载关系，独立解释放第 4 层，附着短标注留第 2 层。 |
| **死背景 / 空画面**：常驻位图始终不动，或主物隐藏、离屏，只剩文字。 | 布景随叙事变化，每个 Scene 检查三帧主物与 rig 的实际可见性；第 2、3 层响应守住节奏，不靠第 1 层漂移充数。 |
| **有真实素材却用代码画**：已有截图、照片或录像，仍造一个缺少证据细节的替身。 | 真实素材按 B-roll 放入第 2 层纸框，保留来源与证据细节；代码负责纸框、附着标注和动作，B 的独立解释仍放第 4 层。 |
| **画风拼贴 + 贴图方块**：写实位图、纸艺、Q 版与毛玻璃同框；带背景的方图直接上台。 | 表前锁本卡纸艺画风、色板与角色状态；道具用带 alpha 的镂空图，方图只进纸框或作墙面贴纸，写实件避开阅读区上方。 |

## 10. 积木清单

积木由 `assets/stage-kit/stage-kit.js` 统一注册与组合，先加载核心，再加载所用积木；参数合同以各 `blocks/*.md` 为准。工程统一传入全片秒数，调用 `apply(t)` 重建画面，结束时调用 `dispose()`。

| 积木名 | 层 | 一句话 | 文档路径 |
|---|---|---|---|
| `disc.scene` | 第 1 层 background | 刚性圆盘半周换景，按件类型逐件装配布景。 | [assets/stage-kit/blocks/disc-scene.md](assets/stage-kit/blocks/disc-scene.md) |
| `rig.rebuild` | 第 2 层 stage | 依次折叠、后退、换皮肤并重新展开纸舞台。 | [assets/stage-kit/blocks/rig-rebuild.md](assets/stage-kit/blocks/rig-rebuild.md) |
| `prop.stand` | 第 2 层 stage | 镂空道具沿顶部铰链立起，带纸边与偏移投影。 | [assets/stage-kit/blocks/prop-stand.md](assets/stage-kit/blocks/prop-stand.md) |
| `inset.broll` | 第 2 层 stage | 纸框滑入局部镜头，支持缩放、平移与附着短标注。 | [assets/stage-kit/blocks/inset-broll.md](assets/stage-kit/blocks/inset-broll.md) |
| `stack.explode` | 第 2 层 stage | 纸质薄板沿 Z 轴拉开、聚焦并收拢。 | [assets/stage-kit/blocks/stack-explode.md](assets/stage-kit/blocks/stack-explode.md) |
| `slot.text` | 第 4 层 text | 固定阅读槽位补位，并在 B 接管时冻结和虚化。 | [assets/stage-kit/blocks/slot-text.md](assets/stage-kit/blocks/slot-text.md) |

`inset.broll` 的 video 模式由积木自己写 `currentTime`，只用于本地预览；正式工程里的视频 B-roll 应走宿主的 `class="clip"` + `data-start` 时序。
