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

## 轨道档自检（登记 Draft 前必做）

- **截帧**：每个 Scene 用工程调试参数或 `window.__timelines` seek 到段首 +0.5 s、中段、段尾 −0.5 s，各截一帧。任一帧「主物不在画里」或「只剩文字卡」直接回改，不登记。截帧只贴进交付说明，不入卡仓。
- **计算样式抽查**：镜头表里本镜应在画里的物，其第 2 层节点的 `visibility` 为 `visible`、`position` 为 `absolute`（被 B 接管而隐藏或虚化的 A 组不在此列）；`.hf-rig` 节点必须存在，确认折叠装置已 mount。用 `getComputedStyle` 核对实际值，不以代码存在代替。
- **可见性归属**：`.scene` 这类容器若写 `visibility:hidden`，子节点必须由同一函数统一写回 `visible`；只改 `opacity` 的节点会被继承隐藏。
- **类名覆盖**：JS 里创建的每个类名必须有样式契约：在工程 `style.css` 或 rig 注入的 CSS 中有规则，或在 JS 里被当作选择器引用；只在创建时写、谁也不引用的类名就是缺陷（位置会塌成 static）。跑 `node tools/check-classes.mjs <工程目录>`，退出码非 0 不得登记。
- **位图规则**：常驻位图只允许台口（幕布、台唇）；生图只接受带 alpha 的镂空道具。带背景的方图只能进 `inset.broll` 纸框或作墙面贴纸；写实件不得压在阅读区上方。
- **声音**：只给 rig 落定、归位、盖章配音效；入场不配音；无 BGM，与 `GUIDE.md` §8 一致。
