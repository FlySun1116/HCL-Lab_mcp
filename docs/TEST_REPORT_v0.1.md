# HCL-Lab_mcp v0.1.0-beta.1 第三轮回归测试报告

> 测试日期：2026-07-15
>
> 测试角色：外部使用者 / MCP Client / 测试工程师
>
> 被测提交：`2bd9cb77e4e4bf60e114e8e2b3e2daca5b15c118`
>
> 上轮提交：`b486adbc1142db2a7ce4eddd261fece9e25e2771`
>
> 声明版本：`v0.1.0-beta.1`
>
> 结论：**不通过，NO-GO。**

## 执行摘要

本轮 Agent Team 增加了统一 Settings、JSON 配置、Runtime 公式端点和 validation middleware。实际黑盒回归表明：JSON 配置和缺失文件报错已有改善，但三个核心 P0 仍未关闭，而且引入了新的测试和启动回归。

当前版本仍不能让 Claude、Cursor 调用真实 HCL 中的 H3C 设备：

1. PyPI/`uvx` 公开安装仍不可用。
2. 声称修复真实 HCL parser 的提交没有修改 `project_repository.py`，真实项目仍为 0。
3. Runtime 把未监听端口报为可用，又在执行命令时报告设备未运行，存在严重假阳性和状态不一致。
4. 干净环境自动化测试为 **11 failed / 396 passed**，不是提交信息所称的全绿。
5. Server 现在没有配置文件就拒绝启动，README 的直接启动、环境变量和 `--projects-dir` 均失效。
6. validation 和 audit 的上一轮问题没有被实际修复。

发布判定：**NO-GO，不具备 beta 外部可用性。**

# 测试环境

| 项目 | 实际环境 |
|---|---|
| 操作系统 | Windows 11，build `10.0.26200`，Asia/Shanghai |
| 仓库来源 | 从 GitHub 全新 clone |
| commit | `2bd9cb77e4e4bf60e114e8e2b3e2daca5b15c118` |
| 分支 | `main`，与 `origin/main` 一致 |
| Git tag | 未发现 beta tag |
| Python | wheel：CPython `3.13.12`；开发门禁：CPython `3.14.5` |
| uv | `0.11.14` |
| MCP SDK | `1.28.1` |
| wheel | `h3c_hcl_mcp-0.1.0b1-py3-none-any.whl` |
| HCL | H3C Cloud Lab `5.10.3`，`F:\HCL` |
| HCL 进程 | SimwareClient、SimwareMultiCC、SimwareWrapper 正在运行 |
| 真实项目根目录 | `C:\Users\Sun-_-\HCL\Projects` |
| 真实项目 | `hcl_1e910d518140` |
| MCP Client | 官方 MCP Python SDK `ClientSession` + `stdio_client` |

真实 HCL 测试仅执行项目发现和两条只读 `display` 请求；没有改动设备配置、项目文件或进程状态。

# 测试项目

## 第一阶段：安装、构建和启动

| 测试项 | 结果 | 实际 |
|---|---|---|
| GitHub 全新 clone | 通过 | HEAD 与远端一致 |
| README：`uvx h3c-hcl-mcp --version` | 失败 | package registry 找不到包 |
| `uv build` | 通过 | wheel 和 sdist 生成成功 |
| 干净 Python 3.13 venv 安装 wheel | 通过 | 安装成功 |
| CLI `--version` | 通过 | `v0.1.0-beta.1` |
| 无配置直接启动 | 失败 | 提示 No configuration file found 后退出 |
| 仅设置 `H3C_CLOUD_LAB_PROJECTS` | 失败 | 在读取环境变量前因无配置文件退出 |
| 仅使用 `--projects-dir` | 失败 | 在应用 CLI override 前因无配置文件退出 |
| 显式 JSON 配置 | 通过 | initialize 成功，项目目录生效 |
| 显式 YAML 配置 | 失败 | wheel 缺少 `yaml` 模块，Server 退出 |
| 显式缺失配置文件 | 通过 | 明确报错并退出，不再静默忽略 |

README 仍写 `Current version: v0.0.1 (pre-alpha)`，与本地 beta 包不一致。

