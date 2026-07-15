# HCL-Lab_mcp v0.1.0-beta.1 第二轮回归测试报告

> 测试日期：2026-07-15
>
> 测试角色：外部使用者 / MCP Client / 测试工程师
>
> 被测仓库：`FlySun1116/HCL-Lab_mcp`
>
> 被测提交：`b486adbc1142db2a7ce4eddd261fece9e25e2771`
>
> 对比基线：`a0f48fdb42c7ebe84f9b8dc3b82da624b8e61e0d`
>
> 声明版本：`v0.1.0-beta.1`
> 回归结论：**不通过，仍然 NO-GO。**

## 执行摘要

Claude 合并的修复取得了可验证的进展：本地 wheel 版本、MCP initialize 版本、参数 Schema、MCP `isError`、未实现错误、CLI 未知参数、ruff、mypy 和自动化测试均已改善。标准 MCP Client 可以稳定发现 15 个 Tool，成功结果与失败结果现在可以被客户端区分。

但项目的最终目标仍未实现：**Claude、Cursor 仍不能调用真实 HCL 中的 H3C 设备。** 三个 P0 阻断项没有关闭：

1. README 推荐的 PyPI/`uvx` 安装仍不可用。
2. 所谓“真实 HCL 5.10.3 fixture”与本机 HCL 5.10.3 文件字段不一致，真实项目仍返回 0 个。
3. Runtime Discovery 只检查 HCL 进程是否存在，没有发现任何设备或 console endpoint，所有设备命令仍不可执行。

此外，配置和审计修复属于“已接线但行为不正确”：README 示例 YAML、等价 JSON 和缺失配置文件都会静默启动并忽略项目目录；审计能写入记录，但领域错误全部记为 `INTERNAL_ERROR`，参数校验失败不留审计。

发布判定：**NO-GO，不应发布或标记为可用的 `v0.1.0-beta.1`。**

# 测试环境

| 项目 | 实际环境 |
|---|---|
| 操作系统 | Windows 11，build `10.0.26200`，Asia/Shanghai |
| 仓库 | 从 GitHub 全新 clone，`main` 与 `origin/main` 一致 |
| Git commit | `b486adbc1142db2a7ce4eddd261fece9e25e2771` |
| Git tag | 未发现对应 beta tag |
| Python | wheel 环境 CPython `3.13.12`；开发门禁 CPython `3.14.5` |
| uv | `0.11.14` |
| MCP SDK | `1.28.1` |
| wheel 元数据 | `h3c-hcl-mcp==0.1.0b1` |
| CLI/health/initialize 版本 | `0.1.0-beta.1` |
| HCL | H3C Cloud Lab `5.10.3`，安装目录 `F:\HCL` |
| HCL 进程 | `SimwareClient.exe`、`SimwareMultiCC.exe`、`SimwareWrapper.exe` 正在运行 |
| 真实项目根目录 | `C:\Users\Sun-_-\HCL\Projects` |
| 真实测试项目 | `hcl_1e910d518140` |
| MCP Client | 官方 MCP Python SDK `ClientSession` + `stdio_client` |
| 安装隔离 | 新 clone、独立 PyPI venv、独立 wheel venv、独立开发 venv |

真实 HCL 测试只执行发现和 `display` 类只读调用；没有修改 HCL 文件、设备配置或进程状态。

# 测试项目

## 第一阶段：外部安装、构建和启动

