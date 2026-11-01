# QA-REPORT · r10 容器化交付（docker compose 两容器 + nginx 同源反代 + 部署文档）

> **结论：可验收**。未发现 P0/P1/P2 缺陷；2 条 P3 观察项（均在 DEPLOY.md §7 已记录、属白名单外文档口径）。
> 验证方式：**全部实跑**（真实 Docker 29.9.2 / Compose v5.6.1 + 真实 DeepSeek Key），不做「文件存在即通过」。
> 自查脚本（5 个，共 789 行）：`logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_{http,ops,derive,surface,interface}.py`；
> 主路径回归复用 T5 的 `check_r10_deploy.py`（V1–V9）。

## 1. 范围与环境

- 分支 `feat/dev-skill-coach`（未提交），HEAD `8239f28`；交付面 9 个文件（新增 8 + `README.md`/`memory.md` 改动 21/1 行），白名单外零改动。
- 环境：Windows + Docker Desktop 29.9.2 / Compose v5.6.1；真实 DeepSeek Key 仅存在于 `backend/.env`（经 `env_file` 注入，未进任何交付文件与镜像层）。
- 环境限制（**非交付缺陷**）：`python -m ruff check` → `No module named ruff`（宿主未安装，与历史轮一致）；真实浏览器无法在沙箱启动（host crashpad 限制），视觉/交互项入 §5 人工补测清单。
- 数据隔离：QA 产生的画像/会话/报告写入命名卷 `code_learning_skillcoach-data`，未污染宿主 `backend/app.db`；临时容器 `qa-derive-*` 全部销毁，无残留。

## 2. 用例与结果

| 组 | 覆盖内容 | 结果 |
|---|---|---|
| V1–V9（T5 回归脚本，我复跑） | config / build / up / 健康 / 课程 / **真实 AI 全链路** / 重建保数据 / 零泄露 / git | **70/70 PASS** |
| Q1–Q7（反代边界） | 缓存矩阵、gzip、7 条 SPA 深路由、404/405 envelope、11.5MB 与 22MB 上传双层上限、冲击后仍健康 | **38/38 PASS** |
| O1–O5（运维承诺） | 缺 `.env` 仍可起、恢复即就绪、backend recreate 后 nginx、`WEB_PORT` 真换端口 | **22/22 PASS** |
| S1–S7（交付面） | 运行中 `nginx -T` 生效配置、镜像/容器零 Key、日志、备份 `compose cp`、git 卫生、文档口径 | **33/33 PASS** |
| I1–I6（接口一致性） | 构建输入存在、端口六处一致、路由 prefix 全覆盖、两份代理表一致、前端同源出口、文档命令真实存在 | **20/20 PASS** |
| V10（门禁） | `pytest` 348 passed / 1 skipped（349 collected，地板 ≥305） | PASS |
| V11（门禁） | typecheck 0 / lint **0 error 28 warning**（≤28）/ vitest **109 passed** / build OK（92 modules） | PASS |

**关键实测证据（摘要）**

