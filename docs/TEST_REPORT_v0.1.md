# HCL-Lab_mcp v0.1 测试报告

> 测试对象：`0.1.0-beta.2` 本地提交候选
> 分支基线：`da7747b` + 本报告所在提交
> 证据基线：2026-07-18 本地源码、协议、双制品、文档、依赖和安全门禁；远端 CI/docs/security/CodeQL 已刷新
> 报告日期：2026-07-18
> 当前结论：**CONDITIONAL GO**（本地与远端代码门禁通过；Dependency Review 等待启用 Dependency Graph，真实运行设备正向验证、客户端 UI 与维护者发布授权仍待完成）

本报告替代 beta.1 的旧失败快照。所有“已修复”结论均以当前源码、自动化测试或本机只读观察为依据；没有把未运行设备上的命令伪造为成功。仓库尚未发布 PyPI、tag 或 GitHub Release。

# 测试环境

| 项目 | 环境 |
|---|---|
| 操作系统 | Windows，本机 HCL 环境 |
| HCL | H3C Cloud Lab 5.10.3 |
| 项目主运行时 | Python 3.14.5（冻结候选全量测试） |
| 发布目标运行时 | Python 3.12.13（干净 beta.2 wheel 与 sdist 均已验证） |
| Python 包版本 | `0.1.0-beta.2`（PEP 440：`0.1.0b2`） |
| MCP SDK | 官方 MCP Python SDK `1.28.1`（依赖限制 `>=1.28.1,<1.29`） |
| MCP transport | `stdio` |
| 实际 MCP Client | Claude Code 2.1.211 隔离临时 profile 已连接；Cursor 3.11.25 CLI 在 MCP 前因 MachineGuid 查询失败；Claude Desktop/Cursor UI 待测 |
| 真实设备写操作 | 未执行；测试只允许 read-only |

本机路径、用户名、真实项目名称、原始日志和设备配置均未写入本报告或测试 fixture。

# 测试项目

## 第一阶段：安装与配置

| 项目 | 当前结果 | 证据/说明 |
|---|---|---|
| 开发依赖安装 | 通过 | 当前虚拟环境可运行全部源码测试 |
| 无配置启动 | 通过 | 官方 stdio 子进程完成 initialize/list/call；采用安全默认值 |
| `--projects-dir` | 通过 | 子进程发现临时项目 fixture |
| 嵌套环境变量 | 通过 | JSON 列表配置项目目录生效 |
| JSON 配置 | 通过 | 显式项目目录生效 |
| YAML 配置 | 通过 | `PyYAML` 已加入运行依赖，显式项目目录生效 |
| 显式缺失配置 | 通过 | 退出码 1、stdout 为空、stderr 明确报错 |
| 显式损坏配置 | 通过 | 在 MCP 协议启动前失败关闭 |
| beta.2 wheel/sdist | 通过 | `uv build --clear` 仅生成一个 `0.1.0b2` wheel 和一个 sdist |
| Python 3.12 干净 wheel | 通过 | 依据 wheel 元数据解析并安装 33 个依赖；官方 stdio 7 passed in 7.18s |
| Python 3.12 干净 sdist | 通过 | 依据 sdist 元数据解析并安装 33 个依赖；官方 stdio 7 passed in 7.22s |
| Claude Code 隔离连接 | 通过 | 2.1.211，临时 `CLAUDE_CONFIG_DIR`，`mcp list/get` 返回 `Connected`；未调用模型 API |
| 公共 registry 安装 | 失败/未发布 | PyPI 不存在 beta.2，不能使用 `uvx h3c-hcl-mcp` |

## 第二阶段：MCP 协议

官方 `mcp.ClientSession` 启动真实子进程，不使用进程内私有调用代替 stdio 验收。

| 测试 | 结果 | 实际行为 |
|---|---|---|
| `initialize` | 通过 | `serverInfo.name` 与配置一致，版本为 beta.2 |
| `tools/list` | 通过 | 返回 15 个 namespaced Tool |
| `tools/call` 成功路径 | 通过 | `server_health(deep=false)` 返回结构化成功结果 |
| `tools/call` Schema 失败 | 通过 | 返回 `isError=true` 和结构化 `INVALID_ARGUMENT` |
| validation 隐私 | 通过 | 不含 Pydantic `input_value` 或外部文档 URL |
| stdout framing | 通过 | 官方客户端可连续解析 JSON-RPC；启动文本位于 stderr |
| request/audit 关联 | 通过 | Schema 与领域错误的响应、事件使用相同 request_id/错误码 |
| 审计不可用 | 通过 | 审计开启且持久化失败时 fail closed，返回稳定 `INTERNAL_ERROR`/`AUDIT_UNAVAILABLE` |
| 未知 Tool | 通过 | 稳定 `INVALID_ARGUMENT`、带 request_id，并写入同一审计事件 |
| 全局 Tool 超时 | 通过 | `server.max_tool_seconds` 在 ToolManager 边界返回稳定 `TIMEOUT` |
| 最终输出预算 | 通过 | `CallToolResult` 两个通道按 UTF-8 字节精确计量；所有结果/错误路径受硬上限保护 |
| 安装制品全 Tool smoke | 通过 | 精确断言 15 个 Tool，全部做最小调用，并查询非空的本轮审计事件 |
| 公共输入与日志隐私边界 | 通过 | 客户端字符串均有 Schema 上限；日志参数/异常有界且清除凭据、Windows/UNC/任意 POSIX 绝对路径，同时保留 HTTPS URL |

## 第三阶段：Tool 功能

beta.2 注册 15 个 Tool：