| 编号 | 测试项 | 结果 | 实际 |
|---|---|---|---|
| INS-01 | 从 GitHub 全新 clone | 通过 | HEAD 与远端一致，工作区干净 |
| INS-02 | README：`uvx h3c-hcl-mcp` | 失败 | package registry 中仍不存在该包 |
| INS-03 | README：`pip install h3c-hcl-mcp` | 失败 | 无法从 package registry 解析 |
| INS-04 | `uv build` | 通过 | 生成 `h3c_hcl_mcp-0.1.0b1` wheel 和 sdist |
| INS-05 | 干净 Python 3.13 venv 安装 wheel | 通过 | 安装成功，CLI 入口存在 |
| INS-06 | `h3c-hcl-mcp --version` | 通过 | 输出 `v0.1.0-beta.1` |
| INS-07 | 未知 CLI 参数 | 通过 | 非零退出并显示 unrecognized arguments |
| INS-08 | README 开发安装 `uv sync --extra dev` | 通过 | 开发环境成功创建 |
| INS-09 | README Claude/Cursor 固定安装配置 | 失败 | 仍依赖未发布的 PyPI 包 |
| INS-10 | README 当前状态说明 | 失败 | README 仍写“Current version: v0.0.1 (pre-alpha)” |

版本源在本地包、CLI、health 和 MCP initialize 之间已经一致，这是上一轮 BUG-010 的有效修复；但 README、Git tag 和公开制品没有完成发布闭环。

## 第二阶段：质量门禁

| 检查 | 结果 |
|---|---|
| `uv run ruff check .` | 通过 |
| `uv run ruff format --check .` | 通过，87 个文件已格式化 |
| `uv run mypy src` | 通过，66 个源文件无问题 |
| `uv run python -m pytest` | 通过，`353 passed`，约 67 秒 |
| `uv build` | 通过 |
| 本地 wheel 安装 smoke | 通过 |

说明：直接执行临时目录中的 `pytest.exe` 被本机 Windows 应用控制策略拦截；改用等价的 `python -m pytest` 后完整套件通过。这是测试主机策略，不判定为项目 Bug。

## 第三阶段：MCP 协议

| 编号 | 测试项 | 结果 | 实际 |
|---|---|---|---|
| MCP-01 | `initialize` | 通过 | 协议版本 `2025-11-25` |
| MCP-02 | `serverInfo.version` | 通过 | `0.1.0-beta.1` |
| MCP-03 | `tools/list` | 通过 | 返回 15 个 Tool |
| MCP-04 | `tools/call server_health` | 通过 | text 与 `structuredContent` 均可读取 |
| MCP-05 | 领域错误 | 通过 | `DEVICE_NOT_FOUND` 等返回 `isError=true` |
| MCP-06 | 输入 Schema 校验 | 通过 | timeout/count/max_hops 有范围，source 有 enum |
| MCP-07 | 非法输入错误格式 | 部分失败 | `isError=true`，但返回裸 Pydantic 英文文本而非稳定 `INVALID_ARGUMENT` payload |
| MCP-08 | 未知 Tool | 通过 | 返回 `isError=true` 和 Unknown tool |

## 第四阶段：配置方式

使用一个仅包含合成项目目录的配置文件，并把子进程 `USERPROFILE` 指向空目录，以排除默认 HCL 目录的干扰。

| 测试 | 预期 | 实际 | 结果 |
|---|---|---|---|
| README 风格 YAML：`hcl.projects_dirs` | 列出 4 个 fixture 项目 | 返回 0 个项目 | 失败 |
| 等价 JSON：`hcl.projects_dirs` | 列出 4 个 fixture 项目 | 返回 0 个项目 | 失败 |
| 不存在的 `--config` 路径 | 启动失败并明确提示 | 静默启动，返回 0 个项目 | 失败 |
| 未知 CLI 参数 | 拒绝启动 | 非零退出 | 通过 |
| `H3C_CLOUD_LAB_PROJECTS` 环境变量 | 列出 fixture 项目 | 返回 4 个项目 | 通过 |

根因：

- wheel 依赖中没有 PyYAML，YAML parser 在 ImportError 时直接返回空配置。
- JSON/YAML 的 `hcl.projects_dirs` 被展平为 `hcl_projects_dirs`，Composition Root 却读取 `projects_dirs`。
- 文件不存在、YAML 解析失败和不支持的后缀都返回空字典，没有配置错误。
- PolicySettings 和示例配置中的多数设置没有被传入实际 adapter。