1. 真实链路经浏览器入口 8080：上传 597 字 → `POST /api/resumes/{id}/profile` 200（skills 8 条、`source_quote` 逐字命中）→ `POST /api/interviews` 200（total=9）→ 12 轮作答至 `completed` → `POST /api/reports/generate` 200（shortfalls=3）。
2. 冷启动 `docker compose up -d --build` 一次通过；backend `healthy` 后才起 frontend —— `service_healthy` 门控真实生效（不是重试蒙过）。
3. `down`/`up`（不带 `-v`）后画像 `0e80b22217004465be0212c2a1928750`、报告 `rep-4b89862657` 前后不变；容器 `uid=10001`，`/data/app.db` 属主 `app:app`。
4. 上传双层上限：11.5MB → **应用侧** `{"error":{"code":"FILE_TOO_LARGE","message":"文件超过 10MB…"}}` 413（envelope 未被 HTML 破坏）；22MB → nginx HTML 413（合成上界的已知边界，A-6 口径）。
5. 缺 `backend/.env` 时 `docker compose config -q` 与 `up -d --wait` 均成功，`/health` 200 且 `ai_configured=false`（README/DEPLOY 对「新克隆」的承诺兑现）。
6. **默认 DeepSeek 推导**在真实镜像中三档实测：空 `AI_PROVIDER` + DeepSeek Key → `deepseek`；显式 `lmstudio` → `lmstudio`（不被 DeepSeek Key 抢）；两者皆无 → `legacy` 且 `ai_configured=false`。
7. `WEB_PORT=8099` 覆盖生效：8099/health 200 且 8080 不再监听，复位后 8080 恢复。
8. 运行中 `nginx -T`（生效配置，非源文件）含 `proxy_read_timeout/send 1300s`、`client_max_body_size 20m`、`try_files`、`/assets/ immutable`、`gzip on`，与仓库 `frontend/nginx.conf` 主体逐字一致。
9. 零泄露：两镜像 `docker history` 无 `sk-`；运行容器 `/app` 仅 `app/` + `requirements.txt`（无 `.env`/`.db`/`tests`）；日志无 Key、无栈、无 EACCES。
10. `docker compose cp backend:/data/app.db` 备份可用（274,432 bytes，SQLite 头正确，卷内 `pragma integrity_check=ok`）。

## 3. 架构核对（对照注入蓝图）

| 蓝图要求 | 核实方式 | 结果 |
|---|---|---|
| 不新增业务模块、`backend/app/**`、`frontend/src/**` 零改动 | `git status` 变更面 | 符合 |
| backend 非 root(10001)、`chown` 早于 `USER app`、urllib 探针 | Dockerfile + 容器 `id -u` + 运行态 healthy | 符合 |
| 分层 `requirements.txt` → pip → `COPY app/` | Dockerfile 顺序 | 符合（dev 实测改代码依赖层 CACHED） |
| 多阶段前端、最终镜像无 node | 镜像内 `command -v node` | 符合 |
| nginx SPA fallback / 同源反代 / 1300s / 20m / no-store / gzip | 运行中 `nginx -T` | 符合 |
| compose：`env_file` 引用 `required:false`、`environment` 只 `DB_PATH`、backend 不发布端口、`service_healthy` 门控 | `config --no-env-resolution` + 真跑 | 符合 |
| 示例文件定名 `docker.env.example`、`.gitignore` 零改动 | `git check-ignore` rc≠0 | 符合（技术单 §3.6 的 `!.env.docker.example` 已被蓝图取代，未执行） |
| 贯穿契约单源（服务名/8000/卷名/8080）写进 `memory.md` | 三处字符串对账 | 符合 |

**重复实现风险逐条**：健康探针两份（Dockerfile `HEALTHCHECK` vs compose `healthcheck`）逐字相同、仅 3 个参数不同 → 脚本核对通过；两份代理路由表（vite :5173 / nginx :80）前缀集合一致（`/api`、`/health`）；示例配置不复制 `AI_LMSTUDIO_*` 清单（仅引用 `backend/.env.example`）；端口 8000 六处一致；「默认供应商」判定分居 compose `command` 与 `config.resolve_ai` 两处 → 三档行为矩阵实测一致，优先级已写入 `memory.md`。**无重复实现漂移、无应抽未抽的抽象。**

## 4. 缺陷表

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| P3-1 | P3 | 文档（memory.md 契约单源） | 打开 `docs/teamflow/memory.md` 的「容器化交付约定」 | 与交付实际一致：示例名 `docker.env.example`，`.gitignore` 零改动 | 仍写「`.gitignore` 需追加 `!.env.docker.example`」，指向一个刻意未创建的旧名 | 架构蓝图「示例文件必须叫 docker.env.example」 | `grep -c "env.docker.example" docs/teamflow/memory.md` | 下一需求订正后输出 `0`；当前为 `1`（DEPLOY §7 已记录该差异，白名单外故本轮不改） |
| P3-2 | P3 | 文档（DEPLOY 运维面） | 读 `DEPLOY.md` §2/§6 | 给出「需要看 /docs 或 Postman 直连后端」的调试配方（蓝图要求「写进 DEPLOY.md、不默认开」） | 只说明 backend 仅内网、不发布端口，未给临时 `docker compose run -p 8000:8000` 的调试命令 | 架构蓝图 §DEPLOY「调试直连方式写进 DEPLOY.md」 | `grep -cE "8000:8000" docs/teamflow/20261101-r10-docker-compose-deploy/DEPLOY.md` | 补一小节后可照抄命令；当前输出 `0` |

