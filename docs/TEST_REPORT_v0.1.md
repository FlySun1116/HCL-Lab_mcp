# HCL-Lab_mcp v0.1 外部验收测试报告

> 测试日期：2026-07-15  
> 测试角色：外部使用者 / MCP Client / 测试工程师  
> 被测仓库：`FlySun1116/HCL-Lab_mcp`  
> 被测提交：`a0f48fdb42c7ebe84f9b8dc3b82da624b8e61e0d`（`main`，与 `origin/main` 一致）  
> 用户声明版本：`v0.1.0-beta.1`  
> 实际包版本：`0.0.1`  
> 总体结论：**不通过，当前提交不能作为 `v0.1.0-beta.1` 交付给外部用户。**

## 结论摘要

标准 MCP `stdio` 链路本身可用：从本地 wheel 安装后，客户端可以完成 `initialize`、`tools/list` 和 `tools/call`，并发现 19 个 Tool。但是 README 推荐的 PyPI/`uvx` 安装路径不可用，README 的固定版本与包版本不一致，`--config` 参数未被处理；更关键的是，真实 HCL 5.10.3 项目格式无法被解析，运行时设备和控制台端点探测尚未实现。因此 Claude、Cursor 等客户端目前只能连接到 Server，不能真正调用本机 HCL 中的 H3C 设备。

发布判定：**NO-GO**。

- P0 阻断项：3 个。
- P1 重要缺陷：7 个。
- P2 一般缺陷：3 个。
- 源代码未被修改；真实 HCL 设备未被配置或重启。

# 测试环境

| 项目 | 实际环境 |
|---|---|
| 操作系统 | Windows 11，build `10.0.26200`，Asia/Shanghai |
| 仓库分支 | `main`，clean，与 `origin/main` 一致 |
| Git commit | `a0f48fdb42c7ebe84f9b8dc3b82da624b8e61e0d` |
| Git tag | 未发现与当前提交对应的发布 tag |
| Python | CPython `3.13.12`；`uv sync` 还在独立环境验证了 `3.14.5` |
| uv | `0.11.14` |
| MCP Python SDK | `1.28.1` |
| 安装后包元数据 | `h3c-hcl-mcp==0.0.1` |
| HCL | H3C Cloud Lab `5.10.3`，安装目录 `F:\HCL` |
| HCL 运行状态 | `SimwareClient.exe`、`SimwareMultiCC.exe`、`SimwareWrapper.exe` 均在运行 |
| HCL 项目目录 | `C:\Users\Sun-_-\HCL\Projects`，发现 3 个项目目录 |
| 真实测试项目 | `hcl_1e910d518140` |
| MCP Client | 官方 MCP Python SDK `ClientSession` + `stdio_client` |
| 隔离方式 | 临时目录全新 clone；独立 `.pypi-venv`、`.wheel-venv` 和开发 `.venv` |

说明：协议测试使用官方 SDK 模拟 Claude/Cursor 启动子进程的方式，覆盖相同的 `stdio` MCP 链路。由于 README 指定的 PyPI 版本无法解析，未在 Claude Desktop/Cursor GUI 中重复执行一个必然无法启动的配置。

# 测试项目

## 第一阶段：安装、构建和客户端配置

| 编号 | 测试项 | 结果 | 证据 |
|---|---|---|---|
| INS-01 | 从 GitHub 全新 clone | 通过 | clone 成功，HEAD 与 `origin/main` 一致 |
| INS-02 | README：`uvx h3c-hcl-mcp` | 失败 | 包注册表中不存在 `h3c-hcl-mcp` |
| INS-03 | README：`pip install h3c-hcl-mcp` | 失败 | PyPI 解析不到该包 |
| INS-04 | README：`uv pip install -e ".[dev]"` | 失败 | 全新 clone 中没有虚拟环境，uv 提示先执行 `uv venv` |
| INS-05 | `uv build` 构建 wheel/sdist | 通过 | 生成 `h3c_hcl_mcp-0.0.1-py3-none-any.whl` 和 sdist |
| INS-06 | 全新 venv 安装本地 wheel | 通过 | 包和依赖安装成功，CLI 入口存在 |
| INS-07 | 启动本地 wheel 的 CLI | 部分通过 | Server 能启动，但输出版本为 `0.0.1` |
| INS-08 | README Claude/Cursor 配置 | 失败 | 配置固定 `h3c-hcl-mcp==0.1.0`，注册表无该版本 |
| INS-09 | `--config config/config.example.yaml` | 失败 | 参数被静默忽略；不存在的 `--definitely-invalid-option` 也能正常启动 |