## 第五阶段：全部 Tool 回归

当前 `tools/list` 返回 15 个 Tool；4 个 v0.2 change placeholder 已从注册表移除。

| Tool | 合成环境结果 | 真实 HCL 结果 | 判定 |
|---|---|---|---|
| `server_health` | 成功，版本正确 | 成功 | 通过 |
| `hcl_list_projects` | 成功，列出 4 个 | 返回 0 个 | 失败（真实兼容性） |
| `hcl_get_topology` | 成功 | `PROJECT_NOT_FOUND` | 失败 |
| `hcl_get_runtime` | 成功但设备为空 | `PROJECT_NOT_FOUND` | 失败；项目校验已修复但无 runtime discovery |
| `h3c_list_devices` | 列出 2 台但 operable=0 | `PROJECT_NOT_FOUND` | 失败 |
| `h3c_get_facts` | `DEVICE_NOT_FOUND` | 无法执行 | 失败 |
| `h3c_run_display` | `DEVICE_NOT_FOUND` | 两条真实命令均失败 | 失败 |
| `h3c_get_config` | `DEVICE_NOT_FOUND` | 无法执行 | 失败；非法 source 校验已修复 |
| `h3c_get_interfaces` | `DEVICE_NOT_FOUND` | 无法执行 | 失败 |
| `h3c_ping` | `DEVICE_NOT_FOUND` | 无法执行 | 失败；count 范围校验已修复 |
| `h3c_trace_route` | `DEVICE_NOT_FOUND` | 无法执行 | 失败；max_hops 范围校验已修复 |
| `h3c_diff_config` | `NOT_IMPLEMENTED`、`isError=true` | 未执行 | 错误语义已修复；仍建议不在 beta 注册 |
| `job_get` | 缺失 job 返回 `INVALID_ARGUMENT` | 不适用 | 负向路径通过 |
| `job_cancel` | 缺失 job 返回 `INVALID_ARGUMENT` | 不适用 | 负向路径通过 |
| `audit_query` | 返回审计事件 | 返回审计事件 | 部分通过，内容存在错误 |

### 用户要求的五个名称

以下精确名称仍未注册：

| 要求名称 | 当前近似名称 | 调用结果 |
|---|---|---|
| `list_devices` | `h3c_list_devices` | Unknown tool |
| `execute_command` | `h3c_run_display` | Unknown tool |
| `configure_device` | 无可用实现 | Unknown tool |
| `get_device_status` | `hcl_get_runtime` / `h3c_get_facts` | Unknown tool |
| `ping_test` | `h3c_ping` | Unknown tool |

如果维护者决定 namespaced 名称是唯一正式 API，需要取得需求方确认并更新交付验收清单；仅在 CHANGELOG 说明“不提供 alias”不能自动关闭接口契约差异。

## 第六阶段：真实 HCL 5.10.3

测试时 HCL 和三个 Simware 进程都在运行，`C:\Users\Sun-_-\HCL\Projects` 下存在 3 个目录。

| 测试 | 结果 | 实际 |
|---|---|---|
| 自动使用默认 HCL 项目目录 | 通过 | Server 确实扫描默认目录 |
| `hcl_list_projects` | 失败 | `count=0` |
| `hcl_get_topology hcl_1e910d518140` | 失败 | `PROJECT_NOT_FOUND` |
| `hcl_get_runtime hcl_1e910d518140` | 失败 | `PROJECT_NOT_FOUND` |
| `h3c_list_devices` | 失败 | `PROJECT_NOT_FOUND` |
| `display version` | 失败 | `DEVICE_NOT_FOUND` |
| `display ip interface brief` | 失败 | `DEVICE_NOT_FOUND` |
| 配置命令 | 未执行 | v0.1 没有配置 Tool，未修改设备 |

