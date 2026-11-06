# Apple Silicon 本地部署

macOS 使用 `release deploy` 生成 `darwin-arm64` 本地包并安装到指定的物理目录。
源码仓与部署根必须独立。`dev-macos` 继续用于仓库开发与隔离预览。

运行时锁为 `darwin-runtime.lock.json`，npm 锁为 `darwin-npm.lock.json`。
原生 Python、Pillow/NumPy/SciPy、Node、Chromium headless shell、FFmpeg/FFprobe
以及 npm 原生模块都随包部署。不会调用 Windows DLL preload 或系统 Python。

准备运行时使用 `.studio/prepare_darwin_runtime.py --help`。输入必须是明确的原生
工具路径、Python 3.12.16 独立发行版、仅包含锁定图像依赖的隔离 site-packages、
按 npm 锁 `npm ci --ignore-scripts` 安装的目录，以及锁定的官方 mac-arm64 浏览器 ZIP。
准备器只生成缓存 ZIP 和哈希锁；检查锁与版本后再部署。依赖版本不随部署自动升级。

```sh
python3 release check-personal --personal-source /absolute/path/magic-video-personal
python3 release deploy --root /absolute/path/magic-video \
  --personal-source /absolute/path/magic-video-personal \
  --config /absolute/path/initial-config.json
cd /absolute/path/magic-video
./work doctor
./work --help
```

首次配置提供绝对 `work_root`、`asset_root`、`design_root` 与 `asset_source_roots`；
`work_root/works` 必须已存在。日常配置保存在部署根 `.studio/.runtime/local.json`，
后续部署省略 `--config`。所有生产操作通过本根 `./work`；不使用仓库开发入口。

部署仅替换清单内受管理文件；拒绝本地改动、陌生文件冲突、符号链接与运行中的工具进程。
用户 Work、配置、资产和导出不属于工具包，不随部署删除。更新复用哈希匹配的完整运行时，
同包重复安装保持不变。失败由原有事务恢复机制处理，至少保留一份回滚。
回滚必须从部署根外的源码仓或已解包包运行：
`python3 .studio/root_deploy.py rollback --root <物理根>`；中断恢复使用 `recover`。

个人包保留同一私有卡提交与技能合同；macOS 根规则来自私有源内已哈希固定的
`personal/macos-AGENTS.md` 和 `personal/macos-CLAUDE.md`。
IndexTTS 使用独立虚拟环境，设置 `INDEX_TTS_DIR` 后选择原生 `.venv/bin/python`。
CPU 合成入口与完整推理质量、模型首次下载、ASR/forced alignment、字体和真实视频
Finalize 是分别验证的能力；`doctor` 与安装成功不能代替这些结果。

本地未提交改动打包如实记录 `channel: local` 与 `dirty: true`，不宣称稳定发行版。