| Tool | 当前状态 | 验证结论 |
|---|---|---|
| `server_health` | 可用 | shallow 成功；deep 使用真实项目/runtime 路径，不再无条件报 healthy |
| `hcl_list_projects` | 可用 | fixture 与本机 HCL 5.10.3 项目均可发现；响应不含绝对路径 |
| `hcl_get_topology` | 可用 | 真实格式与 fixture 可解析；路径攻击被拒绝 |
| `hcl_get_runtime` | 可用 | 未验证 prompt 的端口不会成为 endpoint；project/device 查询一致 |
| `h3c_list_devices` | 可用 | H3C/Comware 候选保留，PC/终端过滤；operable 依赖 verified endpoint |
| `h3c_get_facts` | 条件可用 | fake console 链路通过；真实运行设备正向路径待测 |
| `h3c_run_display` | 条件可用 | 策略、会话和 fake console 通过；真实运行设备正向路径待测 |
| `h3c_get_config` | 条件可用 | `running/startup` Schema 正确；强制脱敏；`redact=false` 被拒绝 |
| `h3c_get_interfaces` | 条件可用 | parser/fake transport 通过；真实运行设备正向路径待测 |
| `h3c_ping` | 条件可用 | 严格目标/次数 Schema、诊断策略和结构化 parser 通过；真实运行设备正向路径待测 |
| `h3c_trace_route` | 条件可用 | 严格目标/最大跳数 Schema、诊断策略和结构化 parser 通过；真实运行设备正向路径待测 |
| `h3c_diff_config` | 占位 | 稳定返回 `NOT_IMPLEMENTED`，没有伪装成功 |
| `job_get` | 占位 | Tool 可发现；当前 JobStore 尚不创建生产 Job |
| `job_cancel` | 占位 | Tool 可发现；当前 JobStore 尚不创建生产 Job |
| `audit_query` | 可用 | 支持 request/tool/device/time/limit；时间和范围错误为 `INVALID_ARGUMENT` |

用户早期验收名称 `list_devices`、`execute_command`、`configure_device`、`get_device_status`、`ping_test` 没有注册。当前正式契约使用 namespaced Tool；`configure_device` 属 v0.2 写能力。短 alias 是否增加仍由维护者依据 `docs/TOOL_ALIAS_PROPOSAL.md` 决策，不能在 beta.2 检阅中擅自改变公共 Schema。

## 第四阶段：真实 HCL 5.10.3（只读）

| 测试 | 结果 | 证据 |
|---|---|---|
| 真实项目发现 | 通过 | 读取 `projectInfo`/`deviceInfoList` 实际格式 |
| 真实 `.net` | 通过 | 解析嵌套 `[vbox]` / `[[MODEL name]]` 设备与链路 |
| 元数据合并 | 通过 | `.net` ID 权威、名称大小写不敏感合并、无异常 warning |
| H3C 节点过滤 | 通过 | S6850 类节点保留，PC 类节点不作为 H3C 可操作设备 |
| 目标项目 runtime | 通过（负向） | 官方 ClientSession 再次确认：6 个设备、running_count=0、2 个 H3C candidate、operable_count=0；未发送设备命令 |
| 关闭端口处理 | 通过（负向） | 30001/30002 关闭，未被公式或 Simware/HCL 进程误报为 operable |
| `display version` | 通过（负向）/正向待测 | 官方 ClientSession 返回 `DEVICE_NOT_RUNNING` |
| `display ip interface brief` | 通过（负向）/正向待测 | 官方 ClientSession 返回 `DEVICE_NOT_RUNNING` |
| 配置命令 | 未执行 | v0.1 禁止写操作 |

这证明 parser 与“无假阳性”负向路径可用，但不能证明真实 console 的完整成功链路。最终发布候选必须在维护者从 HCL GUI 打开目标项目并启动设备后，只读执行两条允许命令。

## 第五阶段：质量门禁

冻结 beta.2 候选后的最终快照：

| 检查 | 最终结果 |
|---|---|
| `uv run --locked ruff check .` | 通过 |
| `uv run --locked ruff format --check .` | 通过：110 个文件 |
| `uv run --locked mypy src scripts/check_distribution.py scripts/check_docs.py scripts/check_repository.py` | 通过：73 个源/脚本文件 |
| 严格 warning + coverage 全量测试 | 通过：**745 passed、3 skipped in 59.83s**，Python 3.14.5 |
| active-v0.1 line coverage | 通过：**87.38%**；3,874 statements / 489 missed，门槛 85% |
| 文档/示例/Action SHA | 通过：29 个 Markdown、24 个内部链接、10 个结构化示例 |
| 依赖/许可证 | 通过：`uv pip check`、`pip-audit`、GPL/AGPL deny gate |
| `uv build --clear` | 通过：唯一 `0.1.0b2` wheel/sdist |
| Python 3.12 wheel stdio | 通过：元数据解析 33 个依赖、独立安装、**7 passed in 7.18s** |
| Python 3.12 sdist stdio | 通过：元数据解析 33 个依赖、独立安装、**7 passed in 7.22s** |
| 制品内容策略 | 通过：wheel 77/sdist 174 members；许可证/schema 存在，无本地 Agent 状态、凭据/专有资产、危险链接、路径穿越或超大成员 |
| GitHub Actions | 条件通过：run `29597839925`、`29597840557`、`29597839864` 的代码侧检查通过；Dependency Review 仅因 Dependency Graph disabled 失败 |
| `git diff --check` | 通过 |

# 成功项

