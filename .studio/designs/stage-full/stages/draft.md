# stage-full · Draft 阶段指南

## 机制与实现

- 文件：`example/index.html` + `example/style.css` + `example/scene.js` + 卡内资产 `assets/stage-rig/stage-rig.js`（四块墙板、内对 ±86°、外板反向 ∓172°、地面桥 -90°、道具脚 88°，先内后外分级展开）。
- 四层：第 1 层 `background`、第 2 层 `stage`、第 3 层 `overlay`（`#spot-a/#spot-b`、因果指示线、吊灯横杆）、第 4 层 `text`；无第 5 层（示例静音）。
- 单一 paused 主时间线注册到 `window.__timelines['stage-full-example']`，同一条交给 `HarnessScene.bindScene`；无 RAF / play / autoplay / Date / Math.random。
- 外部 seek：`window.__example.seek(t)` 直接重建完整状态，`dispose()` 解绑并 kill 时间线；不依赖 seek 事件或回调。

## 资源闭包、字体与释放

- 资源闭包：只依赖宿主放好的 `runtime/gsap.min.js`、`runtime/scene-binding.js`、`runtime/stage-rig.js` 与 `media/SourceHanSansCN-Regular.otf`；无图片、音频、字体下载与新依赖。
- 字体：`document.fonts.ready` 就绪后才首次渲染；`@font-face` 只指向 `media/SourceHanSansCN-Regular.otf`，`font-display:block`；不使用网络字体或系统回退排版。
- 布局：固定 1920×1080；五层各占一层，第 3 层不遮挡第 4 层正文；文字只在阅读窗口内保持稳定。

## 具体技术检查

- 确定性 seek：正放、倒放、随机 seek、重复 seek 一致；对 `[t3, 0, t1, t3]` 抓帧比较同一时刻。
- 释放：`dispose()` 解绑并 kill 时间线后不再响应 seek。
- 声音：示例静音；若某 Variant 需要音效，只为结构重击与关键 hit（如 S4 折叠落定、S3 归位轻点）配音效，不给普通入场自动配音效、不要 BGM；所有 cue 对应同帧可见事件并按 `data-start` 调度以保证 seek 安全。
- 不新增几何/函数预置、通用角色库、AI 概念图库或 BGM 生成。

## 前景自检（登记 Draft 前做）

自检只定位问题、不判通过、不新增审批门；三道人工门以 workflow 为准。修不了的项逐条写进交付说明未处理项，与 `rhythm_gap` 的处理方式一致。

- **先静后动**：先把每个 Scene 写成停在结束状态的静态构图，登记一次 Draft，用 `critic round` 帧条请能看图的一方（用户或 critic）看构图；主物大小、位置定下来再补动作。执行模型看不了图时，不要自己判断构图是否成立。
- **三帧核对**：登记后用 `critic round` 的 Scene 帧条看每个 Scene 的段首 +0.5 s、中段、段尾 −0.5 s。主物不在画里、只剩文字卡，或主物明显小于台面区的 40%，就回改、重新登记。本地排查可用工程调试参数或 `window.__timelines` seek，自己截的帧不作交付证据，不入卡仓。
- **覆盖率线索**：`preview diagnose` 报告的 `stage.findings` 里，`stage_sparse` 是前景（第 2 层，扣除 `data-hf-set` 布景件）覆盖率低于本卡阈值的区间，`stage_empty` 是舞台层完全空。按 plan「规则」第 2 条回改。
- **计算样式抽查**：本镜应在画里的物，其第 2 层节点的 `visibility` 为 `visible`、`position` 为 `absolute`（被 B 接管而隐藏或虚化的 A 组不在此列）；用默认背景时 `.hf-rig` 节点必须存在。用 `getComputedStyle` 核对实际值，不以代码存在代替。
- **可见性归属**：`.scene` 这类容器若写 `visibility:hidden`，子节点必须由同一函数统一写回 `visible`；只改 `opacity` 的节点会被继承隐藏。积木节点经 `kit.shown` 已成对写入。
- **类名覆盖**：JS 里创建的每个类名必须有样式契约：在工程 `style.css` 或 rig 注入的 CSS 中有规则，或在 JS 里被当作选择器引用。跑 `node tools/check-classes.mjs <工程目录>`（Windows 侧用 runtime 自带的 node），退出码非 0 先修正；结果写进交付说明。积木自带 CSS，工程只需保证自己新建的类名有规则。
- **道具自由**：本期专属的物用 `prop.states` 描述，也可以手写；手写节点同样过类名覆盖与计算样式。积木只是工具，不要为了用积木把物换成纸框、牌子或光。
- **位图规则**：常驻位图只允许台口（幕布、台唇）与背景轨布景；生图道具用带 alpha 的镂空图，带背景的方图进 `inset.broll` 纸框、`prop.states` 的 `alpha:false` 纸片或墙面贴纸；写实件不得压在阅读区上方。
- **声音**：只给 rig 落定、归位、盖章配音效；入场不配音；无 BGM，与 `GUIDE.md` §8 一致。