补充质量门禁：

| 命令 | 结果 |
|---|---|
| `uv sync --extra dev` | 通过 |
| `uv run pytest` | 通过，`349 passed`，耗时约 65 秒 |
| `uv run mypy src` | 通过，64 个源文件无错误 |
| `uv run ruff check .` | 失败，`domain/command.py` 有 1 个 E501 |
| `uv run ruff format --check .` | 失败，3 个文件需要格式化 |

## 第二阶段：MCP 协议

| 编号 | 测试项 | 结果 | 实际结果 |
|---|---|---|---|
| MCP-01 | `initialize` | 通过 | 协议版本 `2025-11-25`，Server 可建立会话 |
| MCP-02 | Server capability | 通过 | 声明 `tools`、`resources`、`prompts` 能力 |
| MCP-03 | `tools/list` | 通过 | 返回 19 个工具及 JSON Schema |
| MCP-04 | `tools/call server_health` | 通过 | 同时返回 text 和 `structuredContent` |
| MCP-05 | 调用不存在的 Tool | 通过 | MCP 返回 `isError=true` 和 unknown tool 信息 |
| MCP-06 | 业务错误映射 | 失败 | `ToolResult.ok=false` 时 MCP 层仍返回 `isError=false` |
| MCP-07 | `serverInfo.version` | 失败 | 返回 SDK 版本 `1.28.1`，不是应用版本 |

Server 可以被 MCP Client 发现，但“能连接”不等于“能操作 HCL”。

## 第三阶段：全部 Tool 功能

`tools/list` 实际返回以下 19 个 Tool：

| Tool | 参数设计 | 调用结果 | 功能判定 |
|---|---|---|---|
| `server_health` | 合理 | `ok=true` | 通过；但报告应用版本 `0.0.1` |
| `hcl_list_projects` | 基本合理 | 合成项目成功；真实环境返回空列表 | 失败（真实 HCL 不可用） |
| `hcl_get_topology` | 基本合理 | 合成项目成功；真实项目 `PROJECT_DAMAGED` | 失败 |
| `hcl_get_runtime` | 基本合理 | 对真实/不存在项目均可能返回成功空列表 | 失败，未验证项目且未探测运行时 |
| `h3c_list_devices` | 基本合理 | 合成拓扑可列出；真实项目解析失败 | 失败 |
| `h3c_get_facts` | 合理 | `DEVICE_NOT_FOUND` | 失败，无法到达设备 |
| `h3c_run_display` | `timeout` 缺少 Schema 范围约束 | `DEVICE_NOT_FOUND` | 失败，无法执行命令 |
| `h3c_get_config` | `source` 未使用 enum Schema | 有效 source 无设备；非法 source 退化成 `INTERNAL_ERROR` | 失败 |
| `h3c_get_interfaces` | 合理 | `DEVICE_NOT_FOUND` | 失败 |
| `h3c_ping` | `count` 无 Schema 范围约束，越界值被静默裁剪 | `DEVICE_NOT_FOUND` | 失败 |
| `h3c_trace_route` | `max_hops` 无 Schema 范围约束，越界值被静默裁剪 | `DEVICE_NOT_FOUND` | 失败 |
| `h3c_diff_config` | 可理解 | 返回 `ok=true` 的“未实现”占位结果 | 失败，结果语义错误 |
| `h3c_plan_change` | 表面合理 | 返回 `ok=true` 的“未实现”占位结果 | 失败，结果语义错误 |
| `h3c_approve_change` | 表面合理 | 返回 `ok=true` 的“未实现”占位结果 | 失败，结果语义错误 |
| `h3c_apply_change` | 表面合理 | 返回 `ok=true` 的“未实现”占位结果 | 失败，结果语义错误 |
| `h3c_verify_change` | 表面合理 | 返回 `ok=true` 的“未实现”占位结果 | 失败，结果语义错误 |
| `job_get` | 合理 | 缺失 job 返回结构化 `INVALID_ARGUMENT` | 负向路径通过；无真实 job 可验证 |
| `job_cancel` | 合理 | 缺失 job 返回结构化 `INVALID_ARGUMENT` | 负向路径通过；无真实 job 可验证 |
| `audit_query` | 合理 | 可调用，但多次工具调用后数据库仍为 0 条 | 失败（审计未接入调用链） |

