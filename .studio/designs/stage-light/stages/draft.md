# stage-light · Draft 阶段指南

## 机制与实现

- 文件：`example/index.html` + `example/style.css` + `example/scene.js` + 所引用的 `stage-full/stage-rig` 资产；全部为原创内联 SVG/CSS 剪贴，带白边与偏移投影。
- 折叠与对象接续：`HarnessStageRig.createPaperStage({panels:2})` 只建内板一对；无台口/吊灯/`spot`，强调只用第 3 层 `#readbar` 读行；关键薄荷纸卡靠空间位移从 ② 分组延续到 ③ 解释。
- 单一 paused 主时间线注册到 `window.__timelines['stage-light-example']`，同一条交给 `HarnessScene.bindScene`；无 RAF / play / autoplay / Date / Math.random。
- 动作：物体的出现、退场、强调、移动、落定、换场与归位只用 [MOTION.md](../MOTION.md) 里的动作（`HarnessMotion.create({ card: 'stage-full' })`）；换地点用背景动作 `refold`，前景在换景开始前退场、换景完成后再出现。
- 外部 seek：`window.__example.seek(t)` 直接重建完整状态，`dispose()` 解绑并 kill 时间线；不依赖 seek 事件或回调。

## 资源闭包、字体与释放

- 资源闭包：示例只依赖宿主放好的 `runtime/gsap.min.js`、`runtime/scene-binding.js`、`runtime/stage-rig.js` 与 `media/SourceHanSansCN-Regular.otf`；无图片、音频、字体下载与新依赖。Work 工程另有 `runtime/motion.js` 与 `vendor/components/stage-full/` 下装好的 `stage-rig`、`stage-motion`（见 MOTION.md「接入 Work」）。
- 字体：`document.fonts.ready` 就绪后才首次渲染；`@font-face` 只指向 `media/SourceHanSansCN-Regular.otf`，`font-display:block`。
- 布局：固定 1920×1080；读行不遮挡仍需阅读的信息；文字归属与阅读保护按 visual-design.md。

## 具体技术检查

- 按分镜索引核对 Rolls 区间。看 B-roll 是否对应持续的口播，返回 A 时是否恢复已读状态。按 Plan 核对世界里、页面里和屏幕上的文字。启用字幕时，核对第 5 层字幕在转场处的连续性。
- 确定性 seek：正放、倒放、随机 seek、重复 seek 一致；对 `[t3, 0, t1, t3]` 抓帧比较同一时刻。
- 释放：`dispose()` 解绑并 kill 时间线后不再响应 seek。
- 声音：示例静音；若某 Variant 需要音效，只为结构重击与关键 hit（如 S4 折叠落定）配音效，不给普通入场自动配音效；BGM 只在开启 `bgm.enabled` 时用一条备好的音轨；所有 cue 对应同帧可见事件并按 `data-start` 调度以保证 seek 安全。
- 不新增几何/函数预置、通用角色库、AI 概念图库或 音频生成。