### 真实 schema 与新增 fixture 的差异

本机真实 HCL 5.10.3：

- `projectInfo` 字段为 `name`、`path`、`visibility`、`introduction`、`label`。
- `deviceInfoList` 字段为 `resourceName`、`resourceCategory`、`resourceModel`、`resourceVersion`、`configPath`。
- `deviceInfoList` 没有 `deviceId`；device ID 和设备名存在于 `.net` 文件中。

新增 fixture 使用了 `projectId/projectName/hclVersion` 和 `deviceId/deviceName/deviceModel/deviceType/comwareVersion`。这并不是本机实际 5.10.3 schema，因此自动化测试通过但真实项目仍失败。

### Runtime Discovery 实际能力

当前实现调用 `tasklist` 判断 HCL 进程是否存在，但：

- 不读取项目拓扑设备列表。
- 不读取 HCL 日志。
- 不枚举或探测 loopback console 端口。
- 不创建 `DeviceRuntime`。
- 不创建 `RuntimeEndpoint`。
- 检测到 HCL 且无设备时只执行 `pass`。

因此模块注释中“Endpoint discovery via config, formula, and log parsing”与实际行为不一致。即使先修复项目 parser，设备 Tool 仍然无法连接。

## 第七阶段：审计

审计数据库不再为空，这是有效改进。在合成回归中，`audit_query` 返回 14 条 middleware 记录。

仍存在以下问题：

1. `DEVICE_NOT_FOUND`、`NOT_IMPLEMENTED`、`INVALID_ARGUMENT` 在审计表中全部被记录为 `INTERNAL_ERROR`。
2. Tool 先把 `DomainError` 转成 `ToolError`，audit middleware 只认识 `DomainError`，所以错误码丢失。
3. 参数 Schema 校验发生在 middleware 之前，非法 `source` 和 `count=0` 没有审计记录。
4. 审计 middleware 生成新的 request_id，与 Tool 返回或错误日志中的 request_id 不一致，无法端到端关联。
5. `policy_result` 把所有工具异常统一写为 `denied`，把资源不存在、未实现、内部错误与真正策略拒绝混在一起。

# 成功项

1. 本地 wheel/sdist 构建成功，wheel 可安装。
2. 包、CLI、health、initialize 的应用版本已统一为 `0.1.0-beta.1`。
3. CLI 未知参数会被拒绝。
4. 标准 MCP initialize、tools/list、tools/call 正常。
5. Tool 数从 19 降为 15，4 个 v0.2 change placeholder 已移除。
6. 领域错误现在设置 MCP `isError=true`。
7. `h3c_diff_config` 不再误报成功，返回 `NOT_IMPLEMENTED`。
8. `source` 使用 enum，timeout/count/max_hops 有 JSON Schema 范围约束。
9. `hcl_get_runtime` 会先验证项目是否存在。
10. 审计 middleware 已接入并能写入成功/失败事件。
11. README 开发环境命令已修复为 `uv sync --extra dev`。
12. Windows 启动日志乱码已消失。
13. ruff、format、mypy、353 个 tests 和 build 全部通过。

# 失败项

1. PyPI/`uvx` 公开安装仍不可用。
2. README 当前版本仍写 `v0.0.1`，没有 beta tag。
3. README YAML 和等价 JSON 配置均被静默忽略。
4. 缺失配置文件被静默忽略。
5. 真实 HCL 5.10.3 项目仍无法发现。
6. Runtime Discovery 没有发现任何设备或 endpoint。
7. 所有真实 H3C 设备命令仍失败。
8. 用户要求的五个 Tool 名称仍不存在。
9. 审计错误码、request_id、policy_result 和覆盖范围不正确。
10. 参数校验错误不是稳定结构化 `INVALID_ARGUMENT`。
11. 启动提示在 stderr 重复输出两次。

# Bug列表

## BUG-001

编号：BUG-001

状态：未修复

