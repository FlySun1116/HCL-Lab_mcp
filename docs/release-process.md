# 发布流程

本流程描述如何把已验证候选发布为 PyPI 包和 GitHub Release；新增 workflow 不等于已授权发布。merge、版本切换、签名 tag、GitHub Release 和 PyPI 上传始终由维护者明确批准。

## 一次性仓库设置

维护者在首次正式发布前完成：

1. 为 `main` 启用 branch protection，禁止直接 push/force push，要求 PR 审核。
2. 把 CI、Security、Documentation 的 lint、type、contract、Windows、package、secret、dependency、CodeQL 和 docs jobs 设为 required checks。
3. 启用 GitHub Private Vulnerability Reporting。
4. 在 PyPI 为 `FlySun1116/HCL-Lab_mcp` 配置 Trusted Publisher。
5. 创建 GitHub Environment `pypi`，配置 required reviewer，并仅在准备发布时设置环境变量 `PYPI_RELEASE_ENABLED=true`。

如果 `pypi` 环境或显式变量缺失，release workflow 会在 OIDC 上传前失败。

## 候选退出条件

- 设计文档的 v0.1 十项验收逐项有证据。
- 真实运行 HCL 至少成功执行 `display version` 和 `display ip interface brief`，仅保存脱敏摘要。
- Claude Desktop 与 Cursor 均发现同一组 Tool 并调用 `server_health`。
- [兼容矩阵](compatibility.md) 对 S6850/VSR/MSR 使用 `real-pass`、`real-negative`、`synthetic-pass`、`not-tested` 明确标注，不能把合成证据写成真实通过。
- 完整测试、85% coverage、漏洞/许可证、CodeQL、仓库与制品 allowlist、wheel/sdist clean-install 全部通过。
- CHANGELOG、版本模块、`pyproject.toml`、README 和迁移说明一致。

## 本地预检

```powershell
uv sync --locked --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --cov=h3c_hcl_mcp --cov-report=term-missing --cov-fail-under=85
uv run python scripts/check_docs.py .
uv build --clear
uv run python scripts/check_distribution.py dist
```

运行依赖漏洞审计使用锁文件导出的带哈希 requirements；许可证策略拒绝 GPL/AGPL 运行或开发依赖。

## 触发发布

Release workflow 只响应 `v*` tag，并验证：

1. tag commit 是 `origin/main` 的祖先；
2. tag 是 GitHub 可验证的签名 annotated tag；
3. tag 名与服务版本完全一致；
4. 完整质量门禁、构建与归档 allowlist 通过。

维护者批准后，从已保护 `main` 创建签名 tag；beta 示例为 `v0.1.0-beta.2`，正式版为 `v0.1.0`。不要覆盖或复用已有 tag。

workflow 将：

- 构建 wheel 与 sdist；
- 生成 CycloneDX JSON SBOM 和 `SHA256SUMS`；
- 写入 GitHub build provenance attestation；
- 通过 PyPI OIDC Trusted Publishing 上传并生成 PEP 740 attestations；
- PyPI 成功后创建 GitHub Release 并附全部资产。

## 发布后验证

在没有源码目录和 `PYTHONPATH` 的全新 Python 3.12 环境中：

```powershell
uvx --from h3c-hcl-mcp==0.1.0 h3c-hcl-mcp --version
gh attestation verify <wheel> --repo FlySun1116/HCL-Lab_mcp
Get-FileHash <wheel> -Algorithm SHA256
```

随后逐字验证 README 的 Claude Desktop、Cursor 和 CLI 安装路径，并核对 PyPI 元数据、许可证、SBOM 与 GitHub Release hash。

## 失败与撤回

- build/security 失败：不创建 tag 替代品，不绕过门禁；修复后创建新的预发布版本。
- PyPI 上传前失败：保持 workflow 失败，不手工用长期 Token 绕过 Trusted Publishing。
- PyPI 已发布但发现严重问题：按 PyPI 能力 yank，不删除/覆盖制品；创建安全修复版本和 GitHub Advisory。
- GitHub Release 失败但 PyPI 已成功：核对相同不可变资产后由维护者重跑失败 job，不重新构建上传不同字节。
