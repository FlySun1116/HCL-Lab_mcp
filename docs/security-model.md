# 安全模型

## 范围与资产

v0.1 保护的主要资产包括：本机 HCL 项目与配置快照、loopback console、设备输出、审计数据库、MCP Client 请求，以及用户未来可能提供的凭据。HCL 文件、日志、console banner、设备配置和 Tool 参数都视为不可信输入。

## 信任边界

```text
MCP Client
    │ untrusted arguments
    ▼
MCP validation → policy → application use case → Port
                                              │
                         untrusted HCL files/logs/device output
                                              ▼
                                   HCL/Comware adapters
```

任何 adapter 数据返回客户端前仍需通过 MCP 边界的结果预算与脱敏。设备文本不能成为新的命令、策略或模型指令。

## 核心控制

- v0.1 不注册配置写入、save、reboot、reset、HCL lifecycle、SSH、NETCONF 或 HTTP Tool。
- console endpoint 必须来自目标项目/device 的显式日志绑定，并通过 loopback TCP/Telnet/Comware prompt probe；超限日志的未读区间是状态信任边界，之后必须重新看到明确绑定。
- `h3c_run_display` 拒绝换行、控制字符、管道、重定向、多命令和危险前缀；配置只能收紧规则。
- 每设备独占 session，全局 session、空闲时间、命令次数、连接/命令超时均有硬上限。
- 项目 ID、`project.json`、`.net` 与配置引用都必须 resolve 后留在项目根；元数据文件有读取字节上限。
- 所有公共字符串、日志参数、异常文本、console 捕获和最终 MCP 结果都有独立上限；生产日志还统一移除 Windows、UNC、file URI 与任意 POSIX 绝对路径，同时保留 HTTPS URL。无法与本机绝对路径可靠区分的根相对 `/...` 字符串按保守隐私策略脱敏；CR/LF、终端控制符和 Unicode 行分隔符输出为可见转义，不能注入伪日志行。
- 配置读取强制脱敏；v0.1 的 `redact=false` 返回 `POLICY_DENIED`。
- 审计开启时 fail closed；`retention_days` 在数据库初始化和追加事件时执行。
- wheel/sdist 采用成员 allowlist；仓库层安全门禁拒绝 Secret、专有资产、镜像和大型二进制。
- MCP SDK 暂时限制在已验证的 `>=1.28,<1.29`，因为当前中间件接线仍依赖 FastMCP 1.28 的内部 Tool manager；升级必须先通过完整 contract/stdio 测试。

## 许可边界

项目只读取用户合法安装产生的项目文件、文本日志和 loopback console。不扫描局域网，不控制 HCL/VirtualBox，不实现或代理未公开 HCL 私有协议，也不分发 HCL、Comware 镜像、厂商帮助文件或图标。

## 失败语义

已知外部失败映射为稳定领域错误，例如 `PROJECT_NOT_FOUND`、`PROJECT_DAMAGED`、`DEVICE_NOT_RUNNING`、`CONNECTION_FAILED`、`PROMPT_NOT_FOUND`、`TIMEOUT`、`POLICY_DENIED` 和 `OUTPUT_TOO_LARGE`。内部异常不向客户端返回 traceback、本机路径或原始 buffer；每个错误包含可关联 `request_id`。

## 已知限制

- 真实运行设备的两条 display 正向链路仍需本机 HCL 验证。
- Claude Desktop 与 Cursor GUI 仍需真实客户端证据。
- GitHub Private Vulnerability Reporting 和 `main` required checks 必须由维护者在发布前启用。
- HTTP/OAuth、写审批和 Secret Provider 属后续版本，不应以占位实现宣称安全可用。

漏洞报告流程见 [SECURITY.md](../SECURITY.md)，发布门禁见 [release-process.md](release-process.md)。