优先级：P0
问题：外部用户仍不能按 README 从公开 package registry 安装。

复现步骤：

1. 在干净环境执行 `uvx h3c-hcl-mcp --version`。
2. 在干净 venv 执行 `pip install h3c-hcl-mcp`。

预期：安装并输出 `v0.1.0-beta.1`。

实际：package registry 找不到 `h3c-hcl-mcp`。本地 wheel 已正确改为 `0.1.0b1`，但没有公开制品和 tag；README 仍写当前版本 `v0.0.1`。

建议：建立 release tag 和 GitHub Release；先发布 TestPyPI 做 smoke，再发布 PyPI；从发布源重跑 README；更新 README 状态、classifier 和 CHANGELOG。

## BUG-002

编号：BUG-002

状态：修复无效

优先级：P0
问题：新增 HCL 5.10.3 parser/fixture 不符合本机真实 schema，项目发现仍失败。

复现步骤：

1. 保持真实 HCL 5.10.3 项目目录不变。
2. 启动 wheel，使用默认项目目录。
3. 调用 `hcl_list_projects` 和 `hcl_get_topology`。

预期：列出 `hcl_1e910d518140` 并解析设备和链路。

实际：项目列表为 0，指定项目返回 `PROJECT_NOT_FOUND`。真实字段是 `projectInfo.name/path` 和 `deviceInfoList.resource*`，新增 fixture 使用不存在的 `projectId/deviceId/deviceName` 等字段。

建议：直接从本机真实文件生成最小脱敏 fixture；项目 ID 使用目录名或 `projectInfo.path`；设备 ID/名称与 `.net` 联合解析，按 `resourceName` 关联 metadata；加入本机真实文件 golden test。

## BUG-003

编号：BUG-003

状态：修复无效

优先级：P0
问题：Runtime Discovery 仍没有设备和 console endpoint 发现能力。

复现步骤：

1. 启动 HCL、SimwareClient、SimwareMultiCC 和 SimwareWrapper。
2. 调用 `hcl_get_runtime`、`h3c_run_display`。

预期：返回运行设备与已验证 console endpoint，并执行只读命令。

实际：代码只检测进程；没有生成任何 runtime/endpoint。合成项目 runtime 为空，设备 Tool 返回 `DEVICE_NOT_FOUND`。

建议：先从 topology 得到设备列表；实现日志观察和候选端口发现；逐端口验证 Comware prompt 与设备身份；返回 `DEVICE_NOT_RUNNING`/`CONSOLE_UNAVAILABLE`，不要把拓扑中存在的设备报为不存在。

## BUG-004

编号：BUG-004

状态：部分修复

优先级：P1
问题：CLI 能解析 `--config`，但配置内容没有按 README 生效，错误被静默吞掉。

复现步骤：

1. 创建 README 风格 YAML，设置 `hcl.projects_dirs` 指向 fixture。
2. 使用 `--config` 启动并调用 `hcl_list_projects`。
3. 使用等价 JSON 和不存在路径重复。

预期：YAML/JSON 列出 fixture；缺失文件明确失败。

实际：三种情况均正常启动并返回 0 个项目。YAML 缺 PyYAML；展平键和读取键不一致；错误返回空配置。

建议：使用一个强类型根 Settings model 覆盖 server/hcl/devices/policy/audit；把 PyYAML 作为正式依赖或只承诺 JSON；显式校验文件存在、格式和字段；配置错误非零退出。

## BUG-005

编号：BUG-005

状态：未修复 / 等待维护者确认契约

优先级：P1
问题：验收清单中的五个 Tool 名称仍全部 Unknown tool。

复现步骤：调用 `list_devices`、`execute_command`、`configure_device`、`get_device_status`、`ping_test`。

预期：名称可用，或在开始开发前由需求方确认新的稳定契约。

实际：全部 unknown tool。

