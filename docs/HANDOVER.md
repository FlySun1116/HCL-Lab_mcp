# HANDOVER — HCL-Lab MCP Server

## 2026-07-18：v0.2 控制平面暂停点（当前接手入口）

### 当前版本/分支

- Python 包版本仍为 `0.1.0-beta.2`，尚未发布。
- 当前开发分支：`codex/v0.2-control-plane`。
- 分支基线：`45c641b fix: reject ambiguous HCL project identities`，来自
  `codex/beta2-release-candidate`。
- 状态：**持续开发中，但本阶段主动暂停**。当前提交用于固化安全契约、设计和交接状态，
  不是 v0.2 可用版本，也不应合并或发布为稳定版。
- v0.1 的 15 个只读 MCP Tool 未改变；没有注册任何 HCL 生命周期或拓扑写入 Tool。

### 本阶段目标与实际完成度

目标是让 Agent 最终能够在 HCL 5.10.3 中创建隔离实验、添加设备和链路、顺序启动设备，
再通过 loopback console 执行受控 Comware 验收。当前只完成了不产生副作用的控制内核第一层：

- 新增不可变 `DesiredTopology`、结构化 `TopologyOperation`、资源预算/估算、R0–R3 风险等级；
- 拓扑、Windows/Unicode 身份、设备名、端口和无向链路均执行确定性规范化和冲突拒绝；
- `TopologyPlan` 强制绑定期望拓扑、规范操作序列、资源估算、Provider 能力/会话指纹和
  `must_not_exist=True`，并验证 SHA-256 内容哈希；
- `OperationContext` 绑定 plan、Execution Grant、目标项目、预期基线、操作序号/摘要、
  idempotency key、截止时间和 fencing token；
- `OperationReceipt` 回绑完整上下文，只允许哈希 checkpoint 和符号化 warning code，
  不提供自由文本或本机路径通道；
- 新增无 I/O 的 `TopologyPlanner`，按 create project → add device → connect link → start device
  生成确定性计划，并在能力不足、型号未知或预算超限时于副作用前拒绝；
- 新增尚未有实现类的 `HclControlProvider` Port；
- 新增 Proposed ADR-0007，限定未来 Provider 只能使用精确版本/会话探测后的 Windows UI
  Automation 语义控件，不得使用 HCL 私有端口、VirtualBox 控制、直接修改工程文件、坐标点击
  或图像匹配；
- 更新设计和 CHANGELOG，明确 v0.2 提案尚未注册公共 Tool。

### 修改文件

- `src/h3c_hcl_mcp/domain/topology_control.py`
- `src/h3c_hcl_mcp/application/topology_planner.py`
- `src/h3c_hcl_mcp/ports/hcl_control_provider.py`
- `tests/contract/test_domain_models.py`
- `tests/contract/test_ports.py`
- `tests/unit/application/test_topology_planner.py`
- `docs/adr/0007-version-gated-hcl-ui-automation.md`
- `docs/design.md`
- `CHANGELOG.md`
- `README.md`
- `docs/HANDOVER.md`

### 关键决策与边界

- ADR-0007 仍为 **Proposed**，不能据此宣称 UI Automation 路线已经获得稳定公共契约批准。
- Provider 优先级仍是厂商公开 SDK/API → 明确授权接口 → 精确版本锁定的 UI Automation。
- 当前控制模型只描述“创建一个必须尚不存在的隔离工程”，不接管、覆盖或丢弃用户现有工程。
- UIA Provider 必须 fail closed：版本、locale、会话、Automation ID、模态窗口或基线任一变化即停止。
- 设备启动默认串行且必须先通过内存预算；初始实机里程碑最多两台低资源设备和一条链路。
- 拓扑创建权限不包含 `system-view`、配置保存、重启、删除或修改其他工程的权限。
- 公共 Tool Schema、Execution Grant、默认写策略和 ADR 状态均需维护者重要决策后才能改变。