## 第二阶段：质量门禁

| 检查 | 结果 |
|---|---|
| `uv run ruff check .` | 通过 |
| `uv run ruff format --check .` | 通过，89 个文件已格式化 |
| `uv run mypy src` | 通过，67 个源文件无错误 |
| `uv build` | 通过 |
| `uv run python -m pytest` | **失败：11 failed，396 passed，共 407 项** |

11 个失败均集中在新增 Settings 测试：项目添加了 `types-pyyaml` 类型桩，却没有添加运行依赖 `PyYAML`。因此 `import yaml` 失败，YAML、环境变量优先级和 CLI override 测试随之失败。

这不是测试环境偶发问题：干净 wheel 环境直接执行 `import yaml` 同样得到 `ModuleNotFoundError`。

## 第三阶段：MCP 协议

在显式 JSON 配置下：

| 测试项 | 结果 | 实际 |
|---|---|---|
| `initialize` | 通过 | 协议 `2025-11-25` |
| `serverInfo.version` | 通过 | `0.1.0-beta.1` |
| `tools/list` | 通过 | 15 个 Tool |
| `tools/call` 成功路径 | 通过 | text 与 structuredContent 可用 |
| 领域错误 `isError` | 通过 | `DEVICE_NOT_RUNNING` 等为 true |
| 非法 source/count | 失败 | 仍返回裸 Pydantic 文本和 docs URL |
| validation middleware | 失败 | stdio 实际调用路径未被成功拦截 |

新增 `validation_middleware.py` 没有改变官方 stdio Client 的实际输出。`h3c_get_config(source="snapshot")` 和 `h3c_ping(count=0)` 仍没有项目统一的 `INVALID_ARGUMENT` payload 或 request_id。

## 第四阶段：全部 Tool

15 个已注册 Tool 均完成调用或负向路径验证。

| Tool | 结果 | 判定 |
|---|---|---|
| `server_health` | 成功 | 通过 |
| `hcl_list_projects` | JSON fixture 成功；真实 HCL 返回 0 | 真实功能失败 |
| `hcl_get_topology` | fixture 成功；真实项目 PROJECT_NOT_FOUND | 失败 |
| `hcl_get_runtime` | fixture 返回两个虚假的 running endpoint；真实项目失败 | 失败且存在假阳性 |
| `h3c_list_devices` | fixture 报 operable=2；真实项目失败 | 失败且存在假阳性 |
| `h3c_get_facts` | DEVICE_NOT_RUNNING | 失败 |
| `h3c_run_display` | DEVICE_NOT_RUNNING；真实命令 DEVICE_NOT_FOUND | 失败 |
| `h3c_get_config` | DEVICE_NOT_RUNNING | 失败 |
| `h3c_get_interfaces` | DEVICE_NOT_RUNNING | 失败 |
| `h3c_ping` | DEVICE_NOT_RUNNING | 失败 |
| `h3c_trace_route` | DEVICE_NOT_RUNNING | 失败 |
| `h3c_diff_config` | NOT_IMPLEMENTED / isError=true | 错误语义正确；能力不可用 |
| `job_get` | 缺失 job 返回 INVALID_ARGUMENT | 负向路径通过 |
| `job_cancel` | 缺失 job 返回 INVALID_ARGUMENT | 负向路径通过 |
| `audit_query` | 能查询记录 | 部分通过，内容仍错误 |

用户验收清单中的 `list_devices`、`execute_command`、`configure_device`、`get_device_status`、`ping_test` 仍未注册。仓库新增了 `docs/TOOL_ALIAS_PROPOSAL.md`，但尚未形成已确认的公共契约或实际 alias。

## 第五阶段：Runtime 假阳性专项

合成项目有两台设备。在本机 HCL 进程存在的情况下，Server 返回：

| 设备 | Server 状态 | Server endpoint | 实际端口 |
|---|---|---|---|
| Device 1 | running / console_available / operable | `127.0.0.1:30001` | 未监听 |
| Device 2 | running / console_available / operable | `127.0.0.1:30002` | 未监听 |

紧接着在同一个 MCP 会话调用 `h3c_run_display`，又返回：

