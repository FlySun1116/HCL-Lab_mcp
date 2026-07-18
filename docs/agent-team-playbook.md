# HCL-Lab_mcp Agent Team Playbook

本文说明如何在一个 Issue、一个 feature 分支和一个共享工作树内安全使用 Claude Agent Team。根规则以 `CLAUDE.md` 为准，架构和版本范围以 `docs/design.md` 与已接受 ADR 为准。

## 1. 启用与边界

1. Agent Teams 是可选实验能力，项目构建、测试和发布不得依赖其本地运行状态。
2. 复制 `.claude/settings.example.json` 到个人设置时先审查内容；不要提交个人 `settings.local.json`。
3. 示例使用 `in-process` teammate 和默认权限模式，不启用 bypass/dangerous permissions。
4. 一个 Team 只处理一个 Issue/feature branch。跨 Issue 并行必须使用独立 worktree/独立会话。
5. Team Lead + 3～5 个最小必要 teammate 即可；简单或强顺序任务不用 Team。
6. teammate 不 commit、push、merge、rebase、tag 或发布。GitHub Issue、commit 和 CI 才是长期事实来源。

## 2. 启动前检查

Team Lead 在派发任务前必须：

- 阅读 `CLAUDE.md`、`docs/design.md`、相关 ADR、Issue 和当前 HANDOVER。
- 检查分支、工作树、已有改动和 CI；已有用户改动不得覆盖或重新归属。
- 冻结公共 Tool、Port、稳定错误码、默认策略和版本范围；变化需 ADR/重要决策。
- 建立文件所有权表，确保两个并行任务没有同一文件、共享 fixture 或生成文件交集。
- 标出真实 HCL、客户端 UI、仓库规则和公开发布等 human-required 验收。

## 3. 任务卡模板

Team Lead 必须逐项填写，禁止使用“相关文件”等模糊范围：

```text
Task ID / GitHub Issue:
Objective: 单一、可验证的结果
Risk: low | medium | high
Owner role:
Owned files: 精确路径或互不重叠的 glob
Read-only context files:
Forbidden files/actions:
Input contracts and dependency tasks:
Normal acceptance scenario:
Failure acceptance scenario:
Security acceptance scenario:
Required commands:
Handoff recipient:
Human decision points:
```

teammate 接受任务前先比较 Owned files 与当前工作树；发现重叠或缺少输入契约时不编辑，立即通知 Lead。

## 4. 默认角色与文件边界

| 角色 | 默认 Owned files | 主要禁止边界 |
|---|---|---|
| Team Lead | `pyproject.toml`、`uv.lock`、`mcp/server.py`、共享/根文件、最终集成 | 未授权 merge/tag/Release/PyPI；不替 teammate 改独占文件 |
| Contract Architect | `domain/**`、`ports/**`、`tests/contract/**`、授权 ADR 草案 | 不实现 adapter；不单方面改变公共契约 |
| MCP API Engineer | `mcp/tools/**`、`mcp/resources/**`、`mcp/prompts/**` | 不读文件/连设备/访问数据库；不改组合根 |
| HCL Adapter Engineer | `adapters/hcl/**`、对应 unit tests 和合成 HCL fixtures | 不碰私有协议、用户项目、HCL 安装目录或非 loopback |
| Comware Driver Engineer | `adapters/comware/**`、对应 unit tests/合成输出 | 不改策略，不新增写 Tool，不使用真实凭据 |
| Security Reviewer | policy、授权脱敏/审计安全文件、安全测试/文档 | 不批准自己实现，不放宽安全门禁 |
| QA/Release Engineer | integration/e2e、授权 workflows/packaging/兼容文档 | 不改业务实现/公共契约，不执行公开发布 |

任务卡可缩小范围，不能默默扩大范围。需要同一文件的两个角色必须改为顺序任务并指定唯一 Owner。

## 5. 并行边界

契约冻结后，以下工作通常可以并行：