### 已执行验证

- 安全模型、Provider Port 和 Planner 聚焦测试：**133 passed in 0.53s**。
- 聚焦测试覆盖了计划防伪、内容哈希、Windows 身份碰撞、能力/型号检查、资源拒绝、
  grant/baseline/fence/receipt 绑定、过期时间和自由文本拒绝。
- `ruff check .`：通过；`ruff format --check .`：**114 files already formatted**。
- `mypy src scripts/check_distribution.py scripts/check_docs.py scripts/check_repository.py`：
  **Success: no issues found in 76 source files**。
- 全量测试：**846 passed、3 skipped in 59.87s**。
- 本阶段没有重新构建 wheel/sdist，也没有运行真实 HCL、Claude Desktop 或 Cursor 新能力测试；
  下方 beta.2 的历史制品结果不能代替 v0.2 当前分支的制品验证。

### 未完成内容

1. `PlanStore`、事务 Journal、Lease/Fencing、Job、Execution Grant 校验和进程重启恢复编排；
2. fake Provider 的成功、重试、取消、基线漂移、部分失败、补偿和恢复 saga；
3. HCL 5.10.3 中文界面的只读版本/locale/会话/Automation ID capability probe；
4. Windows UI Automation Provider 实现；
5. 新建隔离工程、添加两台设备、连接一条链路和顺序启动的真实 HCL 闭环；
6. console prompt、`display version`、`display ip interface brief` 和互 ping 验收；
7. 公共 lifecycle Tool、错误语义、Execution Grant 和默认策略评审；
8. wheel/sdist 安装 smoke、Claude/Cursor 对新增能力的端到端验证；
9. ADR-0007 接受、PR 合并、tag、Release 和 PyPI 发布。

### 本机 HCL 观察与安全说明

- 已只读观察到 HCL 5.10.3 Qt 客户端暴露稳定语义 Automation ID，例如 New/Open/Save、
  Router/Switch/Host/Link、StartAll/StopAll；这些只是本机探测证据，不是兼容性保证。
- 当时 HCL 打开的是带未保存修改的临时工程。没有保存、丢弃、覆盖或创建工程，也没有启动设备。
- 后续实机测试前必须由维护者处理或明确授权隔离当前临时工程；自动化不得替用户点击“不保存”。
- 机器内存约 16 GiB，后续 Provider 必须先做资源预检并串行启动，不能直接复刻复杂示例拓扑。
- 不得提交真实工程、设备镜像、凭据、绝对本机路径、HCL 二进制或未脱敏日志。

### 建议接手顺序

1. 从本分支运行完整门禁，确认控制契约提交自身可复现；
2. 独立安全复审 `topology_control.py`、Planner 和 Port，先修复 P0/P1；
3. 实现纯内存 PlanStore/Journal/Lease/Job 和 fake Provider saga，不接触 HCL；
4. 实现只读 UIA capability probe，并把 HCL 版本、build、locale、session/probe fingerprint
   固化进能力对象；
5. 在一个全新且必须不存在的隔离工程中完成单设备 smoke，再扩展到两设备一链路；
6. 最后才评审并注册公共 MCP Tool，随后补双制品和真实 Client 验证。

### 接管命令

```powershell
git fetch --all --prune
git switch codex/v0.2-control-plane
git pull --ff-only
uv sync --locked --extra dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src scripts/check_distribution.py scripts/check_docs.py scripts/check_repository.py
uv run --locked pytest -q
```

接手者应先阅读本节、`CLAUDE.md`、`docs/design.md` 和 ADR-0007，再从“未完成内容”选择任务。
不要把下方 beta.2 历史验证结果当成 v0.2 新增代码已经通过的证据。

---

## beta.2 候选历史交接（保留作为只读基线证据）

## 当前版本/分支