`DEVICE_NOT_RUNNING: Device 1 is not running (state: unknown)`

根因：

1. `discover_project()` 将 UNKNOWN 临时转换为 RUNNING，并临时生成公式端点。
2. 公式端点没有 TCP 探测，更没有 Comware prompt 身份验证。
3. `discover_device()` 直接读取原始 UNKNOWN 状态，不复用 `discover_project()` 的有效状态。
4. 仅检测到任意 HCL 进程就把所有登记设备视为 running，不能代表具体项目或设备已启动。

这是安全和可靠性问题。Agent 可能根据 `operable=true` 选择设备，但下一步必然失败；更危险的是将来如果该端口被其他服务监听，Server 可能连接错误目标。

## 第六阶段：真实 HCL 5.10.3

使用显式 JSON 将 `hcl.projects_dirs` 指向真实项目根目录。

| 测试项 | 结果 | 实际 |
|---|---|---|
| `hcl_list_projects` | 失败 | count=0 |
| `hcl_get_topology hcl_1e910d518140` | 失败 | PROJECT_NOT_FOUND |
| `hcl_get_runtime` | 失败 | PROJECT_NOT_FOUND |
| `h3c_list_devices` | 失败 | PROJECT_NOT_FOUND |
| `display version` | 失败 | DEVICE_NOT_FOUND |
| `display ip interface brief` | 失败 | DEVICE_NOT_FOUND |

本轮声称修复 BUG-002 的提交 `3569eb5` 实际修改的是：

- `config/config.example.json`
- `docs/TOOL_ALIAS_PROPOSAL.md`
- `mcp/validation_middleware.py`
- `tests/unit/infrastructure/test_settings.py`

没有修改 `adapters/hcl/project_repository.py`。该 parser 仍读取错误的 `projectId/projectName/deviceId/deviceName`，而本机真实字段是 `projectInfo.name/path` 和 `deviceInfoList.resource*`。

## 第七阶段：审计

BUG-009 在本轮没有关闭：

- DEVICE_NOT_RUNNING 仍记录为 INTERNAL_ERROR。
- NOT_IMPLEMENTED 仍记录为 INTERNAL_ERROR。
- INVALID_ARGUMENT 仍记录为 INTERNAL_ERROR。
- response、日志和 AuditEvent 使用不同 request_id。
- 参数 Schema 校验失败不产生事件。
- 所有工具异常仍被写为 policy_result=denied。

本轮新增 validation middleware 没有接入审计，也没有解决调用关联。

# 成功项

1. 本地 wheel/sdist 可构建和安装。
2. CLI、wheel、health 和 initialize 版本一致。
3. JSON 配置现在确实生效。
4. 缺失的显式配置文件会明确失败。
5. MCP initialize、tools/list 和普通 tools/call 正常。
6. 15 个 Tool 可发现，领域错误 isError=true。
7. ruff、format 和 mypy 通过。
8. 启动提示不再重复输出。
9. Tool alias 差异已有独立提案文档，但尚待决策。

# 失败项

1. 公开安装仍不可用。
2. 无配置、仅环境变量和仅 `--projects-dir` 都无法启动。
3. YAML 运行依赖缺失。
4. 407 项测试中有 11 项失败。
5. 真实 HCL parser 实际没有被修改。
6. 真实项目仍无法发现。
7. Runtime 报告未监听端口为 operable。
8. Runtime 列表与单设备查询状态互相矛盾。
9. 两条真实 display 命令仍失败。
10. validation middleware 没有改变 stdio 输出。
11. 审计错误码、request_id 和覆盖范围仍错误。
12. README 版本和启动方式仍与实现不一致。

# Bug列表

## BUG-001

编号：BUG-001

状态：未修复

优先级：P0

问题：外部用户仍无法从 package registry 安装，README 和发布元数据不闭环。

复现步骤：执行 `uvx h3c-hcl-mcp --version`。

预期：安装发布版并输出 beta 版本。

实际：registry 找不到包；没有 beta tag；README 仍声明 v0.0.1。

建议：在核心功能通过后建立 TestPyPI/PyPI、GitHub Release、tag 和全新 Windows 安装 smoke；发布前不要用本地 wheel 结果关闭此 Bug。