### 用户要求的五个 Tool 名称

用户测试清单中的五个名称均未注册。使用这些精确名称调用时，MCP 返回 unknown tool：

| 要求名称 | 当前可能对应 | 精确名称是否可调用 |
|---|---|---|
| `list_devices` | `h3c_list_devices` | 否 |
| `execute_command` | `h3c_run_display` | 否 |
| `configure_device` | 无可用实现；只有占位 change workflow | 否 |
| `get_device_status` | `hcl_get_runtime` / `h3c_get_facts` | 否 |
| `ping_test` | `h3c_ping` | 否 |

如果 namespaced 名称是正式 API，应在 README 明确给出迁移映射；如果上述五个名称已经对外承诺，应提供兼容 alias 并标注弃用周期。

### 返回格式评价

成功结果的 `ToolResult` 结构统一，包含 `ok`、`request_id`、`target`、`changed`、`data`、`warnings`、`duration_ms` 和 `truncated`，同时提供 MCP text 与 `structuredContent`，便于 Agent 读取。

主要问题：

1. 业务失败仍使用 MCP `isError=false`，客户端需要二次理解 `structuredContent.ok`。
2. 未实现功能返回 `ok=true`，Agent 会误判任务已完成。
3. 多个设备状态错误被错误映射为 `DEVICE_NOT_FOUND` 或 `INTERNAL_ERROR`。
4. `hcl_list_projects` 静默跳过损坏/不兼容项目，用户看到的是“没有项目”，无法采取修复行动。
5. 参数说明写了范围，但 JSON Schema 没有 `minimum`/`maximum` 或 enum，越界参数被静默修改。

## 第四阶段：真实 HCL 5.10.3

真实环境满足测试前提：HCL 进程正在运行，`C:\Users\Sun-_-\HCL\Projects` 下存在三个项目目录。选择 `hcl_1e910d518140` 验证。

| 测试 | 结果 | 实际 |
|---|---|---|
| 发现 HCL 项目 | 失败 | `hcl_list_projects` 返回 `count=0` |
| 读取真实拓扑 | 失败 | `PROJECT_DAMAGED: project.json missing required field 'id'` |
| 发现设备运行状态 | 失败 | `ok=true`，但 devices 为空，running_count=0 |
| 列出设备 | 失败 | `PROJECT_DAMAGED` |
| `display version` | 失败 | `DEVICE_NOT_FOUND` |
| `display ip interface brief` | 失败 | `DEVICE_NOT_FOUND` |
| 配置命令 | 未执行 | 无可用写 Tool；`h3c_plan_change` 只返回 `ok=true` 占位消息 |

根因证据：真实 HCL 5.10.3 `project.json` 顶层字段为 `projectInfo` 和 `deviceInfoList`；当前解析器强制要求自定义的顶层 `id`、`name`、`version`、`devices`。仓库合成 fixture 使用后者，因此 349 个自动化测试全部通过仍未覆盖真实 HCL 文件格式。

第二个阻断点是 `HCLRuntimeDiscovery` 的模块注释明确写明 v0.1 只支持 synthetic/manual state，真实进程检查、日志观察和 loopback 端口探测尚未实现。Composition Root 没有向该 adapter 注入真实设备状态，因此任何设备命令都会在连接 Telnet 前失败。

# 成功项

1. 仓库可以全新 clone，本地 `uv build` 能生成 wheel 和 sdist。
2. 本地 wheel 可以安装到干净 Python 3.13 venv，CLI 入口存在。
3. `stdio` Server 可以正常启动和关闭。
4. 官方 MCP Client 可以完成 `initialize`、`tools/list`、`tools/call`。
5. 19 个 Tool 都有可发现的名称、描述和输入 Schema。
6. 成功结果包含 `structuredContent`，基础 envelope 一致。
7. 调用不存在的 Tool 时，MCP 协议层能返回标准错误。
8. 合成项目的项目/拓扑解析路径可工作。
9. 命令策略包含 display allowlist、危险关键字和注入字符拦截逻辑。
10. 自动化测试 `349 passed`，mypy 通过。

