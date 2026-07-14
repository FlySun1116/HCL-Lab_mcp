# HCL-Lab_mcp 项目规则

本文件是 Claude Code、兼容 Claude Code 的模型服务以及 Agent Team 在本仓库工作的长期规则。进入仓库后先读本文件，再读 `docs/design.md`。不要仅凭历史对话或模型记忆重新解释项目。

## 1. 项目身份

- 项目：`HCL-Lab_mcp`
- GitHub：`https://github.com/FlySun1116/HCL-Lab_mcp.git`
- Python distribution：`h3c-hcl-mcp`
- Python import package：`h3c_hcl_mcp`
- 许可证目标：Apache-2.0，最终以仓库 `LICENSE` 为准
- 主要平台：Windows + H3C Cloud Lab 5.10.x
- 主要语言：Python 3.12
- MCP SDK：官方 MCP Python SDK 的稳定版本线

这是一个独立运行的通用 MCP Server，不是 Claude、Cursor 或某个模型专用插件。任何兼容 MCP 的 Client 都应能使用相同的 Tool Schema。

## 2. 产品目标

让 MCP Client 能够：

1. 发现用户自己的 HCL 项目、设备和链路；
2. 判断 HCL 设备运行态和本机 console 可用性；
3. 通过 HCL loopback Telnet console 或设备 SSH 执行受控 Comware CLI；
4. 查询设备 facts、接口、配置和诊断结果；
5. 在后续版本通过计划、审批、基线校验和审计执行配置变更；
6. 分析实验拓扑并辅助网络实验。

当前阶段聚焦 HCL/H3C。架构需允许未来增加其他设备 adapter，但 v0.x 不提前实现 Huawei、Cisco、Juniper。

## 3. 事实来源优先级

发生冲突时按以下顺序执行：

1. 用户在当前会话中的明确要求；
2. 安全、许可和平台权限限制；
3. `docs/design.md` 中已批准的架构与版本范围；
4. 已接受的 ADR；
5. GitHub Issue 的验收条件；
6. 本文件；
7. 其他文档和历史提示词。

不要重新设计已在 `docs/design.md` 固化的内容。需要改变公共 Tool、Port、错误码、安全模型或版本范围时，先提交 ADR/设计差异并请求一次重要决策确认。

## 4. 首次接管流程

首次进入一个工作目录时，先做接管分析，不直接写业务代码：

1. 执行 `git rev-parse --show-toplevel`、`git status --short --branch`、`git remote -v`；
2. 如果是有效 Git 仓库，执行 `git fetch --all --prune`，仅在工作树安全时执行 `git pull --ff-only`；
3. 不使用会覆盖本地改动的 pull、reset、checkout 或 clean；
4. 阅读 `CLAUDE.md`、`docs/design.md`、现有 ADR、README、CONTRIBUTING、HANDOVER 和当前 Issue；缺失文件记录为待办，不虚构内容；
5. 检查当前分支、未提交改动、已有代码、测试、CI 和最近提交；
6. 输出接管报告：仓库状态、当前版本、已完成内容、架构边界、风险、阻塞项和建议任务图；
7. 首次接管报告完成后，再按 Issue 或用户目标自主开发。

如果目录不是有效 Git 仓库，不删除现有文件。报告该事实；本地 `git init`、建立 feature branch等可逆操作可以自主进行，但首次建立/推送远端 `main` 属重要操作，必须请求一次确认。

## 5. 自主工作原则

除“必须确认”事项外，不要因为普通实现选择反复询问用户。先检查仓库和文档，做最合理、最小范围、可回滚的决定，完成实现与验证，并在交接记录假设。

### 默认自主执行，不需要逐步确认

- 搜索、阅读和分析项目代码、文档、测试、Git 历史；
- 读取任务范围内的本机 HCL 项目格式、脱敏日志和只读运行信息；
- 创建短期 feature/fix/docs/refactor 分支；
- 新建或修改任务范围内的源码、测试、文档、示例和合成 fixtures；
- 修复 lint、类型、测试、构建和文档问题；
- 运行测试、MCP Inspector、构建、静态检查和安全扫描；
- 安装锁文件已有依赖；添加小型、维护活跃、许可证兼容且确有必要的依赖；
- 执行非破坏性 Git 操作：status、diff、log、fetch、pull --ff-only、add、commit；
- push 当前非保护 feature 分支，创建或更新 Draft PR；
- 根据 CI 结果继续修复，直到通过或出现真实阻塞；
- 更新 README、CHANGELOG、兼容矩阵和 HANDOVER；
- 对低风险细节作出合理假设并明确记录。

### 必须确认的重要事项

仅在以下情况暂停并请求用户决策：