**未发现 P0/P1/P2 缺陷。** 另：`ARCHITECTURE.md:279`「Docker 打包 未做」与交付矛盾，但属白名单外、且 DEPLOY §7 已显式记录差异，计入 P3-1 同一类文档口径，不单独计缺陷。

## 5. 人工补测清单（环境限制，非交付缺陷）

| 项 | 验收标准 | 方法/工具 |
|---|---|---|
| 8080 页面视觉与交互（四步闭环点选） | 首页/画像/面试/报告在 nginx 托管下与 `:5173` 一致，窄屏无横滚 | 本机 Chrome 打开 `http://127.0.0.1:8080`（沙箱禁浏览器启动，无法自动截图） |
| 1300s 长请求超时（本地模型档 >60s） | 单次画像 200 而非 504 | 本机 LM Studio + `AI_PROVIDER=lmstudio`，按 DEPLOY §4 跑一次画像；工具：Chrome + `docker compose logs -f backend` |
| Linux/WSL 下 `host.docker.internal` | lmstudio 档可连宿主模型 | Linux 主机加 `extra_hosts`（DEPLOY §4 有注释示例），实机验证 |
| 备份→恢复（含 `chown` 节点） | 恢复后 backend 可写卷、历史数据可见 | 按 DEPLOY §5 在真实机器执行一次 `cp` + `chown` |

## 6. 复现命令与退出码

| 命令 | 结果 |
|---|---|
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_r10_deploy.py --keep-up` | exit 0 · 70/70 PASS |
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_http.py` | exit 0 · 38/38 PASS |
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_ops.py` | exit 0 · 22/22 PASS |
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_derive.py` | exit 0 · 4/4 PASS（3 档 + 静态禁令） |
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_surface.py` | exit 0 · 33/33 PASS |
| `python -X utf8 logs/teamflow/tf-mvxrcwem-4rzaox/scripts/check_qa_r10_interface.py` | exit 0 · 20/20 PASS |
| `cd backend && python -m pytest -p no:cacheprovider --tb=no` | exit 0 · 348 passed, 1 skipped |
| `cd frontend && npm run typecheck && npm run lint && npm test && npm run build` | exit 0 · 0 / 0err 28warn / 109 passed / built 92 modules |
| `cd backend && python -m ruff check app tests` | exit 1 · `No module named ruff`（环境缺失，非交付缺陷） |
| `docker compose ps` / `curl -sS http://127.0.0.1:8080/health` | backend `healthy` / `{"status":"ok","ai_configured":true,"ai_provider":"legacy","ai_model":"deepseek-chat"}` |

> QA 侧首轮 6 次「假红」均为我自己的探针缺陷（`dict()` 合并重复的 `Cache-Control` 头、urllib 默认不发 `Accept-Encoding`、把注释当 `environment` 契约、JSON 数组形态的 `CMD`、`location` 前缀带斜杠、compose `config` 带解析会打印 Key），逐条修正后全绿，**交付文件一行未改**。

## 7. 结论

**可验收。** 交付以 `docker compose up -d --build` 一条命令起两容器：nginx 同源反代承载全部前端流量与 `/api`、`/health`，后端非 root 只在内网、SQLite 落命名卷且重建保数据；真实 Key 全链路（上传→画像→12 轮面试→报告）经浏览器入口跑通；零 Key 进入镜像/日志；门禁只增不减（pytest 348、vitest 109、typecheck 0、lint 0 error）。两条 P3 均为白名单外文档口径，不阻塞验收。