# 失败项

1. 外部用户无法按 README 从 PyPI/`uvx` 安装。
2. 版本声明、包元数据、README、MCP initialize 和用户声明互相矛盾。
3. README 的 Claude/Cursor 固定版本配置无法解析。
4. `--config` 和未知 CLI 参数均被静默忽略。
5. 真实 HCL 5.10.3 项目格式无法解析。
6. 无真实运行时/console endpoint 探测，所有设备命令不可用。
7. 用户要求的五个 Tool 名称均不存在。
8. 五个未实现/占位工具返回 `ok=true`。
9. 错误枚举引用错误导致本应明确的错误退化为 `INTERNAL_ERROR`。
10. 业务失败没有设置 MCP `isError=true`。
11. 审计数据库成功创建，但实测工具调用记录数为 0。
12. lint 与 format 质量门禁未通过。

# Bug列表

## BUG-001

编号：BUG-001  
优先级：P0  
问题：公开安装和版本发布不可用，仓库不具备 `v0.1.0-beta.1` 可安装制品。

复现步骤：

1. 在干净 Windows 环境执行 `uvx h3c-hcl-mcp`。
2. 或执行 `pip install h3c-hcl-mcp`。
3. 检查 `pyproject.toml`、README、CHANGELOG、Git tag 和本地 wheel 元数据。

预期：README 指定版本可从公开源安装，版本号和 tag 一致。

实际：包注册表找不到该包；README 客户端配置固定 `0.1.0`；wheel、启动日志和包元数据均为 `0.0.1`；未发现 beta tag。

建议：先决定真实发布版本；统一单一版本源；在 TestPyPI/PyPI 和 GitHub Release 做安装 smoke；只有制品、tag、README 和 MCP serverInfo 一致后再标记 beta。

## BUG-002

编号：BUG-002  
优先级：P0  
问题：真实 HCL 5.10.3 `project.json` 格式不兼容，核心项目发现失败。

复现步骤：

1. 启动本机 HCL 5.10.3 并打开真实项目。
2. 将 `H3C_CLOUD_LAB_PROJECTS` 指向 HCL Projects 目录。
3. 调用 `hcl_list_projects` 和 `hcl_get_topology`。

预期：列出项目并解析设备和链路。

实际：列表为 0；指定项目返回 `PROJECT_DAMAGED: missing required field 'id'`。真实文件顶层是 `projectInfo/deviceInfoList`，当前实现和 fixture 使用 `id/devices`。

建议：建立经过脱敏的 HCL 5.10.3 fixture；实现真实 schema 的版本化 parser；从 `.net` 与 `project.json` 交叉解析；列表中不得静默吞掉不兼容项目，应返回 warnings/diagnostics。

## BUG-003

编号：BUG-003  
优先级：P0  
问题：真实 HCL 运行时和 console endpoint 探测未实现，所有设备 Tool 不可用。

复现步骤：

1. 保持 HCL 与 Simware 相关进程运行。
2. 调用 `hcl_get_runtime`、`h3c_run_display` 或 `h3c_ping`。

预期：发现运行设备及 loopback console endpoint，并建立只读会话。

实际：runtime 返回成功空列表；设备调用返回 `DEVICE_NOT_FOUND`。当前 adapter 仅接受程序内手工注入的 synthetic state。

建议：按设计实现进程观察、HCL 日志解析、候选 loopback 端口探测与 prompt 身份校验；将真实 discovery adapter 接入 Composition Root；加入 Windows + HCL 自托管端到端测试。

## BUG-004

编号：BUG-004  
优先级：P1  
问题：README 和示例使用的 `--config` 没有实现，未知参数也被静默接受。

复现步骤：

1. 启动 `h3c-hcl-mcp --definitely-invalid-option`。
2. 启动 `h3c-hcl-mcp --config config/config.example.yaml`。
3. 分别执行 MCP initialize。

预期：未知参数导致明确退出；配置文件被加载并影响项目目录、策略、超时和审计位置。

