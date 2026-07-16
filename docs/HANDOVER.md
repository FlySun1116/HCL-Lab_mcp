# HANDOVER — HCL-Lab MCP Server

## 当前版本/分支

- 候选版本：`0.1.0-beta.2`（未发布）
- 分支：`codex/beta2-release-candidate`
- 当前实现提交：`56c1ef1`
- beta.2 集成状态：源码门禁、覆盖率和 wheel/sdist 独立安装验收通过；真实运行 HCL 的两条只读命令和远端发布仍待外部条件/授权
- 日期：2026-07-16
- 发布状态：未创建 tag、GitHub Release 或 PyPI 包

## 目标 Issue/PR

当前目标是完成 beta.1 测试报告中 parser、runtime、配置、validation、audit、安全和并发问题的修复，形成 `v0.1.0-beta.2` 可验证候选。当前没有可在本文确认的 PR 编号；发布和远端操作需由维护者授权。

## 完成内容

### HCL 项目解析

- 支持 HCL 5.10.x `projectInfo` / `deviceInfoList.resource*` 实际 JSON 结构。
- 支持嵌套 ConfigObj 风格 `.net`，由 `.net` 提供权威 `device_id` 和链路。
- 按设备名称大小写不敏感合并两种来源，链路去重并输出确定性 warning。
- 拒绝绝对路径、目录分隔符、`..`、realpath/symlink 项目根目录逃逸。
- MCP 项目列表和错误不泄漏本机绝对路径。

### Runtime 与 console

- 从 HCL 5.10.x 轮转日志按时间顺序归并项目绑定、console 创建/关闭和 alias 重绑定。
- 任何 HCL 进程存在不再等价于全部设备运行。
- 端口公式不生成 candidate；只探测明确绑定到目标项目/设备的日志 candidate。
- candidate 仅允许 loopback，必须通过 TCP/Telnet 和 Comware prompt 探测；不回答登录/密码，不执行探测命令。
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

### 安全、会话与 Tool

- v0.1 保持 15 个 namespaced Tool；短 alias 尚未注册。
- `h3c_diff_config` 明确返回 `NOT_IMPLEMENTED`；v0.2 写 Tool 未注册。
- PC/终端节点不进入 H3C/Comware 设备列表。
- 所有设备 raw output 在 MCP 边界强制脱敏；`h3c_get_config(redact=false)` 返回 `POLICY_DENIED`。
- 拓扑响应不暴露 `config_path`；提示符错误不携带设备 buffer；PEM/OpenSSH/EC/ENCRYPTED 及截断私钥块均会整段脱敏。
- endpoint 携带项目/设备上下文；task-local 会话状态和设备连接锁防止并发串设备。
- Telnet 连接使用配置的 connection timeout，不再误用 endpoint confidence。
- connect/prompt/EOF/command-timeout/cancelled 失败都会关闭并失效连接，迟到输出不会污染下一次调用。
- HCL 文件扫描和拓扑解析在线程中执行，不阻塞 stdio 事件循环；拓扑刷新会删除已从项目移除的旧 runtime 设备。
- deep health 实际枚举项目，并对首个项目执行 runtime discovery。
- `h3c_ping`/`h3c_trace_route` 使用严格的目标、次数和最大跳数 Schema，并输出结构化诊断摘要。
- 最终 MCP `CallToolResult` 按 UTF-8 实际字节数执行硬上限；成功、错误、Schema、未知 Tool 和超时路径均受限，超限返回稳定 `OUTPUT_TOO_LARGE`。
- 设备结果标记 `content_trust=untrusted_device_output`；结构化 parser 结果不再保留重复 raw 副本。
- SNMP community、NTP authentication、RADIUS/HWTACACS shared key、`super password` 的 role/hash/cipher/simple 变体均在完整和快速路径强制脱敏。
- project list cursor 已接入 repository 分页；恶意超长 Tool/project 标识在进入审计前受限。
- 进程检查、日志加载移出事件循环；日志观察限制为最多 16 个文件、每文件最多 4 MiB，并显式关闭 SQLite、scandir 和测试 Telnet writer。

### GitHub 与 Agent 接管

- `.github/ISSUE_TEMPLATE/` 提供 Bug、Feature 和 Agent Task 表单；Agent Task 强制记录 owned/forbidden files、依赖、验收证据和交接对象。
- PR 模板固定架构影响、完整门禁、Secret/专有资产、安全策略、真实设备只读与外部发布动作检查项。

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
- `.github/ISSUE_TEMPLATE/`、`.github/pull_request_template.md`、`.github/workflows/ci.yml`
- `pyproject.toml`、`uv.lock`、版本模块

## 关键决策/ADR

