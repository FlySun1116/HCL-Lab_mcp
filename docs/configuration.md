# 配置指南

本文适用于未发布的 `0.1.0-beta.2` 候选。v0.1 只支持本机 `stdio`、HCL 用户项目文件和 loopback `console_telnet`；SSH、HTTP、NETCONF 与设备写操作不能通过配置提前启用。

## 配置优先级

同一字段出现多次时，优先级从高到低为：

1. CLI 参数（`--config`、`--projects-dir`）；
2. `H3C_HCL_MCP__...` 嵌套环境变量；
3. 显式 `--config` 或 `H3C_HCL_MCP_CONFIG` 指向的 YAML/JSON；
4. `%LOCALAPPDATA%\h3c-hcl-mcp\config.yaml`、`.yml`、`.json`；
5. 服务端安全默认值。

显式选择的配置不存在、无法解析或包含未知字段时，Server 会在 MCP 协议启动前失败；未选择配置时可以使用只读默认值启动。

## 最小配置

```yaml
hcl:
  projects_dirs:
    - D:\HCL-Labs\Projects
```

也可以不创建配置文件，通过 CLI 指定：

```powershell
.venv\Scripts\h3c-hcl-mcp.exe --projects-dir "D:\HCL-Labs\Projects"
```

数组型环境变量必须使用 JSON：

```powershell
$env:H3C_HCL_MCP__HCL__PROJECTS_DIRS='["D:\\HCL-Labs\\Projects"]'
```

## v0.1 字段

| 分组 | 关键字段 | 约束 |
|---|---|---|
| `server` | `transport` | 必须是 `stdio` |
| `server` | `max_tool_seconds` | 1–600 秒，覆盖所有合法 Tool |
| `server` | `max_output_chars` | 设备 console 捕获上限 |
| `server` | `max_tool_result_bytes` | 最终 MCP UTF-8 返回硬上限 |
| `hcl` | `projects_dirs` | 只读扫描的项目根目录列表 |
| `hcl.runtime_discovery` | `console_host` | 必须是 loopback |
| `hcl.runtime_discovery` | `probe_timeout_seconds` | bounded prompt probe 超时 |
| `devices` | `preferred_transports` | v0.1 必须精确为 `["console_telnet"]` |
| `devices` | `per_device_concurrency` | v0.1 必须为 `1` |
| `policy` | `allow_display_prefixes` | 只能收紧内置 display allowlist |
| `policy` | `deny_patterns` | 额外的不区分大小写字面拒绝项 |
| `policy` | `max_concurrent_sessions` | 进程级 session 上限 |
| `audit` | `enabled` | 默认 `true`；关闭时使用空审计实现 |
| `audit` | `database` | SQLite 文件或目录；空值使用本机默认路径 |
| `audit` | `retention_days` | 1–365 天；启动及追加事件时清理过期记录 |

完整示例见 [YAML](../config/config.example.yaml) 与 [JSON](../config/config.example.json)。路径支持 `~` 和 `${ENV_NAME}` 展开。

## 凭据规则

v0.1 console discovery 不回答用户名或密码提示，也没有可用的 SSH transport。不要把密码、Token、私钥或 SNMP community 写入仓库、MCP 客户端 JSON 或项目配置；未来 adapter 只能引用环境变量、系统凭据库或外部 Secret Provider。

## MCP Client

Claude Desktop、Cursor 与 VS Code 示例分别位于 [examples](../examples)。当前版本尚未发布 PyPI，`command` 必须指向源码虚拟环境中的 `h3c-hcl-mcp` 可执行文件；不要使用尚未存在的公共 `uvx` 包。

## 验证

```powershell
uv run h3c-hcl-mcp --version
uv run pytest tests/unit/infrastructure/test_settings.py tests/integration/test_stdio_client.py -q
uv run python scripts/check_docs.py .
```

配置错误必须只写 stderr，stdout 始终保留给 MCP JSON-RPC。
