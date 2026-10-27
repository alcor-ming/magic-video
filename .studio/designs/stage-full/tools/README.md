# 卡内工具

- `check-classes.mjs`：类名覆盖检查（下文）。
- `sample-frames.mjs`：独立小样取帧（文末）。

## 类名覆盖检查

登记 Draft 前运行，检查 JS 运行时创建的节点是否有样式契约。JS 创建或赋值的类名缺少定义时报错；HTML 静态类名缺少定义只作提示。

### 用法

需要 Node ≥ 18。在本目录运行：

```sh
node check-classes.mjs <工程目录> [--rig <stage-rig.js 路径>]
```

### 检查规则

1. 只使用 `node:fs`、`node:path`、`node:process`，无第三方依赖。不读取时钟，不使用随机数、定时器或网络。
2. 递归收集工程内的 `*.html`、`*.js` 作为使用方，`*.css` 和 JS 字符串中的选择器作为定义方。跳过 `runtime/`、`vendor/`、`node_modules/`、`.runtime/`。另读 `--rig` 指定文件作为定义方；默认读取工程内 `runtime/stage-rig.js`，默认文件不存在则跳过。
3. 提取 HTML 的 `class="a b"`，JS 的 `className = "a b"`、`className: "a"`、`classList.add("a","b")`。第二参数为类串的调用只认 `el`、`make`、`node` 或以 `create` 开头的调用名，支持 `K.el(...)`、`kit.el(...)` 等前缀。单双引号均可。`"icon " + (cls || "")` 这类拼接只取开头字面量，不推导变量值。`setAttribute("d", "M" + ...)` 不算类名创建调用。
4. CSS 与 rig 文本按 `\.([a-zA-Z_][\w-]*)` 提取类名。工程 JS 字符串中以点开头、符合该模式的片段也算定义，包括查询、动画选择器里的类名；仅作 JS 钩子的结构类因此可被覆盖。这是静态文本检查，不执行工程代码，不计算选择器优先级或运行时样式。
5. JS 创建或赋值的类名缺少定义时，按文件、类名排序报错，退出 1。HTML 静态 `class="..."` 缺少定义只输出「提示」，不影响退出码；HTML 内联脚本中的 JS 创建或赋值仍按错误检查。没有 JS 缺失时，首行打印 `ok: N classes covered`，退出 0，随后输出提示。N 是使用方已被定义覆盖的去重类名数，不包含仅作提示的缺失静态类名。单类选择器的声明块含 `visibility:hidden` 时，仍提示「子节点需显式写回 visible」，不影响退出码。参数或读取失败退出 1。

### 自测

以下命令在仓库根目录运行。第一条预期退出 0，首行为 `ok: N classes covered`；允许随后列出静态类名提示。

```sh
node .studio/designs/stage-full/tools/check-classes.mjs .studio/designs/stage-full/example --rig .studio/designs/stage-full/assets/stage-rig/stage-rig.js; echo exit=$?
```

第二条使用已建立并授权可写的夹具目录。先把 `FIXTURE_B` 设置为该目录，再执行。预期 `a.js` 的 `gate-panel` 出现在错误行，`index.html` 的 `scene` 出现在提示行，退出 1。

```sh
printf '<div class="scene"></div>' > "${FIXTURE_B:?}/index.html" &&
printf 'el("div","gate-panel",root);' > "${FIXTURE_B:?}/a.js" &&
: > "${FIXTURE_B:?}/style.css" &&
node .studio/designs/stage-full/tools/check-classes.mjs "${FIXTURE_B:?}"
echo exit=$?
```

## 独立小样取帧

给 Work 的 `materials/tests/<名>/` 这类单文件合成用，不经 Studio、不登记 Draft。按给定时刻 seek 主时间线并派发 `hf-seek` 后截 PNG，每个时刻再经「0 → 片尾 → 该时刻」重 seek 一次比对像素，并报告页面错误、出画的文字与单帧 seek 耗时。正式工程用 `preview diagnose --range … --frames`，不用本工具。

```sh
node sample-frames.mjs <小样目录> <输出目录> --times 0,2.5,7 [--timeline main] [--browser <chrome>] [--puppeteer <puppeteer-core 目录>]
```

- 小样目录要有 `index.html`，一条 paused GSAP 主时间线注册到 `window.__timelines`；`--timeline` 缺省取根 `data-composition-id`，再取第一条。
- 浏览器缺省取 `HYPERFRAMES_BROWSER_PATH`；puppeteer-core 缺省从小样目录和本工具目录向上找 `runtime/npm/node_modules/puppeteer-core`（部署包布局）。入口先找 `lib/puppeteer/puppeteer-core.js`，再找 `lib/esm/puppeteer/puppeteer-core.js`（pnpm / 新版布局），都没有则退出 1。
- 浏览器配置放系统临时目录，结束即删；网络盘或 9p 上的 profile 会让 Chromium 启动即退出。
- 每次 seek 与 HyperFrames 宿主同一路径：先 `seek(t, false)`，由 `onUpdate` 驱动的 WebGL 背景也按该时刻重画；再置 `window.__hfThreeTime` 并在 `window` 同步派发 `hf-seek`（`detail.time`、`detail.waitUntil`），等全部 `waitUntil` Promise 完成后再等两帧截图。`HarnessScene.bindScene` 只监听 `hf-seek`，不跟随 `timeline.seek`；旧版只 seek 时间线，这类页面会停在初始态。
- 防假通过：≥ 2 个不同时刻的帧逐像素全同，多半是 seek 没驱动重绘，`qa.json` 与摘要记 `identicalFrames: true`，退出 1。确实静止的小样至少取一个画面有变化的时刻。
- 输出目录写 `t<秒>.png`、重 seek 不一致时的 `-reseek.png` 与 `qa.json`；标准输出一行摘要。退出码：0 无错误；1 页面错误、重 seek 不一致、帧全同（`identicalFrames`）、参数或启动失败。出画文字只作提示（`textOutsideAt`）。
- 帧只给执行者自己看，不作交付或审片证据，不入卡仓。

### 自测

以下命令在仓库根目录运行。`$DEMO` 为一个装好 `runtime/`、用 `HarnessScene.bindScene` 驱动的小样，`$OUT`、`$STUCK` 为授权可写的临时目录。第一条取画面有变化的三个时刻，预期 `ok:true`、`identicalFrames:false`，三帧互不相同且与页面自己调 binding `seek` 的截图一致，退出 0。

```sh
node .studio/designs/stage-full/tools/sample-frames.mjs "${DEMO:?}" "${OUT:?}" --times 1.2,5.5,11 --browser <chrome> --puppeteer <puppeteer-core 目录>; echo exit=$?
```

第二条用不重绘的页面，预期 `identicalFrames:true`，退出 1。

```sh
printf '%s' '<div data-composition-id="main" data-width="640" data-height="360">static</div><script>window.__timelines={main:{seek(){},duration(){return 10}}}</script>' > "${STUCK:?}/index.html" &&
node .studio/designs/stage-full/tools/sample-frames.mjs "${STUCK:?}" "${STUCK:?}/frames" --times 1,4,7 --browser <chrome> --puppeteer <puppeteer-core 目录>
echo exit=$?
```