建议：不要由开发 Agent 单方面以“canonical namespaced API”关闭需求差异。维护者确认后选择：增加只读 alias；或正式修改验收清单、README 和客户端提示词。

## BUG-009

编号：BUG-009

状态：部分修复

优先级：P1
问题：审计可以写入，但错误码、关联 ID、策略含义和覆盖范围错误。

复现步骤：

1. 调用成功 Tool、`DEVICE_NOT_FOUND`、`NOT_IMPLEMENTED`、缺失 job 和参数校验失败。
2. 调用 `audit_query`。

预期：每次调用记录真实错误码、同一个 request_id、准确结果分类；非法参数也有事件。

实际：所有 ToolError 均记为 `INTERNAL_ERROR`；request_id 与 Tool 不一致；异常统一标为 denied；Pydantic 校验失败不记录。

建议：在 FastMCP 调度/校验边界建立统一 invocation context；先生成 request_id 并贯穿 ToolResult、日志和 AuditEvent；审计 ToolError 结构化 payload；把 outcome 与 policy_result 分开。

## BUG-014

编号：BUG-014

状态：新增

优先级：P1
问题：参数校验错误缺少稳定、机器可读的项目错误结构。

复现步骤：调用 `h3c_get_config(source="snapshot")` 或 `h3c_ping(count=0)`。

预期：`isError=true`，并返回结构化 `INVALID_ARGUMENT`、字段、合法范围和 request_id。

实际：返回裸 Pydantic 英文异常文本及外部文档 URL，没有稳定 error code/request_id，且不进入审计。

建议：增加 validation error mapper，将 Pydantic/FastMCP validation 统一映射为项目错误 envelope；保持开发细节只在 debug 日志中。

## BUG-015

编号：BUG-015

状态：新增

优先级：P2
问题：Server 启动提示重复输出。

复现步骤：由 stdio Client 启动 wheel 并读取 stderr。

预期：启动提示出现一次。

实际：`h3c-hcl-mcp v0.1.0-beta.1 -- starting stdio server...` 连续出现两次。

建议：只在 CLI entrypoint 或 server main 的一个位置输出启动信息，并用日志系统统一控制级别。

## 已验证修复

| 原 Bug | 状态 | 回归证据 |
|---|---|---|
| BUG-006 | 基本修复 | 4 个 change placeholder 已移除；diff 返回 NOT_IMPLEMENTED/isError |
| BUG-007 | 已修复 | 错误 enum 分支不再退化为 AttributeError；非法 source 在 Schema 层拒绝 |
| BUG-008 | 已修复 | 领域错误 `isError=true` |
| BUG-010 | 已修复 | CLI、health、initialize、wheel 版本一致 |
| BUG-011 | 已修复 | `uv sync --extra dev` 可用 |
| BUG-012 | 已修复 | ruff 和 format 通过 |
| BUG-013 | 已修复 | Windows 日志无原乱码 |

# 优化建议

1. 把真实、脱敏 HCL fixture 作为 release blocker，而不是由 Agent 根据猜测手写“real” fixture。
2. 新增真正的 stdio e2e tests；当前 integration tests 主要在进程内调用 Tool，无法覆盖 CLI、配置、MCP validation、audit request context 和 stderr。
3. 不使用私有 `mcp._mcp_server`、`mcp._tool_manager` 作为长期扩展点；至少用 ADR 固化 SDK 版本和升级测试。
4. Server health 的 deep 模式应检查配置是否加载、项目目录是否可读、HCL 是否运行、runtime provider 是否具备 endpoint 能力。
5. 列表工具应报告被跳过的项目与原因，不能把不兼容项目静默表示为 0 个项目。
6. 将 Tool 的“调用结果”“策略判定”“协议错误”“输入校验错误”建模为不同字段。
7. README 的安装命令应由 CI 在全新环境逐字执行。
8. `h3c_diff_config` 既然明确不属于 v0.1，建议从 `tools/list` 移除，避免 Agent 选择无能力 Tool。