实际：两次都正常启动并返回 19 个 Tool；CLI 没有参数解析，YAML 配置未进入 Composition Root。

建议：实现 CLI parser 和 Settings loader；按“CLI > env > YAML > 用户配置 > 默认值”合并；启动时只输出脱敏后的有效配置摘要；补充配置契约测试。

## BUG-005

编号：BUG-005  
优先级：P1  
问题：外部测试契约中的五个 Tool 名称均未注册。

复现步骤：依次调用 `list_devices`、`execute_command`、`configure_device`、`get_device_status`、`ping_test`。

预期：工具可调用，或 README 明确给出稳定名称和迁移映射。

实际：全部返回 unknown tool。当前只有 namespaced 近似工具，且没有可工作的配置工具。

建议：由维护者冻结 v0.1 公共 Tool 契约。若 namespaced 名称是正式接口，更新所有用户文档并提供 alias/迁移期；不要让不同提示词和 README 使用两套名称。

## BUG-006

编号：BUG-006  
优先级：P1  
问题：未实现工具被 `tools/list` 公开并返回 `ok=true`。

复现步骤：调用 `h3c_diff_config`、`h3c_plan_change`、`h3c_approve_change`、`h3c_apply_change`、`h3c_verify_change`。

预期：beta 不公开未实现能力；或返回 `ok=false`、`NOT_IMPLEMENTED` 和 MCP `isError=true`。

实际：五个工具都返回 `ok=true` 和“planned for v0.2.0”，Agent 容易误判操作成功。

建议：v0.1 从注册表移除占位工具；必须保留时统一返回稳定 `NOT_IMPLEMENTED` 错误，且绝不能声称配置计划/应用成功。

## BUG-007

编号：BUG-007  
优先级：P1  
问题：错误分支错误引用 `DomainError` 类属性，导致明确错误退化为 `INTERNAL_ERROR`。

复现步骤：调用 `h3c_get_config` 并传入非法 `source`；或让 runtime 返回 stopped/无 endpoint 状态。

预期：分别返回 `INVALID_ARGUMENT`、`DEVICE_NOT_RUNNING`、`CONSOLE_UNAVAILABLE`。

实际：代码引用不存在的 `DomainError.INVALID_ARGUMENT.code`、`DomainError.DEVICE_NOT_RUNNING.code`、`DomainError.CONSOLE_UNAVAILABLE.code`，触发 `AttributeError` 后映射为 `INTERNAL_ERROR`。

建议：使用 `ErrorCode` enum；为三个分支增加 MCP 端到端负向测试，断言稳定 error code 和可执行建议。

## BUG-008

编号：BUG-008  
优先级：P1  
问题：Tool 业务失败时 MCP `isError` 仍为 `false`。

复现步骤：调用会返回 `PROJECT_DAMAGED` 或 `DEVICE_NOT_FOUND` 的工具并检查完整 `CallToolResult`。

预期：失败结果有结构化 error，同时 MCP `isError=true`，便于 Claude/Cursor 可靠识别失败。

实际：`structuredContent.ok=false`，但顶层 `isError=false`。

建议：统一 MCP error adapter；成功只返回 success result，领域错误转换为 `isError=true` 的工具错误，同时保留稳定 structured error payload。

## BUG-009

编号：BUG-009  
优先级：P1  
问题：审计存储创建成功，但 MCP Tool 调用没有写入审计事件。

复现步骤：执行多次成功和失败的 Tool 调用，然后调用 `audit_query` 或统计 `audit_events`。

预期：每次调用至少记录 request_id、tool、target、结果、耗时和调用者；敏感输出按策略脱敏。

实际：数据库文件存在，`audit_events` 记录数为 0。

建议：在统一 MCP middleware/decorator 接入审计，覆盖成功、领域错误、协议校验错误和取消；增加不可篡改/并发/脱敏测试。

## BUG-010

编号：BUG-010  
优先级：P1  
问题：MCP `initialize.serverInfo.version` 暴露 SDK 版本，不是应用版本。

复现步骤：初始化 MCP 会话并检查 `serverInfo.version`。

预期：返回当前应用发布版本，例如 `0.1.0-beta.1`。