## BUG-002

编号：BUG-002

状态：未修复，提交内容与提交说明不一致

优先级：P0

问题：真实 HCL parser 没有实际修改，真实项目仍为 0。

复现步骤：显式配置真实项目根目录，调用 list/topology。

预期：发现 `hcl_1e910d518140`。

实际：count=0、PROJECT_NOT_FOUND；相关提交没有修改 parser 文件。

建议：Lead 先核对 `git show --name-only 3569eb5`；重新建立 Parser Agent 任务，Owned files 必须包含 project_repository、net parser、真实脱敏 fixture 和对应测试；用本机实际文件黑盒验收。

## BUG-003

编号：BUG-003

状态：修复无效并引入假阳性

优先级：P0

问题：Runtime 把未监听公式端口报告为 running/operable，随后单设备调用又报告未运行。

复现步骤：先调用 hcl_get_runtime 和 h3c_list_devices，再调用 h3c_run_display。

预期：只有经过 TCP 和 Comware prompt 验证的 endpoint 才能 operable；同一会话状态一致。

实际：30001/30002 未监听却 operable=true；display 返回 DEVICE_NOT_RUNNING。

建议：删除“仅 HCL 进程存在即全部 running”的逻辑；公式只能生成 candidate，不能成为 available endpoint；实现 TCP probe、prompt 验证和单一 runtime cache；discover_project/discover_device 共用同一状态来源。

## BUG-004

编号：BUG-004

状态：部分修复并引入启动回归

优先级：P1

问题：JSON 和缺失文件处理已修复，但 YAML 不可用，而且 Server 现在强制要求配置文件。

复现步骤：分别无配置启动、仅环境变量启动、仅 `--projects-dir` 启动、YAML 启动、JSON 启动。

预期：安全默认值允许直接启动；CLI/env 可独立覆盖；README YAML/JSON 均可用。

实际：前三种因 No configuration file found 退出；YAML 因缺 PyYAML 退出；只有 JSON 成功。

建议：没有显式 `--config` 时使用强类型默认值并继续应用 env/CLI；只有显式路径缺失才失败；把 PyYAML 放入正式 dependencies；增加从 wheel 执行的五种 stdio smoke。

## BUG-005

编号：BUG-005

状态：等待维护者确认

优先级：P1

问题：五个验收 Tool 名称仍不存在，只有提案文档。

复现步骤：检查 tools/list 或调用五个名称。

预期：维护者确认后的稳定契约可用。

实际：仍只有 namespaced Tool。

建议：由维护者对 `docs/TOOL_ALIAS_PROPOSAL.md` 作决定；未确认前不要由 Agent 单方面关闭。

## BUG-009

编号：BUG-009

状态：未修复

优先级：P1

问题：审计仍丢失真实错误码和关联 ID，并漏记 validation failure。

复现步骤：调用 DEVICE_NOT_RUNNING、NOT_IMPLEMENTED、INVALID_ARGUMENT 和 schema failure，再查询 audit。

预期：真实错误码、同一 request_id、准确 outcome/policy、每次尝试都有记录。

实际：前三种均为 INTERNAL_ERROR；ID 不一致；schema failure 无记录；异常统一 denied。

建议：把 request context、validation、Tool 调用、error mapping 和 audit 放在同一官方调用边界，不要分别修改 FastMCP 私有对象。

## BUG-014

编号：BUG-014

状态：修复无效

优先级：P1

问题：validation middleware 已增加但标准 stdio Client 输出未变化。

复现步骤：传 source=snapshot 或 count=0。

预期：稳定 INVALID_ARGUMENT、字段、范围、request_id。

实际：裸 Pydantic 英文文本和外部 docs URL。

建议：为官方 MCP SDK stdio 路径写失败优先 e2e test，再选择正确的 SDK hook；不要用进程内假调用证明中间件生效。

## BUG-016

编号：BUG-016

状态：新增

优先级：P1

问题：干净环境测试失败，YAML 运行依赖被错误地替换为类型桩。

复现步骤：全新 clone 后执行 `uv sync --extra dev` 和 `uv run python -m pytest`。

预期：全部测试通过。

