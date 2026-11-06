# macOS 原生开发与预览

本阶段范围是 Apple Silicon 上的本地开发、CLI、Studio 预览与隔离检查。
开发预览入口不启用 Finalize 或生产迁移；后续独立本地部署入口见 [macOS 部署说明](../macos-deployment.md)。
Windows 产品 runtime 和发布命令保持原有目标；开发成功不等于发行资格。

## 本机准备

需要原生 Python 3.11+、Node.js 22+、npm、Git，以及可执行的 macOS
Chrome/Chromium、FFmpeg、FFprobe。Python 与 Node 必须先放到 PATH。
开发验证使用 Python 3.12、Node 24；CI 的 Linux Python 3.11/Node 22 仍保留。

在仓库根创建独立 Python 环境，安装与 CI 一致的图像依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install Pillow==12.3.0
```

Chrome 可使用已安装的应用，或在忽略目录中解压 Chrome for Testing 的
mac-arm64 版本。本机预览验证采用 `windows-runtime.lock.json` 中浏览器版本
对应的 mac-arm64 构建，不使用 Windows 二进制。下载是显式准备步骤，
运行预览命令时不会自动下载浏览器。

使用本机实际路径配置（下面的 FFmpeg 路径仅为示例，需替换）：

```sh
./dev-macos setup \
  --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --ffmpeg /absolute/path/to/ffmpeg \
  --ffprobe /absolute/path/to/ffprobe
./dev-macos doctor
```

`setup` 从现有 `windows-npm.lock.json` 派生预览依赖，移除 Windows DLL 接线的
Koffi 和不在本阶段范围内的 ONNX 推理引擎；保留其余版本与完整 integrity 信息到
`.studio/.runtime/macos-preview/npm`，由 npm 按宿主选择 macOS 原生依赖；
本机派生锁通过 npm 离线裁剪，并逐项核对版本、来源和 integrity 未漂移。
预览 setup 不改受控锁定文件；部署使用另行准备的 darwin runtime lock。安装脚本禁用，
`doctor` 实际加载 Puppeteer、Sharp 和原生 esbuild 检查可用性。
解析器与音效工具继续使用各自的现有 package-lock。配置保存本机绝对路径，
移动 workspace 后需要重新 setup，不将配置提交或配送。

## 开发入口

```sh
./dev-macos work root show
./dev-macos work --help
./dev-macos check
./dev-macos run -- node tests/studio-readonly.mjs
./dev-macos run -- node tests/visual-studio.mjs --preview-only
```

`work` 固定绑定 `.studio/.runtime/macos-preview/sandbox/review/macos`。
`run` 为测试提供相同的原生工具；测试仍可创建自己的临时夹具。
入口清除继承的 `HYPERFRAMES_*` 与 `NODE_OPTIONS`，不沿用生产根、Windows
DLL 预加载器、凭据配置文件路径或既有 Current。它不启动常驻服务；Studio
由既有 start/context/stop 协议管理，Review 禁止生产接受与正式交付。

## macOS 差异与验证边界

- 临时目录使用真实路径，避免 `/var`、`/tmp` 的系统符号链接被 Review
  防逃逸检查拒绝。用户内容中的符号链接与越界依赖仍拒绝。
- 快照遍历在入口正規化根路径，避免真实文件路径与别名根比较失败。
- Studio 允许发现系统或用户 Applications 中的 Chrome/Chromium；显式指定
  的浏览器路径无效时仍失败，不静默改用其他浏览器。
- Windows 锁测试夹具明确声明 Windows 包身份，不因 macOS 宿主而寻找不存在
  的 darwin 锁。WSL 部署预检用显式 mock，不把 macOS 宣称为 WSL。
- 文件名审计测试兼容默认大小写不敏感的 APFS；此文件系统无法实际保存同目录
  下仅大小写不同的两个文件，Linux CI 继续检查真实冲突。
- NumPy/SciPy、真实 Earshot、Windows 原生安装与额外模型不是基础预览依赖；
  相关测试缺少条件时应明确记录跳过，不伪装为通过。

浏览器检查只在隔离夹具运行，验证 Studio HTTP、快照只读性、页面与 seek。
不运行生产 Work，不导出视频。具体执行结果以本次验证报告为准。

`check` 清除本机运行时覆盖，让单元测试使用自己的隔离夹具；`run` 提供原生工具环境，`work` 另将工作目录限制到本机 Review 目录。