# 优先级

| 优先级 | 活跃 Bug | 发布要求 |
|---|---|---|
| P0 | BUG-001、BUG-002、BUG-003 | 全部关闭后才具备 beta 外部可用性 |
| P1 | BUG-004、BUG-005、BUG-009、BUG-014 | beta 前关闭或由维护者书面接受契约变更 |
| P2 | BUG-015 | RC 前关闭 |

# 交给 Claude 开发 Agent 的修复清单

下一轮不要再次把三个 P0 分给同一个宽泛任务。每个任务必须提交黑盒证据，不能只提交 unit test。

## T1：真实 HCL 项目解析（P0）

- 关联：BUG-002。
- 输入证据：本机真实 `project.json` 与 `.net`，先制作最小脱敏 fixture，由人类确认字段未被虚构。
- Owned files：project repository、net parser、真实 fixture、parser tests。
- 实现要求：`projectInfo.path/name`；`deviceInfoList.resource*`；从 `.net` 取得 device_id/name，并按资源名合并 metadata。
- 黑盒验收：wheel 启动后 `hcl_list_projects` 能看到 `hcl_1e910d518140`；topology 设备和链路与 HCL UI 一致。

## T2：Runtime 与 console endpoint 发现（P0）

- 关联：BUG-003。
- 依赖：T1。
- Owned files：runtime discovery、log observer、endpoint probe、Comware session integration、Windows e2e。
- 实现要求：从项目设备出发；HCL 进程检测只能作为前置条件；候选端口必须连接并验证 prompt；不得调用 HCL 私有控制 API。
- 黑盒验收：真实 HCL 执行 `display version` 和 `display ip interface brief`；停止设备返回 DEVICE_NOT_RUNNING；无端点返回 CONSOLE_UNAVAILABLE。

## T3：配置系统重做（P1）

- 关联：BUG-004。
- Owned files：CLI、settings、pyproject dependencies、config example、config e2e tests。
- 实现要求：单一强类型 Settings；YAML 依赖明确；禁止静默返回空配置；所有示例字段实际接入 adapter。
- 黑盒验收：README YAML、等价 JSON、env override、缺失文件、非法字段分别得到预期结果。

## T4：审计与 validation error 边界（P1）

- 关联：BUG-009、BUG-014。
- Owned files：MCP invocation middleware、error mapping、audit、stdio e2e tests。
- 实现要求：一个 request_id 贯穿；保留领域错误码；参数校验也审计；outcome 与 policy_result 分离。
- 黑盒验收：成功、DEVICE_NOT_FOUND、NOT_IMPLEMENTED、INVALID_ARGUMENT、Schema failure 各一条准确事件，可用响应 request_id 查询。

## T5：发布与公共契约（P0/P1）

- 关联：BUG-001、BUG-005、BUG-015。
- 依赖：T1～T4。
- Owned files：README、CHANGELOG、release workflow、版本元数据、Tool alias/文档、package smoke。
- 实现要求：维护者先确认 Tool 名称；更新 README 状态；只输出一次启动日志；发布 TestPyPI/PyPI 和 Git tag。
- 黑盒验收：新 Windows venv 按 README 的 `uvx`/pip 命令安装；Claude/Cursor 配置可 initialize；版本和 Tool 契约一致。

## Lead 最终回归门槛

1. 必须测试发布候选 wheel，不能使用 editable install。
2. 必须使用标准 stdio MCP Client，不得只调用 `server.call_tool`。
3. 必须使用真实 HCL 5.10.3 项目文件验证，不能只用手写 fixture。
4. 必须在真实运行设备执行两条指定 display 命令。
5. 必须验证 README YAML/JSON、环境变量和错误配置。
6. 必须验证 audit request_id 与错误码端到端一致。
7. 必须确认没有写入 HCL 项目和设备配置。
8. P0 全部关闭后，才能进入下一轮 beta 发布验收。
