# 变更记录

本文件只记录**已部署到生产并验收通过**的版本批次。版本号规则、准入清单与发版步骤见
[`docs/teamflow/20261114-cicd/RELEASE.md`](docs/teamflow/20261114-cicd/RELEASE.md)。

格式：`## [vX.Y.Z] - YYYY-MM-DD`，条目按「新增 / 修复 / 运维与安全 / 文档 / 验收」分组。
未发版的内容留在 `dev` 上，不写进本文件；合入 `master` 前由 CI 的 `Release gate`
校验本文件存在对应标题。tag 指向的 commit 即发版时生产实际运行的 `dev` HEAD。

## [v0.1.0] - 2026-11-14

首个受控发布基线。确立 `master`（受保护发布主干）+ `dev`（开发与自动部署）分支模型，
并把 2026-11-14 全天的公网部署成果收编为一个可追溯的版本。

### 新增

- BYOK 国内厂商预设：8 家服务商 + 自定义，设置页可选厂商并自动带出 Base URL 与模型提示。
- GitHub Actions 推 SSH 自动部署：push `dev` → 双门禁 → 受限 deploy key → 服务器部署 / 失败回滚。
- 纯 IP 的 Let's Encrypt 正式证书（SAN `IP Address:43.166.23.144`）+ 每 12 小时自动续期。
- 版本发布流程与 `dev → master` 的 `Release gate` 合入门禁（本版本引入）。

### 修复

- 用户自带 AI「测试连接」把有效 Key 误报为无效：JSON 模式探测语缺 `json` 字样，且 4xx 归因笼统。
- 用户自带 AI 配置的盲 SSRF：拒绝环回 / 内网 / `169.254.169.254`，测试连接超时独立收紧到 8s。
- 部署脚本顶层 `umask 077` 让 checkout 出的源码变 600，进镜像后非 root backend 崩溃、且回滚同样失效。

### 运维与安全

- 公网入口把点文件与备份 / 凭据后缀钉成 404；PG 口令轮换；每日 `pg_dump -Fc` 备份 + 恢复演练。
- 远端分支清理：删除 10 个 dependabot 分支与已停用的 `feat/dev-skill-coach`，只留 `master` + `dev`。
- 证书续期、数据库备份两条 cron 统一 `umask 077`；运行时文件与日志保持 600 / 700。

### 文档

- 公网 443 外部验收报告、CD 可观测性指南、CD 事故复盘（`CD.md` §13）、版本发布规则。

### 验收

- CI `frontend` / `backend` 双门禁全绿；公网 `verify_public.py` **44/44**、0 失败。
- 四容器 healthy、证书链可信、服务器工作树 clean、`deploy-state` 与 `dev` HEAD 一致。
