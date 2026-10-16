# HyperFrames 使用规则

从根目录 Work CLI 操作 Work/Variant；阶段、人工门与生命周期见 [workflow.md](workflow.md)，创作指南见 [spec/visual-design.md](spec/visual-design.md)，运行接口见 [spec/runtime-interfaces.md](spec/runtime-interfaces.md)。HyperFrames 负责唯一时间轴、预览与渲染；设计身份、账号、声线与执行模型分别选择，互不绑定。

本文件是产品包内唯一完整的使用与授权规则；根 `AGENTS.md` 与 `CLAUDE.md` 只保留简短入口并链接本文件，不重复维护第二份授权描述。

## 设计与流程

- 设计身份来自内置卡与用户卡 Catalog，素材卡不进入选择列表。随包安装的卡位于 `.studio/designs/`，是受管理文件、只读，公共包内置 `stage-full`、`stage-light` 两张；用户卡由根配置 `design_root` 定位，默认 `asset-library/designs`。同 ID 冲突拒绝，旧身份只读并提示重选。
- 单一制作流程：Script → Research →（可选）优化 → 文案门 → Plan → Plan 门 → Draft+封面 → Draft 门 → MP4+封面。三道人工门由独立工作流开关（`workflow_settings`）分别控制；Draft 审查为建议式，不阻断登记或继续，没有单独的 Final 阶段。
- 导出成功后 Variant 保持 active 与可继续修改；归档与重开显式执行（`work reopen <Work-ID> --variant-id <Variant-ID>`），不改兄弟版本或等待事项的生命周期。
- 正式导出把 MP4 与封面复制到按系列 / Work / Variant 分类的聚合导出架：只追加，文件名与索引带 hash，重复发布幂等，复制失败可重试且不重渲染；归档、更新、回滚与清理不触及导出架。

## 边界与授权

- 安装工具、runtime、受管理规则、旧冻结 vendor 与 Accepted Snapshot 保持不变；`design_root` 中的用户卡及卡内资产可直接编辑，随包安装的卡只读；提交 Draft 时保存 Work 自有快照。获授权生产 Work 或独立验收 Work 的文稿、Plan 与工程源可编辑；Current、采用记录、接受状态与 Final 快照由 CLI 管理，不手改。
- 保留文稿、Scene/Anchor、正式声音与对齐来源、其他 Variant 与已有导出；同身份不同内容拒绝覆盖。
- 用户授权的目标覆盖目标内制作；公开发布、上传、发送、私有内容转交新外部提供方、付费服务与不可恢复删除需要覆盖准确目标的单独授权，不公开发布、不购买额度、不得读取 Cookie。
- Plan 的 Asset Brief 列明生成素材用途、数量与风格后，方向批准一并授权这些已列用途；未列用途或明显超量再确认，不新增计划外的审批门。外部或付费服务必须单独取得用户授权。
- Draft 与 test-work 不导出视频；正常制作链可在获准生产目标或通过物理隔离预检的独立 local 验收根完成正式导出与交付。Review 只在隔离副本读写，不改生产 Current、源、接受记录或默认配置。截图、机械检查与测试证据不代替用户的文案、Plan、Draft 决定与动态观看或试听。

## 会话、阶段与报告

- `--context <name>`（或环境变量 `HYPERFRAMES_CONTEXT`）为每个会话绑定一对 Work/Variant；不同对象可并行，同一准确对象同时只允许一个执行者，更新类命令等待该对象全部在跑命令结束后执行。只有移动、删除或重新标识 Work 的仓库级命令（`migrate`、`successor`、`browser rebuild`、`root set`、`storage cleanup`、`series move/delete`）要求其它命令全部结束；卡片、资产和请求包等仓库目录写入只彼此互斥，不阻塞其它 Work。
- 设计卡在首次 Draft 前实时读取，Draft 后使用快照；status/预览提示变化，显式更新只作用于选定 Variant，保留工程副本并报告待重新安装资产，不读最新 `lines.yaml` 覆盖旧快照；阶段只加载当前阶段必要文件；账号身份、声线与执行模型分别配置，账号不能修改文案、流程门或设计身份。
- 只报告实际产物、检查结果与真实未验证项。

部署、安装切换、应用交付与 commit/tag/push 需要覆盖准确目标的用户授权；测试接受不转为生产接受。

生产会话以本根为 cwd，读取 `.agents/skills/hyperframes-production-workflow/SKILL.md`。Windows 原生使用 `work.cmd`，WSL 生产会话使用 `./work-wsl.sh`；开发会话只使用隔离夹具。执行者可能无法看图：返回诊断 JSON、seek 检查结果及截图路径，需要人工动态观看或试听的项目标为未验证。
