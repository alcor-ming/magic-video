# 类名覆盖检查

登记 Draft 前运行，检查 JS 运行时创建的节点是否有样式契约。JS 创建或赋值的类名缺少定义时报错；HTML 静态类名缺少定义只作提示。

## 用法

需要 Node ≥ 18。在本目录运行：

```sh
node check-classes.mjs <工程目录> [--rig <stage-rig.js 路径>]
```

## 检查规则

1. 只使用 `node:fs`、`node:path`、`node:process`，无第三方依赖。不读取时钟，不使用随机数、定时器或网络。
2. 递归收集工程内的 `*.html`、`*.js` 作为使用方，`*.css` 和 JS 字符串中的选择器作为定义方。跳过 `runtime/`、`vendor/`、`node_modules/`、`.runtime/`。另读 `--rig` 指定文件作为定义方；默认读取工程内 `runtime/stage-rig.js`，默认文件不存在则跳过。
3. 提取 HTML 的 `class="a b"`，JS 的 `className = "a b"`、`className: "a"`、`classList.add("a","b")`。第二参数为类串的调用只认 `el`、`make`、`node` 或以 `create` 开头的调用名，支持 `K.el(...)`、`kit.el(...)` 等前缀。单双引号均可。`"icon " + (cls || "")` 这类拼接只取开头字面量，不推导变量值。`setAttribute("d", "M" + ...)` 不算类名创建调用。
4. CSS 与 rig 文本按 `\.([a-zA-Z_][\w-]*)` 提取类名。工程 JS 字符串中以点开头、符合该模式的片段也算定义，包括查询、动画选择器里的类名；仅作 JS 钩子的结构类因此可被覆盖。这是静态文本检查，不执行工程代码，不计算选择器优先级或运行时样式。
5. JS 创建或赋值的类名缺少定义时，按文件、类名排序报错，退出 1。HTML 静态 `class="..."` 缺少定义只输出「提示」，不影响退出码；HTML 内联脚本中的 JS 创建或赋值仍按错误检查。没有 JS 缺失时，首行打印 `ok: N classes covered`，退出 0，随后输出提示。N 是使用方已被定义覆盖的去重类名数，不包含仅作提示的缺失静态类名。单类选择器的声明块含 `visibility:hidden` 时，仍提示「子节点需显式写回 visible」，不影响退出码。参数或读取失败退出 1。

## 自测

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