实际：11 failed / 396 passed；`ModuleNotFoundError: No module named 'yaml'`。

建议：将 `PyYAML` 加入运行 dependencies，将 `types-PyYAML` 保留在 dev；删除 Agent 环境的隐式全局依赖；CI 必须从空缓存/干净 venv 验证。

## 已验证修复

| Bug | 状态 | 证据 |
|---|---|---|
| BUG-006 | 已修复 | change placeholder 已移除，diff 正确报 NOT_IMPLEMENTED |
| BUG-007 | 已修复 | 错误 enum 不再触发 AttributeError |
| BUG-008 | 已修复 | 领域错误 isError=true |
| BUG-010 | 已修复 | 应用版本一致 |
| BUG-011 | 已修复 | uv sync 开发安装可执行 |
| BUG-012 | 已修复 | ruff/format 通过 |
| BUG-013 | 已修复 | 原 Windows 乱码消失 |
| BUG-015 | 已修复 | 启动提示只出现一次 |

# 优先级

| 优先级 | 活跃 Bug | 发布要求 |
|---|---|---|
| P0 | BUG-001、BUG-002、BUG-003 | 全部关闭前禁止 beta 发布 |
| P1 | BUG-004、BUG-005、BUG-009、BUG-014、BUG-016 | beta 前关闭或由维护者接受契约变更 |

# 交给 Claude Agent Team 的修复清单

## Agent Team 交付规则

1. 每个 Agent 完成时必须附 `git diff --name-only <base>..HEAD`。
2. 提交标题声称修复某模块时，diff 必须包含该模块 Owned files。
3. Lead 不得仅依据 Agent 消息或 unit test 标记完成，必须运行外部黑盒验收。
4. 所有门禁从全新 clone、干净 uv 环境执行，禁止依赖全局 site-packages。
5. 共享 `mcp/server.py` 只由 Lead 集成。

## T1：真正完成 HCL Parser（P0）

- 关联：BUG-002。
- Owned files：project_repository.py、net_parser.py、真实脱敏 fixture、parser tests。
- 要求：使用实际 `projectInfo.name/path` 和 `deviceInfoList.resource*`；ID 从目录/.net 获取；按 resourceName 合并。
- 验收：wheel + JSON 配置可发现本机项目并返回正确拓扑。

## T2：重做 Runtime Discovery（P0）

- 关联：BUG-003。
- 依赖：T1。
- 要求：candidate 与 verified endpoint 分离；TCP probe；Comware prompt 身份验证；统一 project/device 查询状态。
- 验收：未监听 30001 不得 operable；真实设备执行两条 display；停止/无端点错误稳定。

## T3：配置和依赖闭环（P1）

- 关联：BUG-004、BUG-016。
- 要求：PyYAML 正式依赖；默认启动恢复；CLI/env 不依赖配置文件；JSON/YAML/缺失/非法配置黑盒测试。
- 验收：407+ tests 全绿，干净 wheel 五种启动模式符合 README。

## T4：Validation 和 Audit 官方调用边界（P1）

- 关联：BUG-009、BUG-014。
- 要求：先写 stdio e2e；单一 request context；validation 也审计；保留真实错误码；outcome 与 policy 分开。
- 验收：用响应 request_id 查询到对应准确事件，非法 source/count 为结构化 INVALID_ARGUMENT。

## T5：契约和发布（P0/P1）

- 关联：BUG-001、BUG-005。
- 依赖：T1～T4。
- 要求：维护者确认 alias 提案；更新 README 状态；发布 TestPyPI/PyPI 和 tag 前请求授权。
- 验收：全新 Windows 环境逐字执行 README 安装配置，Claude/Cursor 等价 stdio Client 可调用真实设备。

## 最终回归门槛

1. 公开安装 smoke 成功。
2. 干净环境全部测试通过。
3. 无配置、CLI、env、JSON、YAML 五种配置路径符合文档。
4. 真实 HCL 项目和拓扑可发现。
5. endpoint 必须经过实际探测和 prompt 验证。
6. 两条真实 display 命令成功。
7. validation 和 audit request_id 可关联。
8. 没有修改 HCL 项目或设备配置。