- MCP API：只依赖 fake Port，不接具体 adapter。
- HCL adapter：只实现已冻结 ProjectRepository/RuntimeDiscovery。
- Comware driver：只实现已冻结 DeviceTransport/CommandParser。
- Security：只实现已冻结 Policy/Audit 边界；独立发布复核必须由非作者完成。

以下内容必须由 Lead 串行处理：

- `mcp/server.py` 组合根与跨模块 application 接线。
- `pyproject.toml`、`uv.lock`、公共 Port、根文档和共享 fixture。
- 解决冲突、最终格式化、全量门禁、Git 和 Draft PR。
- 公共契约、默认安全策略、版本和许可方向的决策。

## 6. 推荐集成顺序

1. **Contract**：冻结 domain、Port、错误码与 contract tests。
2. **Parallel implementation**：MCP、HCL、Comware、Security 在不重叠文件内实现并跑聚焦测试。
3. **Lead integration**：核对每份 handoff 和 diff，接入 application/composition root。
4. **QA**：官方 MCP Client、Windows fake console、覆盖率、双制品和兼容矩阵。
5. **Independent Security review**：检查命令策略、脱敏、审计、供应链和专有资产边界。
6. **Lead finalization**：全量门禁、HANDOVER、变更摘要和允许范围内的 Draft PR。
7. **Human gate**：merge、branch protection、tag、Release、PyPI、真实设备写入等重要动作。

上游契约变化后，Lead 必须使依赖任务失效并重新验收，不能继续使用旧假设集成。

## 7. 交接格式

每个 teammate 完成或阻塞时返回：

```text
Status: complete | blocked
Task ID:
Files changed:
Behavior implemented:
Tests added and exact results:
Required checks not run and why:
Contract/ADR impact:
Security or compatibility risks:
Known limitations:
Handoff recipient:
Recommended follow-up:
```

Lead 必须验证实际 diff、文件所有权和测试输出。仅声明“已完成”、没有精确测试结果、改变契约未报告或留下未解释 TODO 的交接应被拒绝。

## 8. 失败与升级规则

遇到以下情况立即停止相关编辑并通知 Team Lead：

- 需要修改任务卡之外的文件或与其他 teammate 发生所有权冲突。
- 公共 Tool Schema、Port、稳定错误码、版本、许可证或默认安全策略需要变化。
- 发现 Secret、真实拓扑/配置、厂商资产、未脱敏日志或疑似许可问题。
- 需要 HCL 私有协议、非 loopback 扫描、真实凭据或真实设备/HCL 有状态写入。
- 测试只能通过删除用例、降低覆盖率、关闭类型检查、吞异常或放宽策略。
- 工作树出现不明改动、共享状态丢失、同文件冲突或 Team 状态无法恢复。

Lead 能在既有范围内通过重分配唯一 Owner、缩小任务或增加安全测试解决时可继续。以下情况集中升级给人类维护者：

- 两种方案会显著改变产品方向且现有设计无法裁决。
- merge `main`、改写共享历史、tag/Release/PyPI、仓库保护规则或其他外部发布动作。
- 真实设备写操作、真实 Secret、专有接口/资产、费用或生产系统变更。

若 Agent Team 本地任务/mailbox 异常或需要跨天恢复，停止 Team，保留工作树，不删除未知 worktree；把状态写入 Issue/HANDOVER，改用独立 worktree 会话继续。

## 9. 最低完成门槛

按变更范围运行并记录：

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest tests/contract -v
uv run --locked pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
uv run --locked python scripts/check_docs.py .
uv run --locked python scripts/check_repository.py .
uv build --clear
uv run --locked python scripts/check_distribution.py dist
```

不能运行真实 HCL、Claude Desktop/Cursor UI 或公开 registry 测试时，明确记录为 `not tested`/`human-required`，不得用 synthetic、fake 或官方 SDK 结果替代。