1. 真实 HCL 5.10.x JSON/.net parser 已替换 beta.1 的错误字段假设。
2. 项目 ID 路径穿越、绝对路径、分隔符和 root-escape 检查已覆盖。
3. Runtime 不再使用公式或“任意 HCL 进程”制造 running/operable 假阳性。
4. 日志绑定、console close/rebind、loopback 和 Comware prompt 验证有脱敏 fixture 测试。
5. 项目级和设备级 runtime 共用状态来源与短期缓存。
6. CLI/env/JSON/YAML/无配置/非法配置均有 stdio 子进程覆盖。
7. 官方 MCP Client 可 initialize、列出 15 个 Tool、调用 Tool 并获得结构化结果。
8. Schema 失败为稳定 `INVALID_ARGUMENT`，response/audit request_id 可关联。
9. 审计区分 `policy_result` 与 `outcome`，保留真实错误码；禁用时不创建数据库。
10. 设备输出在 MCP 边界强制脱敏，不能通过 `redact=false` 绕过。
11. PC/终端节点过滤、设备连接上下文和并发防串设备测试已覆盖。
12. 真实项目未运行时返回 `DEVICE_NOT_RUNNING`，没有伪造命令成功。
13. 策略配置只能收紧内置命令规则，配置 allowlist/deny pattern 不能绕过强制注入和危险命令检查。
14. 未知 Tool、Schema 失败和全局 Tool 超时都有稳定错误码、request_id 和单一审计事件。
15. Telnet prompt/EOF/timeout/cancelled 路径会失效连接，迟到输出不会进入下一条命令。
16. 错误响应与拓扑响应不会泄漏 console buffer、配置路径或本机路径。
17. PEM/OpenSSH/EC/ENCRYPTED 及截断私钥块、SNMPv3 凭据均有脱敏回归。
18. HCL 文件扫描在线程中执行，不阻塞 stdio 事件循环；所有合法 Tool 受全局超时保护。
19. beta.2 wheel/sdist 仅依据各自包元数据在 Python 3.12.13 干净环境安装，7 个官方 stdio 场景全部通过。
20. `ping`/`tracert` 具有严格参数模型、诊断分类和结构化结果 parser。
21. 最终 MCP 返回按真实 UTF-8 字节硬限制，超限结果有稳定错误和审计事件。
22. SNMP、NTP、RADIUS/HWTACACS、`super password` 等 Comware 凭据语法均覆盖完整/快速脱敏路径。
23. 同设备 100 并发 fake-console 请求未串线；阻塞 I/O、SQLite/scandir/Telnet 资源和日志读取边界已回归。
24. CI 已配置 active-v0.1 85% 覆盖率门禁，以及 wheel/sdist 两套独立安装 stdio smoke。
25. Bug/Feature/Agent Task Issue 表单与 PR 模板已固化模块所有权、验收证据、安全边界和 Agent 交接要求。
26. 所有第三方 GitHub Actions 已升级到当前 Node 24 版本并固定完整 commit SHA，避免可变 tag 与 Node 20 下线风险。
27. Claude Code 2.1.211 使用隔离临时配置真实启动 stdio Server 并报告 `Connected`，没有污染用户配置或产生模型 API 调用。
28. `key-string`、WEP key、WLAN/IPsec pre-shared-key 已进入完整/快速脱敏回归。
29. Telnet IAC 分片、loopback/transport 边界、全局会话上限、空闲/命令次数回收和 lifespan 清理已验证。
30. 审计持久化失败会 fail closed；公共字符串和客户端日志参数有服务端硬边界。
31. 启动、审计、SecretProvider 和异常日志不再暴露本机绝对路径；通用 POSIX 规则覆盖 `/etc`、`/usr/local` 和自定义根目录且不破坏 HTTPS URL。
32. wheel/sdist 成员策略已自动化，sdist 不再包含本地 Claude/Agent 状态。
33. [Draft PR #4](https://github.com/FlySun1116/HCL-Lab_mcp/pull/4) 的 Linux quality/contracts/full、Windows full/package 和 secret scan 六项 CI 全部通过。
34. Linux mypy 平台差异与 gitleaks-action v3 Token 要求已修复，secret scan 已实际执行而非仅静态配置。

# 失败项

1. 真实运行设备的 `display version` 和 `display ip interface brief` 正向链路尚未验证。
2. PyPI、tag 和 GitHub Release 尚未发布；公共 `uvx` 安装不可用。
3. `h3c_diff_config` 和 Job 生产用例仍是占位能力。
4. 短 Tool alias 尚未决策/注册，但 namespaced Tool 的 MCP 可发现性已通过。
5. 尚未在本机真实 Claude Desktop 与 Cursor UI 中记录同一候选的启动证据；Cursor 隔离 CLI 在 MCP 初始化前被自身 Windows MachineGuid 查询阻塞，官方 MCP SDK 与 Claude Code stdio 已通过。
6. 远端代码侧 GitHub Actions 已通过，但 Dependency Review 因仓库未启用 Dependency Graph 而失败；`main` 也尚未启用 branch protection/required checks。

# Bug列表

## BUG-001

编号：BUG-001

级别：P0

状态：OPEN

问题：公开 package registry 没有 beta.2，外部用户不能按 `uvx h3c-hcl-mcp` 安装。

复现步骤：在未安装本地源码/本地 wheel 的干净环境尝试从 PyPI 启动包。

预期：发布授权后能安装固定版本并返回一致的 Server 版本。

实际：当前没有 beta.2 PyPI 包、tag 或 GitHub Release。

根因：本地质量门禁已完成；公开发布仍缺真实 HCL 正向证据和维护者授权。

修复：先完成本报告所有退出检查，再按发布流程申请授权；发布前文档只提供源码虚拟环境配置。

验证证据：当前客户端示例已移除未发布的 `uvx` 路径。

## BUG-002

编号：BUG-002

级别：P0

状态：VERIFIED

问题：beta.1 无法解析真实 HCL 5.10.3 项目。

复现步骤：读取包含 `projectInfo`、`deviceInfoList.resource*` 和嵌套 `.net` 的项目。

预期：列出项目，并用 `.net` ID 构建设备和链路。

实际：beta.2 的 synthetic-real fixture 和本机真实项目均成功。

根因：旧 parser 假定了不存在的扁平字段和标准 INI 结构。

修复：实现真实字段归一化和 ConfigObj 风格嵌套 parser，按名称合并来源。

验证证据：parser/repository 单元测试与本机只读项目检查通过。

## BUG-003

编号：BUG-003

级别：P0

状态：VERIFIED

问题：beta.1 把未监听的公式端口报告为 running/operable，project/device 查询互相矛盾。

复现步骤：HCL 进程存在但目标项目未打开时查询 runtime 和设备列表。

预期：没有明确日志绑定和 prompt 验证就不得发布 endpoint。

实际：beta.2 返回 running_count=0、无 endpoint，设备命令返回 `DEVICE_NOT_RUNNING`。

根因：旧实现把 HCL 进程、端口公式和设备运行态错误等同。

修复：日志状态机、candidate/probe 分离、Comware prompt 验证、共享 cache 和 project-aware 注册。

验证证据：closed/rebound/formula/prompt 自动化测试及本机负向检查通过。

## BUG-004

编号：BUG-004

级别：P1

状态：VERIFIED

问题：beta.1 强制配置文件，YAML/环境变量/CLI 启动路径不闭环。

复现步骤：分别使用无配置、CLI、环境变量、JSON、YAML、显式缺失和损坏配置启动子进程。

预期：前五种可用；显式错误文件在协议前失败。

实际：行为符合预期。

根因：旧 loader 将默认文件缺失和显式文件错误混为一类，且依赖/merge 不完整。

修复：安全默认值、严格显式文件、PyYAML 运行依赖、嵌套 env JSON coercion。

验证证据：`tests/integration/test_stdio_client.py` 的 7 个场景包含上述启动路径。

## BUG-005

编号：BUG-005

级别：P2

状态：BLOCKED

问题：早期验收提示词使用五个短 Tool 名称，当前公共契约使用 15 个 namespaced Tool。

复现步骤：检查 `tools/list` 中是否存在 `list_devices` 等短名称。

预期：由维护者明确 alias 策略，避免 Agent 擅自扩展公共 API。

实际：短名称未注册；正式 namespaced Tool 可发现。

根因：用户验收用语与项目 namespaced 契约来源不同。

修复：等待维护者对 `docs/TOOL_ALIAS_PROPOSAL.md` 作产品决策；v0.1 不开放 `configure_device`。

验证证据：官方 `tools/list` 返回 15 个正式 Tool。

## BUG-009

编号：BUG-009

级别：P1

状态：VERIFIED

问题：错误审计曾丢失真实 error code/request_id，并把执行失败误记为策略拒绝。

复现步骤：触发 `PROJECT_NOT_FOUND`、`NOT_IMPLEMENTED`、`INVALID_ARGUMENT` 和 Schema failure 后查询 SQLite。

预期：响应和事件 ID/错误码一致，policy 与 outcome 分离。

实际：beta.2 符合预期，Schema failure 也有事件。

根因：validation、error mapping 与 audit 分散在不同调用边界。

修复：包装实际 ToolManager 调用边界，复用 result request_id，引入 `outcome` 字段和迁移。

验证证据：协议级 validation/audit 集成测试通过。

## BUG-014

编号：BUG-014

级别：P1

状态：VERIFIED

问题：beta.1 validation middleware 没有作用于官方 stdio 调用路径。

复现步骤：传入非法 `source`、`count` 或 `audit_query.limit`。

预期：稳定、结构化 `INVALID_ARGUMENT`，包含字段/范围/request_id。

实际：beta.2 符合预期且不泄漏 Pydantic 细节。

根因：旧实现替换了 FastMCP 注册完成后不会被协议 handler 调用的表面方法。

修复：包装实际 ToolManager 的 `call_tool`。

验证证据：内存协议测试和真实 stdio 子进程测试通过。

## BUG-016

编号：BUG-016

级别：P1

状态：VERIFIED

问题：beta.1 干净环境缺少 YAML 运行依赖。

复现步骤：安装包后导入 `yaml` 或使用 YAML 配置启动。

预期：运行依赖包含 PyYAML。

实际：`pyproject.toml`/锁文件包含 PyYAML，YAML stdio 测试通过。

根因：只添加了类型桩，没有添加运行包。

修复：将 `pyyaml>=6.0.3` 加入 production dependencies。

验证证据：当前候选 745 passed、3 skipped；Python 3.12.13 干净 wheel 与 sdist 的 YAML/JSON/CLI/env stdio 场景均进入 7 passed。

## BUG-017

编号：BUG-017

级别：P0

状态：BLOCKED

问题：真实运行设备的完整 console 命令成功链路尚无证据。

复现步骤：在 HCL GUI 打开目标项目、启动目标 H3C 设备，再调用两条允许命令。

预期：verified endpoint 上成功执行 `display version` 和 `display ip interface brief`，输出脱敏且不串设备。

实际：最新检查时目标项目/设备未运行，只验证了 `DEVICE_NOT_RUNNING` 负向路径。

根因：外部 HCL 运行状态不满足正向测试前提，不是 Server 假阳性。

修复：由维护者启动测试设备；测试工程师只执行 read-only 命令。

验证证据：待补充真实 stdio 调用记录；不得用 fake console 替代本项。

## BUG-018

编号：BUG-018

级别：P1

状态：VERIFIED

问题：并发集成期间 Ruff format gate 曾失败，且当时全量测试后仍有修改。

复现步骤：执行 `uv run --locked ruff format --check .`。

预期：全部文件格式合格，并在冻结候选上运行全量门禁。

实际：最终已格式化；`ruff format --check` 报告 110 个文件全部合格。

根因：多个 beta.2 修复并行集成时尚未执行最终格式化和冻结回归。

修复：Team Lead 运行 formatter，审查 diff，并重跑 ruff check/format、mypy、pytest、build 和 wheel/sdist clean-artifact stdio。

验证证据：Ruff check/format 通过、mypy 73 个源/脚本文件通过、745 passed/3 skipped、87.38% active-v0.1 coverage、beta.2 clean build 通过，Python 3.12 wheel/sdist stdio 各 7 passed。

## BUG-019

编号：BUG-019

级别：P1

状态：VERIFIED

问题：`allow_display_prefixes` 和 `deny_patterns` 曾只存在于配置模型，策略引擎没有使用，造成虚假安全保证。

复现步骤：配置只允许 `display version`，再提交 `display interface brief`；或配置拒绝 `brief` 后执行该命令。

预期：自定义规则只能进一步收紧内置安全策略，且拒绝规则优先。

实际：修复前命令仍按内置规则放行；修复后均返回 `COMMAND_NOT_ALLOWED`。

根因：`PolicyEngineImpl` 调用命令校验器时没有传入配置规则。

修复：接入 restriction-only allowlist 和不区分大小写的字面 deny pattern，始终先执行不可覆盖的注入/危险规则。

验证证据：策略单元测试及 745 passed/3 skipped 候选全量回归通过。

## BUG-020

编号：BUG-020

级别：P1

状态：VERIFIED

问题：Telnet prompt 失败、命令超时或中途 EOF 后连接可能残留，迟到输出可能污染下一次调用；错误还可能携带原始 `buffer_tail`。

复现步骤：fake console 接受连接但不发 prompt，或把第一条命令响应延迟到 timeout 之后，再执行第二条命令。

预期：失败连接必须关闭并不可复用；第二次连接不能读到第一条迟到输出；MCP 错误不能含设备原始数据。

实际：修复后 prompt/EOF/timeout/cancelled 均清理 reader/writer/session，重连成功且无跨调用污染；错误只保留非敏感计数。

根因：连接清理由调用方承担，且 `_collect_output` 曾把 EOF/无 final prompt 当成正常结束。

修复：transport 自身在所有失败路径 fail-closed；EOF 返回 `CONNECTION_CLOSED`，无 prompt 返回 `COMMAND_TIMEOUT`，截断连接不复用；MCP 边界移除未可信输出字段。

验证证据：Telnet fake server 清理、重连、迟到输出、100 并发和错误边界测试进入 745 passed/3 skipped 全量回归。

## BUG-021

编号：BUG-021

级别：P1

状态：VERIFIED

问题：未知 Tool、全局 Tool 超时、审计时区比较和拓扑 `config_path` 曾绕过统一协议/隐私边界。

复现步骤：调用不存在的 Tool；运行超过 `max_tool_seconds` 的 Tool；用 `+08:00` 查询 UTC 事件；读取含绝对 `configPath` 的拓扑。

预期：稳定错误码/request_id/单一审计事件；时间按同一时刻比较；不返回本机配置路径；慢文件系统不阻塞 stdio loop。

实际：修复后未知 Tool 为 `INVALID_ARGUMENT`、超时为 `TIMEOUT`，审计统一 UTC，拓扑省略 `config_path`，项目扫描进入 worker thread。

根因：统一边界只处理 Pydantic validation，SQLite 对带偏移 ISO 文本直接排序，Repository 在 async 方法中同步扫描文件。

修复：扩展 ToolManager 边界、UTC 迁移/规范化、公共 topology DTO 脱敏，并用 `asyncio.to_thread` 隔离阻塞文件 I/O。

验证证据：官方内存协议、SQLite、拓扑、全局超时和最终输出预算回归进入 745 passed/3 skipped 全量回归。

## BUG-022

编号：BUG-022

级别：P1

状态：VERIFIED

问题：私钥脱敏仅覆盖完整 RSA/PKCS#8 块，OPENSSH、EC、ENCRYPTED 或被截断且缺少 END 的块可能泄漏。

复现步骤：让设备输出包含上述 PEM label，或让输出上限截断私钥块。

预期：从 BEGIN 到匹配 END 或文本末尾全部替换，不保留 key material。

实际：修复后五种 label 和截断块均整段替换；SNMPv3 usm-user 整行也强制脱敏。

根因：旧正则限定 RSA/普通 PRIVATE KEY 且要求 END，同时通用 key 规则可能先破坏 PEM 标记。

修复：把通用 PEM/OpenSSH 规则置于具体 key 规则之前，覆盖文本结尾，并补 SNMPv3 变体规则。

验证证据：脱敏聚焦测试及 745 passed/3 skipped 候选全量回归通过。

## BUG-023

编号：BUG-023

级别：P1

状态：VERIFIED

问题：`ping`/`tracert` 曾按普通 display 路径处理，参数和返回缺少明确诊断语义。

复现步骤：调用两个诊断 Tool，检查 policy classification、生成命令和结构化结果。

预期：只接受安全目标和有界参数，归类为 DIAGNOSTIC，并返回可机器理解的统计/跳点。

实际：严格 Schema、命令构造、策略分类和 Comware parser 均已接线。

根因：早期纵向切片复用了通用命令处理，未完成诊断专用 parser。

修复：新增 ping/traceroute parser，限制 ping count 1～100、tracert max hops 1～255，并拒绝重复/未知/不安全参数。

验证证据：诊断 parser 测试、六个 H3C read Tool synthetic/fake 正向链路及 745 passed/3 skipped 全量回归通过。

## BUG-024

编号：BUG-024

级别：P1

状态：VERIFIED

问题：进程/日志读取可能阻塞事件循环，部分 SQLite、scandir 和测试 Telnet writer 资源未显式关闭。

复现步骤：启用严格 ResourceWarning/PytestUnraisable，运行并发 console、runtime、日志和审计测试。

预期：无未关闭资源、无跨请求串线，阻塞文件/进程工作不占用 stdio 事件循环。

实际：相关同步 I/O 已移入线程，资源显式关闭，日志读取有文件数和大小上限。

根因：早期实现把本机同步发现路径直接放在 async 调用链，并依赖对象析构关闭资源。

修复：使用线程桥接同步发现；限制 16 个日志文件和每文件 4 MiB；补齐连接、扫描器和 writer 清理。

验证证据：100 个同设备 fake-console 并发请求无串线；严格 warning 模式下 745 passed/3 skipped。

## BUG-025

编号：BUG-025

级别：P1

状态：VERIFIED

问题：旧输出上限只限制设备 capture，没有覆盖 FastMCP 的文本和 structured 双通道最终响应。

复现步骤：让成功、领域错误、Schema 错误、未知 Tool 或超时返回超大 payload，测量最终 `CallToolResult`。

预期：所有路径按最终 UTF-8 字节数受硬限制，且仍返回稳定、可审计的错误。

实际：所有转换路径均受 `server.max_tool_result_bytes` 约束，超限返回 `OUTPUT_TOO_LARGE`。

根因：capture 字符限制不能代表序列化后的双通道协议大小，也未覆盖框架生成的错误。

修复：新增 final-result budget middleware、紧凑 JSON、受限错误 payload，并把预算放在审计边界内。

验证证据：output-budget 单元/集成测试覆盖成功、错误、未知、Schema 和超时；745 passed/3 skipped 全量回归。

## BUG-026

编号：BUG-026

级别：P1

状态：VERIFIED

问题：部分 Comware 凭据语法（特别是 `super password role ... hash/cipher/simple`）可能绕过脱敏。

复现步骤：向完整和快速脱敏路径输入 SNMP、NTP、RADIUS/HWTACACS 与 super password 大小写/空格变体。

预期：秘密值从文本、结构化结果、日志和审计通道全部移除。

实际：所有受测语法均整行或值级脱敏，秘密值不残留。

根因：旧规则只覆盖少数固定 token 位置，没有描述 role 和编码模式组合。

修复：扩展顺序敏感的凭据规则，并为完整/快速路径增加对称回归。

验证证据：脱敏聚焦测试和 745 passed/3 skipped 全量回归通过。

## BUG-027

编号：BUG-027

级别：P2

状态：VERIFIED

问题：`hcl_list_projects` 暴露 cursor，但旧 Tool 没有把 cursor 传给 repository，无法翻页。

复现步骤：以小 page size 查询第二页。

预期：返回 cursor 可直接用于下一次调用，且参数有界。

实际：cursor 已接入 repository，并有多页功能测试。

根因：Tool Schema 与 repository 能力接线不完整。

修复：增加有界 cursor 参数并向下传递。

验证证据：project-list 分页集成测试及 745 passed/3 skipped 全量回归通过。

## BUG-028

编号：BUG-028

级别：P1

状态：VERIFIED

问题：旧 CI 没有 85% 核心覆盖率门禁，也未从安装后的 console entry point 验证两种发布制品。

复现步骤：检查 CI coverage 命令和 package job，并在仓库外干净环境安装制品。

预期：完整测试套件进入 active-v0.1 coverage；wheel/sdist 各自独立安装并运行同一 stdio 黑盒套件。

实际：coverage 为 87.38%；两个制品均在 Python 3.12.13 独立环境依据各自包元数据解析 33 个依赖，通过版本、entry point 和 7 个 stdio 场景。

根因：早期 package smoke 只证明源码模块和 wheel 的部分路径可运行。

修复：CI 使用完整 suite + 85% 门禁，`uv build --clear` 后分别安装 wheel/sdist，清除 `PYTHONPATH` 并从临时 cwd 调用生成的可执行文件。

验证证据：本地双制品黑盒验收通过；[CI run 29567692684](https://github.com/FlySun1116/HCL-Lab_mcp/actions/runs/29567692684) 的 Windows clean-artifact job 通过。

## BUG-029

编号：BUG-029

级别：P1

状态：BLOCKED

问题：尚未留下 Claude Desktop 与 Cursor 各自加载当前候选的真实客户端证据。

复现步骤：分别配置两种客户端为本地 `h3c-hcl-mcp.exe`，重启客户端并查看工具列表/调用健康检查。

预期：两者均发现同一组 15 个 Tool，并能完成 `server_health`。

实际：官方 MCP SDK 黑盒通过，Claude Code 2.1.211 隔离临时 profile 已报告 `Connected`；Cursor 3.11.25 隔离 CLI 在创建 profile/MCP 连接前因自身 Windows `MachineGuid` 查询失败退出且无残留，Claude Desktop 与 Cursor GUI 仍没有可审计运行记录。

根因：客户端安装/运行状态属于用户桌面外部环境，自动化测试不能证明具体 UI 已配置。

修复：维护者在发布前按 README 示例各执行一次，只记录版本、Tool 名称和脱敏结果。

验证证据：待补；不把官方 SDK 测试冒充具体客户端 UI 证据。

## BUG-030

编号：BUG-030

级别：P1

状态：OPEN

问题：远端 GitHub Actions 证据和 `main` required checks/branch protection 状态需要验证。

复现步骤：推送 feature 分支并创建 PR，观察 quality/contract/full Windows+Ubuntu/package/security checks；检查 main 规则。

预期：所有 jobs 通过且 required checks 阻止未通过的合并。

实际：[Draft PR #4](https://github.com/FlySun1116/HCL-Lab_mcp/pull/4) 的 [CI run 29567692684](https://github.com/FlySun1116/HCL-Lab_mcp/actions/runs/29567692684) 六个 job 全部通过；GitHub API 对 `main` protection 查询返回 404 `Branch not protected`。

根因：远端 workflow 的初次失败由 BUG-036 修复；仓库治理仍未给 `main` 配置保护规则。

修复：CI 代码部分已完成；维护者需明确授权后启用 `main` branch protection，并选择 required checks。

验证证据：PR 与 CI 链接见上；`gh api repos/FlySun1116/HCL-Lab_mcp/branches/main/protection` 返回 404 `Branch not protected`。

## BUG-031

编号：BUG-031

级别：P1

状态：VERIFIED

问题：CI 使用可变 major tag 和旧 Node 20 Action；其中 gitleaks v2 将于 2026-09-16 在 GitHub-hosted runner 停止工作。

复现步骤：检查 workflow 的 `uses:` 引用，并与各 Action 官方最新 release 和 runtime 要求比较。

预期：使用支持 Node 24 的当前版本，且供应链引用固定到审核过的完整 commit SHA。

实际：checkout v7.0.0、setup-uv v8.3.2、upload-artifact v7.0.1、gitleaks v3.0.0 均已按完整 SHA 固定。

根因：早期 CI 使用创建仓库时的 major tag，Dependabot 分支尚未合并且远端 main 落后本地候选。

修复：依据官方 release 与远端 Dependabot 证据升级四个 Action；添加静态检查确保所有 `uses:` 引用都是 40 位 SHA。

验证证据：CI YAML 和全部 Action SHA 静态校验通过；[CI run 29567692684](https://github.com/FlySun1116/HCL-Lab_mcp/actions/runs/29567692684) 六项远端 runner 全部通过。

## BUG-032

编号：BUG-032

级别：P0

状态：VERIFIED

问题：旧 sdist 会把构建机未跟踪的 `.claude/settings.local.json` 打入公开源码包，存在本地设置泄漏和不可复现构建风险。

复现步骤：在仓库存在本地 Claude 设置时构建 sdist，枚举 tar archive members。

预期：发布制品只包含项目所需源码、文档、许可证和审计 schema，不包含任何本地 Agent 状态、凭据或专有资产。

实际：Hatch 显式排除 `.claude`、`.codex`、`.agents`、缓存、虚拟环境和构建目录；最终 sdist 不含本地 Agent 状态。

根因：早期只依赖 Git 跟踪状态和用户全局 ignore，没有为 sdist 建立显式成员策略。

修复：增加仓库级 ignore、Hatch exclude 和 `scripts/check_distribution.py`，检查路径、链接、敏感名称/扩展、大小及必需文件。

验证证据：wheel/sdist 内容策略通过；检查器报告 wheel 77 members、sdist 174 members，且 LICENSE、NOTICE、`schema.sql` 完整。

## BUG-033

编号：BUG-033

级别：P1

状态：VERIFIED

问题：Comware `key-string`、WEP key、WLAN/IPsec `preshared-key`/`pre-shared-key` 语法可绕过旧脱敏规则。

复现步骤：向完整与快速脱敏路径输入上述 plain/simple/cipher、大小写和多空格变体，并检查 MCP 最终结果。

预期：秘密值不能出现在设备结果、结构化内容、日志或审计通道。

实际：规则按敏感命令整行脱敏，完整与快速路径均不保留秘密值。

根因：旧规则只覆盖常见 password/shared-key token，没有覆盖这些 Comware 特有语法。

修复：扩展顺序敏感的凭据模式，并增加完整/快速路径对称测试。

验证证据：新增语法聚焦测试及 745 passed/3 skipped 全量回归通过。

## BUG-034

编号：BUG-034

级别：P2

状态：VERIFIED

问题：旧 console adapter 未在 transport 边界再次拒绝非 loopback/非 Telnet endpoint，IAC 过滤假设协商序列位于同一 TCP chunk，持久会话策略和 Server 退出清理也未完整接线。

复现步骤：构造非 loopback 或 SSH endpoint、分片 IAC 序列、超过全局连接上限/空闲时间/命令次数的会话，并触发 Server lifespan 退出。

预期：危险 endpoint 在建连前拒绝；IAC 分片正确过滤；会话按策略回收，退出后无残留 writer。

实际：配置与 adapter 双边界强制 console loopback，IAC filter 跨 chunk 保持状态；SessionManager 落实 reservation、空闲/命令回收，lifespan 调用 `close_all()`。

根因：早期约束只存在于 runtime discovery，传输和 composition root 没有完整执行现有 policy 设置。

修复：增加 endpoint 验证、增量 IAC 状态机、连接 reservation、会话计数/时间戳和 lifespan 清理。

验证证据：console/session/server 聚焦测试及 745 passed/3 skipped 严格 warning 全量回归通过。

## BUG-035

编号：BUG-035

级别：P2

状态：VERIFIED

问题：审计持久化异常被吞掉后 Tool 仍可能返回成功，且多个公共字符串没有长度上限，超长未知 Tool 名可放大日志。

复现步骤：注入始终失败的 AuditSink，调用成功、领域错误、Schema、未知 Tool 和超时路径；提交超长 command/project/tool/filter 字段。

预期：审计开启时不能产生未审计成功；超长输入在设备连接前拒绝；日志不回显完整攻击字符串。

实际：审计失败统一转换为有界 `INTERNAL_ERROR`/`AUDIT_UNAVAILABLE`；公共 Schema 均有 max length，日志参数最多保留 1024 字符。

根因：审计中间件采用可用性优先的异常吞噬策略，Schema 和日志边界未统一设计。

修复：审计路径 fail closed；统一有界字段并在 logging adapter 截断客户端值。

验证证据：审计失败、Schema 上限、输出预算和日志截断测试及 745 passed/3 skipped 全量回归通过。

## BUG-036

编号：BUG-036

级别：P1

状态：VERIFIED

问题：Draft PR 首次 CI 在 Linux mypy 和 gitleaks secret scan 两项失败。

复现步骤：查看 PR #4 的首次 [CI run 29567126042](https://github.com/FlySun1116/HCL-Lab_mcp/actions/runs/29567126042)：Linux typeshed 不暴露 `winreg.QueryValueEx`，gitleaks-action v3 因未传 `GITHUB_TOKEN` 在扫描前退出。

预期：同一源码在 Windows/Linux 类型平台均通过；secret scan 实际执行并报告扫描结果。

实际：修复后 [CI run 29567692684](https://github.com/FlySun1116/HCL-Lab_mcp/actions/runs/29567692684) 六个 job 全部通过。

根因：Windows 专用 API 在 Linux typeshed 下的可见性不同；gitleaks-action v3 增加了显式 GitHub Token 要求。

修复：通过受控动态属性读取 Windows registry API 并处理 `KeyError`；按 gitleaks-action v3 官方说明给扫描步骤传入仓库 `GITHUB_TOKEN`。

验证证据：历史默认和 `--platform linux` mypy 均通过；当前默认 mypy 73 个源/脚本文件、745 passed/3 skipped 严格 warning 回归通过，旧远端 CI 六项全绿。

## BUG-037

编号：BUG-037

级别：P1

状态：VERIFIED

问题：`project.json`、`.net` 及其引用路径曾缺少统一大小上限和完整的项目根/symlink 边界。

复现步骤：构造超大项目文件、绝对/UNC/盘符/`..` 引用或指向项目根外的 symlink/junction。

预期：在解析前有界读取并拒绝所有项目根逃逸，错误不泄漏绝对路径。

实际：`project.json` 限制 16 MiB、`.net` 限制 64 MiB；引用按 realpath 验证并拒绝逃逸。

建议：保持当前边界；未来改变限额须有真实兼容性证据。

## BUG-038

编号：BUG-038

级别：P1

状态：VERIFIED

问题：旧制品检查主要依靠危险扩展 denylist，未知类型仍可能进入 wheel/sdist；仓库本身也缺少 tracked-file allowlist。

复现步骤：向 archive 或 Git inventory 注入未列入 denylist 的二进制、链接、大小写冲突、秘密文件或非 fixture `.net/.cfg`。

预期：只允许明确审核过的源码/文档/配置类型和位置，未知成员默认拒绝。

实际：制品检查改为 wheel/sdist allowlist；仓库检查基于 `git ls-files -z`，拒绝危险路径、资产、链接、大小和 casefold 冲突。

建议：新增公开文件类型时同步更新策略和纯函数测试，不放宽为通用扩展。

## BUG-039

编号：BUG-039

级别：P1

状态：VERIFIED（代码）/HUMAN-REQUIRED（Dependency Graph）

问题：仓库此前没有独立依赖漏洞、许可证、CodeQL、文档、SBOM/provenance 和可信发布门禁。

复现步骤：查看旧 `.github/workflows/`，只有基础 CI/secret scan，无法生成受证明的 release assets。

预期：PR 运行依赖/许可证/CodeQL/docs/repository gates；发布只从 main 的验证签名 tag 进入受保护 PyPI environment，并生成 SBOM、校验和和 provenance。

实际：新增 `security.yml`、`docs.yml`、`release.yml`，所有第三方 Action 固定完整 SHA；本地与远端依赖、许可证、文档、构建、CodeQL 和 SBOM 路径通过。Dependency Review 因仓库 Dependency Graph disabled 而 fail closed。

建议：推送后要求新 workflows 全绿，再由维护者配置 required checks 与 release environment。

## BUG-040

编号：BUG-040

级别：P2

状态：VERIFIED

问题：v0.1 配置模型曾接受 `ssh` 或混合 transport，实际实现却只有 `console_telnet`，造成虚假能力。

复现步骤：设置 `device.preferred_transports=["ssh"]` 或混合列表并加载配置。

预期：v0.1 只接受且必须等于 `["console_telnet"]`。

实际：空列表、SSH、NETCONF、混合与重复项均在启动前拒绝。

建议：SSH 只在 v0.2 adapter、契约和安全测试完成后通过 ADR 开放。

## BUG-041

编号：BUG-041

级别：P2

状态：VERIFIED

问题：`audit.retention_days` 曾仅存在于配置，SQLite 不清理过期事件；异常文本和 traceback 也可能无界进入日志。

复现步骤：插入超过 retention window 的事件，或记录携带长秘密尾部的异常。

预期：过期事件按 UTC 清理；异常在 human/JSON 日志中先脱敏再按字节边界截断。

实际：store 初始化和 append 后清理过期事件；异常文本/traceback 上限 1024 字符并经过敏感信息脱敏。

建议：未来若需要长期合规归档，使用独立外部 AuditSink，不取消本地保留期。

## BUG-042

编号：BUG-042

级别：P2

状态：VERIFIED

问题：旧 server 在注册后直接修改 FastMCP `_tool_manager`，依赖范围又宽至 `<2`，SDK patch/minor 漂移可能静默破坏协议路径。

复现步骤：搜索源码中的 `_tool_manager`/`_mcp_server` 并检查 MCP 依赖上界。

预期：Tool 注册/调用/Schema 走公开 API；不可避免的 version 私有桥单点隔离并 fail fast。

实际：`HCLFastMCP` 使用公开 `add_tool`、`call_tool`、`list_tools`；源码仅 `sdk_compat.py` 保留 `_mcp_server`，依赖限制 `>=1.28.1,<1.29`，官方 stdio 7 场景和 63 个集成测试通过。

建议：任何 MCP SDK 升级先重跑完整协议矩阵并更新验证版本，不直接放宽上界。

## BUG-043

编号：BUG-043

级别：P2

状态：OPEN / MAINTAINER-DECISION

问题：公开 Tool input schema 当前没有统一声明 `additionalProperties: false`，客户端可发送未知字段后由运行时验证拒绝，但 Schema 本身不够明确。

复现步骤：检查 `tools/list` 的 15 个 `inputSchema` 并提交未知字段。

预期：由维护者决定是否把未知字段拒绝固化为公开 Schema 契约，并评估 Claude/Cursor 兼容性。

实际：本轮未修改公共 Tool Schema；运行时仍返回稳定 `INVALID_ARGUMENT`。

建议：作为独立 ADR/契约 PR 处理，不能夹带在安全修复中。

## BUG-044

编号：BUG-044

级别：P1

状态：HUMAN-REQUIRED

问题：GitHub Dependency Graph、Private Vulnerability Reporting 当前 disabled，`main` 未保护，`pypi` environment/Trusted Publisher/显式发布开关尚未配置。

复现步骤：运行 Dependency Review，查询 private vulnerability reporting 和 main protection；检查仓库 environments/PyPI Publisher。

预期：公开发布前启用 Dependency Graph、私密报告入口、required checks、受保护发布环境和 OIDC Trusted Publisher。

实际：代码与 workflow 已 fail closed，但仓库侧设置尚未执行。

建议：由维护者确认后统一配置；这会改变仓库治理和发布权限，Agent 不得自行启用。

## BUG-045

编号：BUG-045

级别：P1

状态：VERIFIED

问题：真实 stdio 启动时，AuditStore 曾把审计数据库绝对路径写入 stderr；SecretProvider 和异常日志也可能记录本机路径或原始异常文本。

复现步骤：以默认配置启动 Server，观察 `Audit store initialized at ...`；向日志参数/异常传入 Windows、UNC、`/home`、`/etc`、`/usr/local` 与自定义 POSIX 绝对路径。

预期：stderr 可用于诊断但不得暴露用户名、安装目录、项目/审计/Secret 文件位置；凭据和异常仍需有界，HTTPS URL 保持可读。

实际：启动日志只报告 AuditStore 已初始化；Secret 文件日志不含位置；统一过滤器输出 `<local-path>`，覆盖 Windows、UNC 和任意 POSIX 绝对路径，HTTPS URL 不变。

建议：保持路径脱敏为 logging adapter 的强制边界；新增 logger 时不得绕过统一 handler 或拼接原始异常。

验证证据：真实官方 stdio Client 重启后 stderr 不含审计库路径；human/JSON、PathLike、异常、`/etc`、`/usr/local`、任意根目录、file URI、UNC、诊断后缀及 URL 回归进入 745 passed/3 skipped 全量测试。

# 优化建议

1. 把 Python 3.12 wheel/sdist clean-artifact + 官方 stdio 7 场景设为 Windows CI required check。
2. 为真实 HCL 自托管 runner 记录脱敏的 project-bound/console/prompt/command 阶段，不上传厂商资产。
3. 在 `v0.2` 前决定 Tool alias；若不增加，给外部验收文档提供明确映射表。
4. 将 `h3c_diff_config` 和 Job placeholder 在 Tool 描述中持续标为不可用，避免 Client 误选。
5. 发布前生成 SBOM、校验和、干净安装记录，并逐字执行 README/三种客户端示例。
6. 将真实正向 HCL 测试与设备写测试永久分离；v0.1 CI/验收不得执行配置、save、reboot。

# 优先级

| 优先级 | 活跃项 | 发布要求 |
|---|---|---|
| P0 | BUG-001、BUG-017 | 真实命令成功并完成公开发布授权后才能宣布外部可安装；发布动作本身需维护者确认 |
| P1 | BUG-029、BUG-030、BUG-039、BUG-044（外部/远端门禁） | Dependency Graph 启用后仍需客户端证据、`main` 保护、私密报告和受保护发布环境；BUG-045 已验证 |
| P2 | BUG-005、BUG-043 | Tool alias 与 `additionalProperties` 都是公共契约决策，不夹带修改 |

# 交给开发 Agent 的修复清单

1. **无待修复的 P1 本地代码缺陷**：BUG-018～028、BUG-031～042、BUG-045 已在当前候选验证；远端仅 Dependency Review 等待仓库 Dependency Graph。
2. **真实 HCL 正向测试**：等待维护者启动设备，只执行两条 display 命令并记录脱敏结果。
3. **发布决策**：候选分支和 Draft PR #4 已通过 CI；merge/tag/Release/PyPI 仍需维护者明确授权。
4. **真实客户端与仓库治理**：按 BUG-029/030/044 补齐 Claude Desktop、Cursor、Dependency Graph、`main` 保护、私密报告和受保护发布环境。
5. **后续契约决策**：Tool alias 与 `additionalProperties`（BUG-043）分别单独评审，不在 beta.2 安全候选中临时改变公共 Tool Schema。
