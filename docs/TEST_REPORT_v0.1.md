# HCL-Lab_mcp v0.1 测试报告

> 测试对象：`0.1.0-beta.2` 本地提交候选
> 实现提交：`fb5e758`
> 报告日期：2026-07-16
> 当前结论：**CONDITIONAL GO**（代码与本地制品门禁通过；公开发布仍等待真实运行设备正向验证和维护者授权）

本报告替代 beta.1 的旧失败快照。所有“已修复”结论均以当前源码、自动化测试或本机只读观察为依据；没有把未运行设备上的命令伪造为成功。仓库尚未发布 PyPI、tag 或 GitHub Release。

# 测试环境

| 项目 | 环境 |
|---|---|
| 操作系统 | Windows，本机 HCL 环境 |
| HCL | H3C Cloud Lab 5.10.3 |
| 项目主运行时 | Python 3.14.5（冻结候选全量测试） |
| 发布目标运行时 | Python 3.12.13（干净 beta.2 wheel 已验证） |
| Python 包版本 | `0.1.0-beta.2`（PEP 440：`0.1.0b2`） |
| MCP SDK | 官方 MCP Python SDK v1 稳定线（锁定 `<2`） |
| MCP transport | `stdio` |
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
| beta.2 wheel/sdist | 通过 | `uv build` 生成 `0.1.0b2` wheel/sdist；wheel 含 75 项及审计 `schema.sql` |
| Python 3.12 干净安装 | 通过 | Python 3.12.13 从 wheel 安装 `0.1.0b2`；官方 stdio 7 passed in 7.43s |
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
| 未知 Tool | 通过 | 稳定 `INVALID_ARGUMENT`、带 request_id，并写入同一审计事件 |
| 全局 Tool 超时 | 通过 | `server.max_tool_seconds` 在 ToolManager 边界返回稳定 `TIMEOUT` |

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
| `h3c_ping` | 条件可用 | 参数边界和命令策略通过；真实运行设备正向路径待测 |
| `h3c_trace_route` | 条件可用 | 参数边界和命令策略通过；真实运行设备正向路径待测 |
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
| 目标项目 runtime | 通过（负向） | 官方 ClientSession：6 个设备、running_count=0、2 个 H3C candidate 均不可操作 |
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
| `uv run --locked ruff format --check .` | 通过：93 个文件 |
| `uv run --locked mypy src` | 通过：68 个源文件 |
| `uv run --locked pytest` | 通过：**489 passed in 19.34s**，Python 3.14.5 |
| `uv build` | 通过：`0.1.0b2` wheel/sdist |
| Python 3.12 wheel stdio | 通过：**7 passed in 7.43s** |
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
19. beta.2 wheel/sdist、Python 3.12.13 干净安装和 7 个官方 stdio 场景全部通过。

# 失败项

1. 真实运行设备的 `display version` 和 `display ip interface brief` 正向链路尚未验证。
2. PyPI、tag 和 GitHub Release 尚未发布；公共 `uvx` 安装不可用。
3. `h3c_diff_config` 和 Job 生产用例仍是占位能力。
4. 短 Tool alias 尚未决策/注册，但 namespaced Tool 的 MCP 可发现性已通过。

# Bug列表

## BUG-001

编号：BUG-001

级别：P0

状态：OPEN

问题：公开 package registry 没有 beta.2，外部用户不能按 `uvx h3c-hcl-mcp` 安装。

复现步骤：在未安装本地源码/本地 wheel 的干净环境尝试从 PyPI 启动包。

预期：发布授权后能安装固定版本并返回一致的 Server 版本。

实际：当前没有 beta.2 PyPI 包、tag 或 GitHub Release。

根因：候选尚未完成最终质量门禁和维护者发布授权。

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

验证证据：冻结候选 489 项全量通过；Python 3.12.13 干净 wheel 的 YAML/JSON/CLI/env stdio 场景进入 7 passed。

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

实际：最终已格式化；`ruff format --check` 报告 93 个文件全部合格。

根因：多个 beta.2 修复并行集成时尚未执行最终格式化和冻结回归。

修复：Team Lead 运行 formatter，审查 diff，并重跑 ruff check/format、mypy、pytest、build 和 clean-wheel stdio。

验证证据：Ruff check/format 通过、mypy 68 个源文件通过、489 passed、beta.2 build 通过、Python 3.12 wheel stdio 7 passed。

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

验证证据：策略单元测试及 489 项冻结候选全量回归通过。

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

验证证据：Telnet fake server 清理、重连、迟到输出和错误边界测试进入 489 项全量通过。

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

验证证据：官方内存协议、SQLite、拓扑和全局超时回归进入 489 项全量通过。

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

验证证据：30 项 redaction 测试及 489 项冻结候选全量回归通过。

# 优化建议

1. 把 Python 3.12 clean-wheel + 官方 stdio 7 场景设为 Windows CI required check。
2. 为真实 HCL 自托管 runner 记录脱敏的 project-bound/console/prompt/command 阶段，不上传厂商资产。
3. 在 `v0.2` 前决定 Tool alias；若不增加，给外部验收文档提供明确映射表。
4. 将 `h3c_diff_config` 和 Job placeholder 在 Tool 描述中持续标为不可用，避免 Client 误选。
5. 发布前生成 SBOM、校验和、干净安装记录，并逐字执行 README/三种客户端示例。
6. 将真实正向 HCL 测试与设备写测试永久分离；v0.1 CI/验收不得执行配置、save、reboot。

# 优先级

| 优先级 | 活跃项 | 发布要求 |
|---|---|---|
| P0 | BUG-001、BUG-017 | 真实命令成功并完成公开发布授权后才能宣布外部可安装；发布动作本身需维护者确认 |
| P1 | 无未关闭代码缺陷 | BUG-018～022 已在冻结候选验证 |
| P2 | BUG-005 | 维护者决策；不阻止 namespaced Tool 的技术验证 |

# 交给开发 Agent 的修复清单

1. **无待修复的 P1 代码缺陷**：beta.2 实现提交、最终 diff 复核和本地制品验证均已完成。
2. **真实 HCL 正向测试**：等待维护者启动设备，只执行两条 display 命令并记录脱敏结果。
3. **发布决策**：正向验证通过后申请公开发布授权；未经授权不 push/tag/Release/PyPI。
4. **后续契约决策**：Tool alias 继续单独评审，不在 beta.2 候选中临时增加公共 Tool。