实际：返回 `1.28.1`（MCP SDK 版本），而 health 和包元数据为 `0.0.1`。

建议：从单一版本源显式传给 FastMCP；增加 initialize 契约测试，确保包、health、日志、serverInfo 和 tag 一致。

## BUG-011

编号：BUG-011  
优先级：P2  
问题：README 的开发安装命令在全新 clone 中不可直接执行。

复现步骤：在没有 `.venv` 的全新 clone 中执行 `uv pip install -e ".[dev]"`。

预期：按 README 一次执行即可准备开发环境。

实际：uv 报告没有虚拟环境并要求先执行 `uv venv`。

建议：README 改为 `uv sync --extra dev`，或明确先执行 `uv venv`；CI 加文档命令 smoke test。

## BUG-012

编号：BUG-012  
优先级：P2  
问题：仓库当前 lint/format 门禁失败。

复现步骤：执行 `uv run ruff check .` 和 `uv run ruff format --check .`。

预期：发布分支全部质量门禁通过。

实际：1 个 E501；3 个文件需要格式化。

建议：修复格式后将 ruff、mypy、pytest 和 build smoke 设为受保护分支 required checks。

## BUG-013

编号：BUG-013  
优先级：P2  
问题：Windows 启动日志存在乱码，降低外部用户诊断能力。

复现步骤：由标准 stdio MCP Client 启动 Server 并读取 stderr。

预期：显示清晰的启动文本。

实际：破折号显示为 `бк`，例如 `h3c-hcl-mcp v0.0.1 бк starting...`。

建议：统一 stderr UTF-8 编码，避免非 ASCII 装饰字符，加入 Windows console 编码 smoke test。

# 优化建议

1. 以“真实 HCL fixture + 官方 MCP Client e2e”作为 beta 的主验收链路，不再只依赖 in-process `server.call_tool` 测试。
2. 为 Tool 输入使用 Pydantic 约束生成 JSON Schema：`source` 使用 Literal/enum，timeout/count/max_hops 使用范围约束，destination 使用长度和字符策略。
3. 不静默裁剪非法数值；返回 `INVALID_ARGUMENT` 并告诉 Agent 合法范围。
4. `hcl_list_projects` 返回被跳过项目的 warning 和原因，避免把“格式不兼容”伪装成“没有项目”。
5. `hcl_get_runtime` 先验证项目存在；设备存在但未运行时返回 `DEVICE_NOT_RUNNING`，不要返回 `DEVICE_NOT_FOUND`。
6. 冻结 v0.1 Tool 名称、参数和错误码，并为 Claude Desktop、Claude Code、Cursor 各保留一份可执行配置 smoke。
7. 发布前在全新 Windows 用户环境执行：PyPI 安装、initialize、tools/list、真实 HCL 只读命令、卸载。
8. 占位能力不要注册为正式 Tool；功能标志应影响 `tools/list`，而不是让 Agent 调用后才发现未实现。
9. 审计、版本和配置属于横切能力，应由统一中间层/Composition Root 接入，不应由每个 Tool 自己实现。
10. 新增兼容矩阵，至少记录 HCL 版本、真实文件 schema、设备型号、Comware 版本、console 发现方式和测试日期。

# 优先级

| 优先级 | 含义 | Bug | 发布要求 |
|---|---|---|---|
| P0 | 阻断外部安装或核心 HCL 使用 | BUG-001、BUG-002、BUG-003 | beta 发布前必须全部关闭 |
| P1 | 破坏配置、错误语义、Agent 可靠性或审计 | BUG-004～BUG-010 | beta 发布前关闭；至少不得遗留误报成功和审计缺失 |
| P2 | 文档、质量门禁和诊断体验 | BUG-011～BUG-013 | RC 前关闭 |

# 交给 Claude 开发 Agent 的 Bug 修复清单

以下任务按依赖顺序执行。每个任务单独分支/PR；共享 `mcp/server.py` 的任务不得并行修改，由 Lead 最后集成。

## T1：冻结版本与发布入口（P0）

- 关联：BUG-001、BUG-010、BUG-011。
- Owned files：`pyproject.toml`、版本模块、README、CHANGELOG、发布 workflow、安装 smoke tests。
- 任务：确定下一预发布版本；统一版本源；修复 PyPI/uvx、README 和 MCP Client 配置；传递正确 serverInfo 版本。
- 验收：全新 Windows venv 可从发布源运行 README 命令；包元数据、tag、health、日志、initialize 全部同版本。