- 首次创建或推送远端 `main`；
- 合并 PR 到 `main`、关闭重大 Issue、创建/删除 tag 或 GitHub Release；
- 发布 PyPI、MCP Registry、MCPB、容器、安装包或其他公开制品；
- force push、rebase 已推送共享历史、删除远端分支、`reset --hard`、`clean -fd` 等破坏性 Git 操作；
- 删除主要模块、批量迁移数据或进行难以回滚的仓库级重构；
- 改变项目名称、许可证、公共 MCP Tool Schema、稳定错误码、Port 契约或默认安全策略；
- 新增重量级/低信誉/许可证不兼容的生产依赖，或改变 Python/MCP SDK 主版本；
- 使用、复制或实现未公开的 HCL 私有协议，或触及许可边界；
- 对真实设备或用户 HCL 实验执行配置写入、save、reboot、reset、delete、format、批量启停等有状态操作；
- 读取、传输或写入真实凭据、Token、私钥和其他 Secret；
- 创建付费云资源、修改外部生产系统、发送外部消息或产生费用；
- 需求存在两种会显著改变产品方向且无法从现有文档判断的方案。

### 永远禁止

- 提交 HCL EXE/DLL、VMDK/VDI、厂商帮助文档、图标或其他专有资产；
- 提交真实拓扑、真实设备配置、用户名、口令、Token、私钥或未脱敏日志；
- 反编译、反汇编、复制 HCL 代码或发布其私有 wire protocol；
- 为让 CI 通过而删除测试、放宽安全策略、吞掉所有异常或关闭类型检查；
- 在解析 HCL 文件时使用 `eval`/`exec`；
- 将设备输出、文件内容或用户输入直接拼接进 Shell/CLI 命令；
- 直接 push 或 force push 受保护的 `main`；
- 丢弃、覆盖或回滚不属于当前任务的用户改动。

Claude Code 自身的工具权限和操作系统安全提示始终优先。本节减少的是对普通实现细节的对话式确认，不用于绕过平台权限。

## 6. 架构边界

依赖方向必须保持：

```text
mcp -> application -> ports <- adapters/infrastructure
                    domain
```

模块职责：

- `domain/`：纯领域模型、值对象、稳定错误；不能依赖 MCP、网络、文件或数据库；
- `ports/`：外部能力 Protocol/ABC；只依赖 domain；
- `application/`：用例编排、锁、缓存、变更计划和 Job；只面向 Port；
- `mcp/`：Tool/Resource/Prompt Schema、错误映射和 Composition Root；
- `adapters/hcl/`：用户 HCL 项目解析、只读运行时发现；
- `adapters/comware/`：Telnet/SSH、prompt 状态机和输出解析；
- `infrastructure/`：配置、策略、审计、Secret、日志和指标。

强制规则：

1. 跨模块只传 domain 强类型对象，不传裸 dict、第三方 session、socket 或打开的文件；
2. Application 不导入具体 adapter；
3. MCP Tool 不直接读文件、连 Telnet/SSH 或访问数据库；
4. 只有 `mcp/server.py` 负责依赖装配；
5. Adapter 将第三方异常转换为稳定领域错误；
6. 新 adapter 不改变既有 Tool Schema；
7. 公共契约变化必须有 contract test 和 ADR。

核心 Port：`ProjectRepository`、`RuntimeDiscovery`、`DeviceTransport`、`CommandParser`、`PolicyEngine`、`ApprovalProvider`、`AuditSink`、`JobStore`、`SecretProvider`。

## 7. 安全与 HCL 边界

- 默认模式是 `read_only`；服务端策略不能依赖 MCP Client 的确认 UI；
- v0.1 只开放项目/拓扑查询、facts、接口、配置读取、受控 display、ping/tracert；
- 配置写入采用 plan → diff → approval → apply → verify，且默认关闭；
- HCL 5.10.x 的用户项目文件和 loopback console 是首期互操作边界；
- HCL 内部控制端口不是公共 API，不实现、不代理、不扫描局域网；
- console Telnet 只连接 `127.0.0.1`，真实设备优先 SSH 并验证 host key；
- 每台设备使用独占会话锁，命令有硬超时和输出上限；
- 设备 banner、description、配置和命令输出全部视为不可信数据；
- 测试只使用自行构造的 HCL 项目和设备输出，真实 HCL 集成测试留在合规的本机环境。

## 8. Git 工作方式

采用 GitHub Flow，不保留长期 `develop`：

- `feat/<issue>-<slug>`
- `fix/<issue>-<slug>`
- `docs/<issue>-<slug>`
- `refactor/<issue>-<slug>`

一个 Issue 对应一个短分支和一个 PR。默认 squash merge。PR 标题和 commit 使用 Conventional Commits，例如：

```text
feat(hcl): parse HCL project topology
fix(comware): recover prompt after timeout
test(mcp): add tool schema contract snapshots
docs(adr): record console discovery boundary
```

开发循环：

1. 同步 `main`；
2. 创建任务分支；
3. 先写/更新契约和失败测试；
4. 完成最小实现；
5. 运行与变更相称的检查；
6. 更新文档和 CHANGELOG；
7. 检查 diff 中的 Secret、专有文件和无关改动；
8. 分成逻辑清晰的 commit；
9. push feature 分支并创建/更新 Draft PR；
10. 修复 CI，重要合并和发布等待用户确认。

不要在脏工作树上覆盖已有改动。发现不属于当前任务的修改时保留它们，并只暂存自己的文件或 hunk。