- ADR-0001～0006 继续有效：Python 3.12、stdio、本机项目文件 + loopback console、六边形架构、默认只读、不实现 HCL 私有协议。
- beta.2 runtime 采取“日志明确绑定 + prompt 验证”；`fallback_telnet_base` 仅保留配置兼容，不产生 endpoint。
- 15 个 namespaced Tool 是当前公共契约；短 alias 由维护者按 `docs/TOOL_ALIAS_PROPOSAL.md` 决策。
- v0.1 不开放配置写入、SSH、NETCONF、HTTP 或 HCL lifecycle。

## Git commits

- `39ed695 chore: add agent-ready GitHub templates`（Issue forms 与 PR 接管/验收清单）
- `56c1ef1 fix: complete beta2 release hardening`（诊断、结果预算、脱敏、资源、覆盖率与双制品 CI）
- `fb5e758 fix: complete beta2 runtime and MCP hardening`（beta.2 实现提交）
- `f8e578b docs: record beta2 verification evidence`（上一轮验证文档）
- `127acdb fix: BUG-002 real HCL parser + BUG-003 remove false positive + BUG-016 PyYAML`（前一基线）

## 执行的测试与精确结果

以下结果来自冻结后的 beta.2 候选：

| 检查 | 最终结果 | 说明 |
|---|---|---|
| `uv sync --locked --extra dev` | 通过 | 锁定 51 个包 |
| `uv run --locked ruff check .` | 通过 | 无 lint 问题 |
| `uv run --locked ruff format --check .` | 通过 | 101 个文件格式合格 |
| `uv run --locked mypy src` | 通过 | 69 个源文件无类型错误 |
| 严格 warning + coverage 全量测试 | 通过 | **628 passed in 57.82s**，Python 3.14.5 |
| active-v0.1 line coverage | 通过 | **86.83%**；3,646 statements / 480 missed，门槛 85% |
| `uv build --clear` | 通过 | 仅生成一个 `0.1.0b2` wheel 与一个 sdist |
| Python 3.12 干净 wheel | 通过 | 独立环境安装，版本/console entry point 断言通过，官方 stdio **7 passed in 8.89s** |
| Python 3.12 干净 sdist | 通过 | 第二个独立环境安装，版本/console entry point 断言通过，官方 stdio **7 passed in 8.47s** |
| 制品内容策略 | 通过 | wheel 76 members、sdist 151 members；许可证/schema 存在，无危险扩展名、路径穿越或超大 tracked 文件 |
| `git diff --check` | 通过 | 无空白错误 |

制品 stdio 场景在仓库外工作目录运行并清除 `PYTHONPATH`，精确断言 15 个 Tool、对全部公开 Tool 做最小调用，并验证本轮审计事件的非空过滤查询。

真实 HCL 5.10.3 通过官方 `ClientSession` 子进程只读验证：发现 1 个项目、6 个设备、5 条链路，仅保留 2 个 S6850 H3C candidate；当时 running `0/6`、30001/30002 均关闭，两条 display 均稳定返回 `DEVICE_NOT_RUNNING`。

## 未执行的验证

- 真实 HCL 目标项目处于运行状态时成功执行 `display version`、`display ip interface brief`。
- TestPyPI/PyPI、GitHub Release、tag 和全新外部用户公开安装测试（尚未授权发布）。

## 已知问题和风险

1. 真实 HCL 5.10.3 项目可只读解析，但最新检查时目标项目/设备未运行，runtime 正确返回 0 个 running endpoint；真实命令成功路径仍未验证。
2. beta.2 本地制品已构建但尚未发布 PyPI；文档和示例必须使用源码虚拟环境，不可宣称 `uvx h3c-hcl-mcp` 已可用。
3. `h3c_diff_config`、Job 创建、SSH、NETCONF、HTTP 和所有写操作尚未实现。
4. Tool alias 尚待维护者决定，但 namespaced Tool 不影响 MCP 协议可发现性。
5. GitHub Actions 配置已补齐 wheel/sdist 独立安装门禁，但远端 workflow 和 `main` required-check/branch-protection 状态尚未在本地证明。

## 下一阶段任务

1. 请维护者在 HCL GUI 打开目标项目并启动只读测试设备；只执行两条允许的 display 命令。
2. beta.2 本地集成 commit、Secret/专有资产复核和双制品门禁完成后，等待正向 HCL 证据再更新最终发布报告。
3. 正向 HCL 证据通过后给出公开发布决策；push、tag、Release、PyPI 仍需维护者授权。

## 接管所需命令

```powershell
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --cov=h3c_hcl_mcp --cov-report=term-missing --cov-fail-under=85
uv build --clear
```

客户端从源码测试时，把 `command` 指向仓库 `.venv\Scripts\h3c-hcl-mcp.exe`，并用 `--projects-dir` 或 `%LOCALAPPDATA%\h3c-hcl-mcp\config.yaml` 指定项目目录。禁止把真实 HCL 文件、日志、配置或凭据复制进仓库。