- 候选版本：`0.1.0-beta.2`（未发布）
- 分支：`codex/beta2-release-candidate`
- 当前分支基线：`7e05464` + 本文所在提交
- 当前证据基线：本轮本地源码、双制品、安全/文档/依赖门禁，以及 Draft PR #4 的 2026-07-18 新 CI/CodeQL runs
- beta.2 集成状态：项目文件、审计、日志、SDK 与供应链边界已加固；真实 HCL 只验证到项目/拓扑发现和“设备未运行”负向路径，未宣称两条 display 正向成功
- 日期：2026-07-18
- 发布状态：未创建 tag、GitHub Release 或 PyPI 包

## 目标 Issue/PR

当前目标是完成 beta.1 测试报告中 parser、runtime、配置、validation、audit、安全和并发问题的修复，形成 `v0.1.0-beta.2` 可验证候选。候选集成到 [Draft PR #4](https://github.com/FlySun1116/HCL-Lab_mcp/pull/4)；最新 CI、docs、artifact security、license、secret scan 和 CodeQL 均通过，唯一红项 Dependency Review 明确因仓库未启用 Dependency Graph。merge、tag、Release、PyPI 和仓库设置变更仍需维护者授权。

## 完成内容

### HCL 项目解析

- 支持 HCL 5.10.x `projectInfo` / `deviceInfoList.resource*` 实际 JSON 结构。
- 支持嵌套 ConfigObj 风格 `.net`，由 `.net` 提供权威 `device_id` 和链路。
- 按设备名称大小写不敏感合并两种来源，链路去重并输出确定性 warning。
- 拒绝绝对路径、目录分隔符、`..`、realpath/symlink 项目根目录逃逸。
- 配置项目根按规范化物理路径去重；跨不同物理目录的 project ID 大小写冲突以 `PROJECT_DAMAGED` fail closed，列表不再重复或静默选择首项。
- 一个项目只接受一个直接子级 `.net`；多候选不再按不稳定目录枚举顺序选择陈旧设备 ID/链路。
- MCP 项目列表和错误不泄漏本机绝对路径。

### Runtime 与 console

- 从 HCL 5.10.x 轮转日志按时间顺序归并项目绑定、console 创建/关闭和 alias 重绑定。
- 任何 HCL 进程存在不再等价于全部设备运行。
- 端口公式不生成 candidate；只探测明确绑定到目标项目/设备的日志 candidate。
- candidate 仅允许 loopback，必须通过 TCP/Telnet 和 Comware prompt 探测；不回答登录/密码，不执行探测命令。
- 超限日志仅读取连续尾部并插入状态信任边界；旧 alias/project/endpoint/closed/legacy 状态全部失效，tail 中没有新明确绑定就不产生 endpoint。
- 配置与 transport 边界双重拒绝非 loopback 地址和非 `console_telnet` endpoint；v0.1 默认不再包含未实现的 SSH。
- Telnet IAC 解析跨 TCP chunk 保留状态，分片协商不会泄漏到 CLI 输出。
- 项目级和设备级查询使用同一短期 runtime cache。
- `ProjectAwareRuntimeDiscovery` 在每次查询前注册拓扑，消除 Tool 调用顺序依赖。

### MCP、配置与审计

- 无配置以只读 stdio 默认值启动；显式缺失/损坏配置在协议启动前失败。
- CLI、嵌套环境变量、JSON、YAML 配置均有官方 stdio 子进程测试。
- `PyYAML` 已是运行依赖；列表型环境变量支持 JSON。
- v0.1 只接受 `stdio`、每设备并发固定为 1、transport 首选项必须有效且不重复。
- `allow_display_prefixes` 只能收紧内置 display allowlist；`deny_patterns` 只增加不区分大小写的字面子串拒绝，均不能覆盖内置注入/危险规则。
- 官方 `tools/call` Schema 错误规范化为结构化 `INVALID_ARGUMENT`，不泄漏 Pydantic 输入或文档 URL。
- 未知 Tool 同样返回带 `request_id` 的稳定 `INVALID_ARGUMENT` 并写入审计；所有合法 Tool 受 `server.max_tool_seconds` 全局超时保护。
- Schema、领域和占位错误在响应与审计中复用同一 `request_id` 和真实错误码。
- `AuditEvent.outcome` 与 `policy_result` 分离；旧 SQLite 表采用加列迁移，并把旧错误事件与非 UTC 时间戳规范化。
- `audit.enabled=false` 使用空审计实现，不创建数据库。
- `audit.retention_days` 已实际清理过期 SQLite 事件，取值限制为 1～365 天。
- 审计开启时，写入失败会 fail closed，返回稳定 `INTERNAL_ERROR`/`AUDIT_UNAVAILABLE`，不产生未审计成功。
- 所有公共字符串字段都有长度上限；客户端控制的日志参数在输出前截断。
- 审计库/Secret 文件初始化不再记录绝对位置；统一日志过滤器脱敏 Windows、UNC 和任意 POSIX 绝对路径、凭据与异常文本，同时保留 HTTPS URL。
- Tool 注册/调用/Schema 查询使用 FastMCP 公开扩展点；唯一 `_mcp_server` 版本桥集中在 `sdk_compat.py`，运行时仅接受 MCP 1.28.x，依赖锁定到 `mcp>=1.28.1,<1.29`。

### 安全、会话与 Tool

- v0.1 保持 15 个 namespaced Tool；短 alias 尚未注册。
- `h3c_diff_config` 明确返回 `NOT_IMPLEMENTED`；v0.2 写 Tool 未注册。
- PC/终端节点不进入 H3C/Comware 设备列表。
- 所有设备 raw output 在 MCP 边界强制脱敏；`h3c_get_config(redact=false)` 返回 `POLICY_DENIED`。
- 拓扑响应不暴露 `config_path`；提示符错误不携带设备 buffer；PEM/OpenSSH/EC/ENCRYPTED 及截断私钥块均会整段脱敏。
- endpoint 携带项目/设备上下文；task-local 会话状态和设备连接锁防止并发串设备。
- 全局会话上限、空闲超时、单会话命令次数回收已接入生产 SessionManager；Server lifespan 退出时关闭全部连接。
- Telnet 连接使用配置的 connection timeout，不再误用 endpoint confidence。
- connect/prompt/EOF/command-timeout/cancelled 失败都会关闭并失效连接，迟到输出不会污染下一次调用。
- 命令完成 prompt 必须是独立终行并与连接时捕获值完全一致；正文中的 `<fake>`/`[fake]` 不会截断响应或串入下一命令。
- HCL 文件扫描和拓扑解析在线程中执行，不阻塞 stdio 事件循环；拓扑刷新会删除已从项目移除的旧 runtime 设备。
- deep health 实际枚举项目，并对首个项目执行 runtime discovery。
- `h3c_ping`/`h3c_trace_route` 使用严格的目标、次数和最大跳数 Schema，并输出结构化诊断摘要。
- 最终 MCP `CallToolResult` 按 UTF-8 实际字节数执行硬上限；成功、错误、Schema、未知 Tool 和超时路径均受限，超限返回稳定 `OUTPUT_TOO_LARGE`。
- 设备结果标记 `content_trust=untrusted_device_output`；结构化 parser 结果不再保留重复 raw 副本。
- SNMP community、NTP authentication、RADIUS/HWTACACS shared key、`super password` 的 role/hash/cipher/simple 变体均在完整和快速路径强制脱敏。
- `key-string`、WEP key、WLAN/IPsec `preshared-key`/`pre-shared-key` 变体均在完整和快速路径强制脱敏。
- project list cursor 已接入 repository 分页；恶意超长 Tool/project 标识在进入审计前受限。
- HCL 项目、拓扑和 runtime 元数据与设备输出统一标记为不可信外部内容。
- 进程检查、日志加载移出事件循环；日志观察限制为最多 16 个文件、每文件最多 4 MiB，并显式关闭 SQLite、scandir 和测试 Telnet writer。
- 统一日志边界覆盖紧凑 `label:/path`，并把 CR/LF、ANSI/终端控制符与 Unicode 行分隔符转为可见转义，阻止伪造日志记录。

### GitHub 与 Agent 接管

- `.github/ISSUE_TEMPLATE/` 提供 Bug、Feature 和 Agent Task 表单；Agent Task 强制记录 owned/forbidden files、依赖、验收证据和交接对象。
- PR 模板固定架构影响、完整门禁、Secret/专有资产、安全策略、真实设备只读与外部发布动作检查项。
- CI 的 checkout、setup-uv、upload-artifact、gitleaks 已升级到当前 Node 24 版本，并固定到完整 commit SHA；避免 Node 20 下线和可变 major tag 风险。
- CI 对 `ResourceWarning`/`PytestUnraisableExceptionWarning` 零容忍；wheel/sdist 在干净 Python 3.12 环境仅依据各自包元数据解析依赖后运行同一 stdio 黑盒测试。
- `scripts/check_distribution.py` 拒绝本地 Agent 状态、凭据/专有资产、链接、路径穿越、超大成员和缺失的许可证/审计 schema；sdist 不再包含 `.claude/settings.local.json`。
- `.claude/settings.example.json`、七个角色定义和 `docs/agent-team-playbook.md` 固化 Agent Team 所有权、并行边界、Git 禁区与 human-required 动作。
- `security.yml` 执行依赖/许可证/仓库资产/双制品/CodeQL 门禁；`docs.yml` 校验链接、结构化示例和 Action SHA；`release.yml` 只接受 main 上 GitHub 验证的签名 tag，并在 PyPI environment 显式开关、OIDC Trusted Publishing、SBOM/provenance 成功后创建 Release。
- GitHub Private Vulnerability Reporting 当前仍为 disabled；启用它、配置 `pypi` environment 和 `PYPI_RELEASE_ENABLED` 属维护者仓库设置动作。

## 修改文件

beta.2 候选修改覆盖以下边界；以最终集成 diff 为准：

- `src/h3c_hcl_mcp/adapters/hcl/`
- `src/h3c_hcl_mcp/adapters/comware/`
- `src/h3c_hcl_mcp/application/runtime_service.py`
- `src/h3c_hcl_mcp/domain/audit.py`
- `src/h3c_hcl_mcp/infrastructure/settings.py`
- `src/h3c_hcl_mcp/infrastructure/audit/`
- `src/h3c_hcl_mcp/mcp/`
- `tests/contract/`、`tests/unit/`、`tests/integration/`、脱敏 fixtures
- `README.md`、`CHANGELOG.md`、`docs/`、`config/`、`examples/`
- `.github/ISSUE_TEMPLATE/`、`.github/pull_request_template.md`、`.github/workflows/`
- `.claude/`、`.gitignore`、`scripts/check_distribution.py`、`scripts/check_docs.py`、`scripts/check_repository.py`
- `pyproject.toml`、`uv.lock`、版本模块

## 关键决策/ADR

- ADR-0001～0006 继续有效：Python 3.12、stdio、本机项目文件 + loopback console、六边形架构、默认只读、不实现 HCL 私有协议。
- beta.2 runtime 采取“日志明确绑定 + prompt 验证”；`fallback_telnet_base` 仅保留配置兼容，不产生 endpoint。
- 15 个 namespaced Tool 是当前公共契约；短 alias 由维护者按 `docs/TOOL_ALIAS_PROPOSAL.md` 决策。
- v0.1 不开放配置写入、SSH、NETCONF、HTTP 或 HCL lifecycle。

## Git commits

- `7e05464 test: avoid CodeQL sensitive-data false positive`（保持日志边界测试语义，避免测试变量名触发高危误报；复跑 CodeQL 通过）
- `0efdc8a fix: complete v0.1 release readiness gates`（项目/审计/SDK 边界、兼容矩阵、Agent Team 和供应链门禁）
- `da7747b docs: record green beta2 CI evidence`（上一轮六项 CI 证据）
- `192fc41 ci: fix Linux typecheck and gitleaks token`（Linux mypy 跨平台兼容与 gitleaks v3 实际执行）
- `61ba9d9 docs: finalize beta2 security verification`（beta.2 安全验证文档）
- `183f3f6 fix: harden beta2 security and release boundaries`（审计 fail-closed、脱敏、Telnet/session、输入边界与制品策略）
- `938b96e docs: record Cursor client environment blocker`（Cursor 外部环境阻塞证据）
- `fbac9ec docs: record Claude Code client smoke`（Claude Code 隔离连接证据）
- `b19ba0e docs: record CI supply-chain update`（CI 供应链验证文档）
- `f39ce15 ci: pin current Node 24 actions`（官方当前版本与完整 SHA 供应链固定）
- `31516d8 docs: align final artifact inventory`（制品清单对齐）
- `74cb880 docs: finalize beta2 verification report`（冻结候选验证报告）
- `39ed695 chore: add agent-ready GitHub templates`（Issue forms 与 PR 接管/验收清单）
- `56c1ef1 fix: complete beta2 release hardening`（诊断、结果预算、脱敏、资源、覆盖率与双制品 CI）
- `fb5e758 fix: complete beta2 runtime and MCP hardening`（beta.2 实现提交）
- `f8e578b docs: record beta2 verification evidence`（上一轮验证文档）
- `127acdb fix: BUG-002 real HCL parser + BUG-003 remove false positive + BUG-016 PyYAML`（前一基线）

## 执行的测试与精确结果

以下结果来自 2026-07-18 本轮本地候选；远端结果以推送后的 Draft PR #4 新 run 为准：

| 检查 | 最终结果 | 说明 |
|---|---|---|
| `uv sync --locked --extra dev` | 通过 | 锁定环境检查 78 个包，`uv pip check` 无冲突 |
| `uv run --locked ruff check .` | 通过 | 无 lint 问题 |
| `uv run --locked ruff format --check .` | 通过 | 110 个文件格式合格 |
| `uv run --locked mypy src scripts/check_distribution.py scripts/check_docs.py scripts/check_repository.py` | 通过 | 73 个源/脚本文件无类型错误 |
| 严格 warning + coverage 全量测试 | 通过 | **767 passed、3 skipped in 60.81s**，Python 3.14.5 |
| active-v0.1 line coverage | 通过 | **87.56%**；3,931 statements / 489 missed，门槛 85% |
| 文档/结构化示例 | 通过 | 29 个 Markdown、24 个内部链接、10 个 JSON/YAML 示例；workflow Action 均固定 40 位 SHA |
| 依赖/许可证 | 通过 | `pip-audit` 无已知漏洞；GPL/AGPL deny gate 通过 |
| `uv build --clear` | 通过 | 仅生成一个 `0.1.0b2` wheel 与一个 sdist |
| Python 3.12 干净 wheel | 通过 | 解析并安装 33 个依赖，官方 stdio **7 passed in 10.33s** |
| Python 3.12 干净 sdist | 通过 | 解析并安装 33 个依赖，官方 stdio **7 passed in 9.58s** |
| 制品内容策略 | 通过 | wheel 77 members、sdist 174 members；许可证/schema 存在，无本地 Agent 状态、凭据/专有资产、危险链接或路径 |
| Claude Code 客户端 | 通过 | 2.1.211，隔离临时 `CLAUDE_CONFIG_DIR`，`mcp list/get` 报告 `Connected`；未调用模型 API |
| GitHub Actions | 条件通过 | CI run `29597839925`、docs run `29597840557` 及 security run `29597839864` 的代码侧检查通过；唯一失败 Dependency Review 因 Dependency Graph disabled |
| `git diff --check` | 通过 | 无空白错误 |

制品 stdio 场景在仓库外工作目录运行并清除 `PYTHONPATH`，精确断言 15 个 Tool、对全部公开 Tool 做最小调用，并验证本轮审计事件的非空过滤查询。

真实 HCL 5.10.3 通过官方 `ClientSession` 子进程再次只读验证：发现 1 个项目、6 个设备、5 条链路，仅保留 2 个 S6850 H3C candidate；running `0/6`、operable `0/2`。本轮因没有 verified endpoint 未发送设备命令；历史负向调用稳定返回 `DEVICE_NOT_RUNNING`。

## 未执行的验证

- 真实 HCL 目标项目处于运行状态时成功执行 `display version`、`display ip interface brief`。
- TestPyPI/PyPI、GitHub Release、tag 和全新外部用户公开安装测试（尚未授权发布）。

## 已知问题和风险

1. 真实 HCL 5.10.3 项目可只读解析，但最新检查时目标项目/设备未运行，runtime 正确返回 0 个 running endpoint；真实命令成功路径仍未验证。
2. beta.2 本地制品已构建但尚未发布 PyPI；文档和示例必须使用源码虚拟环境，不可宣称 `uvx h3c-hcl-mcp` 已可用。
3. `h3c_diff_config`、Job 创建、SSH、NETCONF、HTTP 和所有写操作尚未实现。
4. Tool alias 尚待维护者决定，但 namespaced Tool 不影响 MCP 协议可发现性。
5. Draft PR #4 最新 CI/docs/security/CodeQL 的代码侧门禁通过；Dependency Review 因 Dependency Graph disabled 失败。GitHub API 对 `main` protection 查询返回 404 `Branch not protected`，成功检查不会被 required checks 强制执行。
6. 候选 feature 分支和 Draft PR 均已就绪；启用 `main` 分支保护属于仓库治理变更，需维护者明确授权。
7. Claude Code 隔离连接已通过；Claude Desktop 和 Cursor 仍缺真实 UI 级连接记录。Cursor 3.11.25 的隔离 CLI 尝试在进入 MCP 前因自身 Windows `MachineGuid` 查询失败退出，未创建临时 profile、未留下进程，不能归因于 Server。
8. Dependency Graph 与 Private Vulnerability Reporting 当前关闭，`pypi` environment/Trusted Publisher/显式发布开关尚未由维护者配置。

## 下一阶段任务

1. 请维护者在 HCL GUI 打开目标项目并启动只读测试设备；只执行两条允许的 display 命令。
2. 请维护者决定是否为 `main` 启用 branch protection，并把 CI、docs、security/CodeQL 和 package 门禁设为 required checks。
3. 在 Claude Desktop 与 Cursor GUI 各完成一次 15-Tool 发现和 `server_health` 调用记录。
4. 启用 Private Vulnerability Reporting，配置受保护的 `pypi` environment 与 Trusted Publisher；这些仓库设置需维护者明确授权。
5. 正向 HCL 和客户端证据通过后给出公开发布决策；merge、tag、Release、PyPI 仍需维护者授权。

## 接管所需命令

```powershell
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --cov=h3c_hcl_mcp --cov-report=term-missing --cov-fail-under=85
uv run python scripts/check_docs.py .
uv run python scripts/check_repository.py .
uv build --clear
uv run python scripts/check_distribution.py dist
```

客户端从源码测试时，把 `command` 指向仓库 `.venv\Scripts\h3c-hcl-mcp.exe`，并用 `--projects-dir` 或 `%LOCALAPPDATA%\h3c-hcl-mcp\config.yaml` 指定项目目录。禁止把真实 HCL 文件、日志、配置或凭据复制进仓库。