## T2：真实 HCL 5.10.3 项目兼容（P0）

- 关联：BUG-002。
- Owned files：HCL project repository/parser、脱敏 fixtures、对应 contract/unit/integration tests。
- 任务：解析 `projectInfo/deviceInfoList` 和真实 `.net`；保留兼容旧 fixture 的明确策略；输出可诊断 warning。
- 验收：真实项目可被 list/get/topology 发现，设备数和链路与 HCL UI 一致；不提交 HCL 专有资产或用户数据。

## T3：真实 Runtime Discovery 与只读 Console（P0）

- 关联：BUG-003、BUG-007 的 runtime 分支。
- 依赖：T2。
- Owned files：runtime discovery、log observer、loopback probe、Comware session 集成、Windows integration tests。
- 任务：发现运行设备和 console endpoint，验证 prompt/device identity，接入 Composition Root。
- 验收：真实 HCL 上 `display version`、`display ip interface brief`、facts/interfaces/ping 可执行；停止设备返回 `DEVICE_NOT_RUNNING`；端点缺失返回 `CONSOLE_UNAVAILABLE`。

## T4：配置加载与 CLI（P1）

- 关联：BUG-004。
- Owned files：CLI entrypoint、settings、配置 tests、示例配置。
- 任务：实现 `--config`、未知参数拒绝、环境变量覆盖和安全默认值。
- 验收：配置优先级契约测试通过；Claude/Cursor 示例能够选择真实项目目录；未知参数非零退出。

## T5：Tool 契约、错误语义和占位工具治理（P1）

- 关联：BUG-005、BUG-006、BUG-007、BUG-008。
- Owned files：MCP tool registration、error mapping、schemas、MCP e2e tests。
- 任务：冻结 Tool 名称；处理 alias/迁移；移除 v0.2 占位工具或返回 `NOT_IMPLEMENTED`；改用 `ErrorCode`；失败设置 `isError=true`；补参数约束。
- 验收：官方 MCP Client 断言成功/失败语义；不存在任何 `ok=true` 的未实现结果；五个外部名称有明确可执行契约或文档映射。

## T6：审计闭环（P1）

- 关联：BUG-009。
- Owned files：MCP middleware/audit adapter、审计 tests；如需修改 `mcp/server.py`，等待 T3/T5 完成后由 Lead 集成。
- 任务：记录每个 Tool 的成功、失败、耗时、target 和 request_id；确保敏感字段脱敏。
- 验收：e2e 调用后 `audit_query` 能查到对应记录；失败、取消和并发路径均有审计；原始密钥/配置不落库。

## T7：发布质量与 Windows 诊断（P2）

- 关联：BUG-012、BUG-013。
- Owned files：格式问题文件、CI、Windows smoke tests。
- 任务：修复 ruff；统一 UTF-8 stderr；将 lint/type/test/build/install/MCP smoke 设为 required checks。
- 验收：ruff、mypy、349+ tests、build 和全新 wheel install 全绿；Windows 日志无乱码。

## Lead 最终回归门槛

Claude Lead 合并前必须在本机真实 HCL 5.10.3 重跑以下清单，并将原始结果摘要附在 PR：

1. 从发布候选 wheel/源安装，不得使用 editable install。
2. Claude/Cursor 等价 stdio 配置完成 initialize 和 tools/list。
3. 找到 `hcl_1e910d518140`，拓扑设备数与 HCL UI 一致。
4. 在已启动 H3C 设备执行 `display version` 和 `display ip interface brief`。
5. 验证非法命令、停止设备、缺失端点和非法参数返回稳定错误。
6. 验证所有失败均被 Client 识别为失败，未实现能力不出现在 Tool 列表。
7. 验证 audit_query 能找到上述调用，且无敏感原文。
8. 确认没有修改 HCL 安装文件、项目文件或设备配置。

只有 P0 全部关闭、P1 不再存在误报成功/真实设备不可用/审计缺失，才建议重新标记 `v0.1.0-beta.1` 或发布新的预发布版本。
