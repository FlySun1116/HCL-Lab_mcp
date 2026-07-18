# HCL-Lab_mcp 兼容矩阵

本页是 `config/compatibility.yaml` 的人类可读说明。YAML 是机器事实源，契约测试负责校验字段、状态、证据路径和保守声明规则。兼容状态描述的是一条具体“版本 × 型号 × 能力 × transport”证据，不代表整个设备族均已支持。

## 状态语义

矩阵只允许以下四种状态：

| 状态 | 含义 | 能否证明真实正向设备能力 |
|---|---|---|
| `real-pass` | 在合法本机环境中对真实 HCL 项目或运行设备完成了该条能力的正向验证，并留下脱敏外部说明或非 fixture 仓库证据 | 仅能证明该记录声明的能力 |
| `real-negative` | 真实 HCL 环境执行了负向路径，例如设备未运行并稳定返回 `DEVICE_NOT_RUNNING` | 不能；不得升级为真实正向结果 |
| `synthetic-pass` | 合成 fixture、parser 样本或 fake console 通过 | 不能；只证明项目自建测试边界 |
| `not-tested` | 没有足以判断该能力的证据 | 不能 |

禁止使用 `supported`、`pass`、`partial` 等模糊状态。真实正向记录不得只引用 `tests/fixtures/`；不能运行真实环境时必须保留 `synthetic-pass` 或 `not-tested`。

## 当前矩阵

| 记录 ID | HCL | 设备/模型 | 能力 | Transport | 状态 | 结论边界 |
|---|---|---|---|---|---|---|
| `hcl-5103-s6850-project-parsing` | 5.10.3 | S-series / S6850 | 项目和拓扑解析 | filesystem | `real-pass` | 真实项目元数据可解析；不证明 console 命令成功 |
| `hcl-5103-s6850-runtime-not-running` | 5.10.3 | S-series / S6850 | runtime 与命令前置条件 | console Telnet | `real-negative` | 设备未运行时稳定返回 `DEVICE_NOT_RUNNING`；无正向 endpoint |
| `hcl-5103-s6850-display-parser` | 5.10.3 | S-series / S6850 | `display version` parser | synthetic output | `synthetic-pass` | 仅合成输出 parser |
| `hcl-5103-msr36-display-parser` | 5.10.3 | MSR / MSR36-20 | `display version` parser | synthetic output | `synthetic-pass` | 仅合成输出 parser |
| `hcl-5103-s6850-fake-console` | 5.10.3 | S-series / S6850 | 只读 console session | fake Telnet | `synthetic-pass` | fake Comware server，不是 HCL 设备 |
| `hcl-5103-vsr-read-only-console` | 5.10.3 | VSR / VSR-88 | 只读 console session | console Telnet | `not-tested` | 当前没有 fixture 或真实执行证据 |

## 已知事实

- 本机 HCL 5.10.3 项目解析是真实只读观察：能发现项目、设备和链路，并识别 S6850 candidate。
- 最新真实 runtime 检查时设备未运行、没有 verified endpoint；两条 display 调用只证明 `DEVICE_NOT_RUNNING` 负向行为。
- S6850/MSR36 的 `display version` parser 和 S6850 标识的 console session 使用项目自建输出或 fake server，只能标记 `synthetic-pass`。
- VSR 没有足够证据，保持 `not-tested`。不得根据通用 Comware 相似性推断兼容。

## 更新规则

每条 `entries` 记录必须包含：

- 唯一 `id`；
- `hcl_version`、`device_family` 和至少一个 `models` 值；
- 单一、可复现的 `capability` 与 `transport`；
- 四值枚举中的 `status`；
- 至少一个存在的仓库证据路径，或非空 `external` 脱敏说明；
- 至少一条 `limitations`，说明不能从该证据推导什么。

新增真实验证时只记录 HCL/Client 版本、设备族/模型、只读能力、稳定错误码和脱敏结论。不要提交真实项目名称、绝对路径、原始日志、设备配置、用户名或凭据。真实设备写入、HCL 生命周期操作、tag/Release/PyPI 不属于兼容矩阵更新权限。

## 发布判定

`real-negative`、`synthetic-pass` 和 `not-tested` 不能满足相应真实正向发布门槛。当前矩阵仍缺运行中 HCL 设备的 `display version` 与 `display ip interface brief` 正向记录，以及 VSR 基础验证；因此本页不能作为宣布最终 `v0.1.0` 完成的依据。