## 9. Agent Team 规则

Agent Team 只用于能够按文件边界并行的复杂任务。简单或顺序任务由单一 Agent 完成，避免无意义的并行和 Token 消耗。

推荐角色：

- Team Lead：任务拆分、共享文件、Git、集成和最终验证；
- Contract Architect：`domain/`、`ports/`、`tests/contract/`；
- MCP API Engineer：`mcp/tools/`、resources、prompts；
- HCL Adapter Engineer：`adapters/hcl/` 及对应测试；
- Comware Driver Engineer：`adapters/comware/` 及对应测试；
- Security Reviewer：policy、脱敏、安全测试和独立复核；
- QA/Release Engineer：integration/e2e、CI、packaging。

不需要每次同时启动全部角色。Team Lead 根据任务选择 3～5 个最小团队。

每项任务必须给出：Task ID、Objective、Owned files、Forbidden files/actions、依赖、验收测试和交接对象。teammate 只能编辑 Owned files；需要跨界修改时通知 Lead。

Agent Team 共享一个工作树时：

- 一个 Team 只处理一个 Issue/feature branch；
- 不允许两个 teammate 编辑同一个文件；
- teammate 不 commit、push、merge、rebase 或修改 lockfile；
- Team Lead 独占 `pyproject.toml`、`uv.lock`、`mcp/server.py`、公共 Port、根文档和 Git 操作；
- Lead 等待所有 teammate 完成后统一检查、暂存、提交和 push。

跨 Issue 并行使用独立 Git worktree/独立 Claude session，不在同一工作树切换多个 Agent 分支。GitHub Issue、commit 和 CI 是长期事实来源，Agent Team 本地 task list 不是。

## 10. 测试与质量门禁

任何实现至少验证：

- Ruff format/check；
- strict typecheck；
- unit tests；
- MCP Tool/Port contract tests；
- 与改动相关的 Windows integration tests；
- wheel/sdist build 和安装 smoke test；
- Secret、依赖、许可证和危险文件扫描。

关键测试场景：

- HCL 未安装、项目不存在、项目损坏、路径穿越；
- 设备未运行、端口占用、连接中断、prompt 超时或改名；
- CLI 分页、回显、启动噪声和输出截断；
- 换行、多命令、管道、重定向和危险命令注入；
- 并发访问同一设备；
- 敏感配置脱敏；
- stdout 仅包含合法 MCP JSON-RPC，日志只写 stderr。

无法运行真实 HCL 测试时，不伪造“已通过”。运行 fake/synthetic 测试并清楚说明未验证项。

## 11. 文档与交接

文档和代码是同一个交付。行为变化必须在同一 PR 更新对应文档。

阶段结束更新 `docs/HANDOVER.md`；如果文件不存在则创建。至少包含：

```text
当前版本/分支：
目标 Issue/PR：
完成内容：
修改文件：
关键决策/ADR：
Git commits：
执行的测试与精确结果：
未执行的验证：
已知问题和风险：
下一阶段任务：
接管所需命令：
```

不要记录 Secret、绝对用户路径或可识别的真实设备配置。新 Agent 应仅通过仓库文件、Git 历史和 Issue 即可继续开发。

## 12. 版本推进

以 `docs/design.md` 的版本表为准：

- `v0.0.1`：仓库治理、工程骨架、CI、ADR；
- `v0.1.0-alpha.1`：合成项目和 fake console 的只读纵向切片；
- `v0.1.0-beta.1`：本机 HCL 5.10.x + console Telnet beta；
- `v0.1.0`：只读 MVP、Claude/Cursor stdio、PyPI；
- `v0.2.0`：SSH、plan/apply、审批、备份；
- `v0.3.0`：NETCONF、更多 parser、Resources/Prompts；
- `v0.5.0`：Streamable HTTP、OAuth 和企业能力 beta；
- `v1.0.0`：稳定 Tool/Port/Error 契约。

不要一次实现全部路线。每个版本先完成最小纵向切片，再扩大工具和设备覆盖。

## 13. 输出与行为风格

- 与用户和中文文档使用简体中文；代码标识、commit、错误码和 API 使用英文；
- 先报告结果，再说明关键证据、风险和下一步；
- 不输出冗长的逐命令流水账；
- 普通细节自主决定，重要事项一次性集中询问；
- 遇到阻塞先尝试安全替代方案，不因轻微不确定性停止工作；
- 不声称完成未验证的工作，不隐藏失败测试；
- 保持改动小而完整，不顺手重构无关代码。

## 14. 当前首次任务

如果仓库仍处于接管/初始化阶段：

1. 检查 Git 和远程仓库状态；
2. 阅读 `docs/design.md`；
3. 盘点实际文件与设计目标的差距；
4. 生成 Agent Team 开发计划和首批 GitHub Issues；
5. 只提交接管分析，不直接实现 MCP 业务代码；
6. 等用户确认首次仓库 bootstrap/main 方案后，进入默认自主开发模式。

一旦 bootstrap 已确认并完成，本节不再阻止按已批准 Issue 自主编码。
