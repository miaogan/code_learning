# QA 复验报告（round 2）· dev-skill-coach 0.1.0

- 需求夹：`docs/teamflow/20261031-r1-dev-skill-coach/`
- 分支 / 基线：`feat/dev-skill-coach`，基线 `32487b4`（工作区未提交，QA 不改交付代码）
- 复验日期：2026-10-31
- 本轮性质：**对 round-1 的 4 条 P2/P3（D-1 ~ D-4）做复验**，不是新一轮全量测试
- 结论：**验收就绪（可验收）**。round-1 的 4 条缺陷 **全部 CLOSED**（逐条按原 Check command 复跑通过）；本轮新增 3 条 P3 观察，**无 P0/P1/P2 未修复项**

## 1. 范围与环境

被测对象：四步闭环 Web 应用（`backend/` FastAPI + SQLite，`frontend/` React18+Vite5+TS strict），AC-1 ~ AC-10。

本轮做法（按复验策略）：**先原样复跑 logs 目录里全部既有检查器**（本需求的回归契约），再只对 round-1 未覆盖的**新表面**补探针。

环境限制（**非交付缺陷**，逐条记录原因）：
1. **浏览器不可启动**：沙箱受限令牌下 Chromium crashpad 需 `PROCESS_ALL_ACCESS` 自进程权限被拒 ⇒ 视觉/动效走人工补测。
2. **vitest / vite build 不可执行**：`npm test`、`npm run build` 均 `Error: spawn EPERM`（esbuild 服务进程被沙箱拒绝）。`typecheck`（tsc）与 `lint`（eslint）可执行并通过。工作区存在 `frontend/dist/` 旧产物（gitignore 已覆盖，不进提交面）。
3. **`ruff` 未安装**：`No module named ruff`（`backend/requirements.txt` 已声明 pytest 等，ruff 属开发机/CI 工具）。
4. **`pypdf` / `python-docx` 未安装**：AC-1 的 PDF/DOCX **正常路径**无法在本机跑通（缺依赖的降级路径已验证，见 §2 在线探针）。

## 2. 回归检查器全量复跑（逐条原样计数）

| 检查器 | 本轮回跑结果 | 关键数字 |
|---|---|---|
| `check_t14_delivery_e2e.py`（四步闭环 E2E） | **PASS** | `RESULT 50/50 passed, 0 failed`；终态面试 10 题均分 6.5、笔试 10 题（客观 8）`total=100.0`、报告 4 条短板证据命中真题、markdown 2414 字节同源、新会话可读 |
| `check_qa_contract.py`（接口一致性） | **PASS** | `RESULT 9/9 passed, 0 failed`（routes 8 路径 / 6 方法对 / fields 23 对 / sql-exit / keyleak / timeouts / ai-contract / repro / tokens） |
| `check_qa_ac1_upload_probe.py`（AC-1 在线边界） | **PASS** | `RESULT 7/7 passed, 0 failed`（需真服务，见 §3 启动方式） |
| `check_profile_chain.py`（AC-2） | **PASS** | 5 组断言全 PASS（引用上限截断仍可溯源、终态维度保留、未知 id 404） |
| `check_interview_chain.py`（AC-3） | **PASS** | `checks: 80, passed: 80, failed: 0`（本轮**扩展**该检查器，见 §4） |
| `check_exam_chain.py`（AC-4） | **PASS** | `41 passed, 0 failed` |
| `check_report_chain.py`（AC-5/AC-6/AC-9） | **PASS** | `RESULT: ALL PASSED (86 assertions)` |
| `check_history_chain.py`（AC-10） | **PASS** | 3 组 OK（服务层投影 / 端点 200·422 envelope / 全 running 窗口压力），`[real app]` |
| `check_seed_questions.py`（题库） | **PASS** | `断言: 1130 次，失败: 0`；各方向 12 题 / 挑战 1（8.3% ≤20%） |
| `check_t0_base.py` / `check_t0_contract.py` / `check_t7_frontend_infra.py` | **PASS** | 均 `all green` / `全部通过`（契约与前端基础设施自检） |
| `check_t8_profile_logic.mjs`（AC-2 页逻辑） | **PASS** | `TOTAL 53/53`；`dimensionsFilled:5, sourceQuotes:3, failureKeptData:true` |
| `check_t8_profile_page.mjs` | **PASS** | `TOTAL 88/88` |
| `check_t9_interview_page.mjs`（AC-3 页） | **PASS** | `168/168` |
| `check_t12_history_page.sh`（AC-10 页） | **PASS** | `84 checks passed`（SSR 7 场景 + 静态契约） |
| `report-components-smoke.cjs`（AC-5/AC-6 组件） | **PASS** | `TOTAL 21 PASS 21 FAIL 0` |
| `check_useasync_e2e.mjs`（状态机） | **PASS** | 8 场景全过（含卸载 abort） |
| `git-closeout-check.sh`（提交面） | **PASS** | `SUMMARY pass=27 fail=0` |

工程命令：`pytest` **73 passed**（round-1 为 67，新增 6 例工程门禁）；`npm run typecheck` exit 0；`npm run lint` **0 error / 18 warning**（全为 `react-refresh/only-export-components`，为让检查器 import 纯函数而导出）。

## 3. 上一轮缺陷逐条复验（对比表，**非本轮 open 缺陷**）

> 表头用「round-2 级」，请勿按 `严重级` 解析为本轮未关闭缺陷。

| 编号 | round-1 级 | round-2 级 | 复验结论 | 检测命令（原样） | 实际输出 | 修复前 → 后（同一 sweep 的命中数） |
|---|---|---|---|---|---|---|
| D-1 | P2 架构（存储出口） | **已修复** | **CLOSED** | `cd backend && python -X utf8 ../logs/teamflow/tf-mvvyywwo-zt1b2q/scripts/check_qa_contract.py --only=sql-exit` | `PASS sql-exit:裸 SQL 只出现在 repository.py / db.py  (唯一 SQL 出口成立)`，exit 0 | `INSERT INTO documents` 直写点 **1 → 0**；`insert_document` 调用方 **0（死代码）→ 1**（`routers/resume.py:40`）；mime 漂移已消除，在线上传落库实测 `mime='text/plain'`（真实 content_type，非写死 `application/octet-stream`） |
| D-2 | P2 架构（AI 契约） | **已修复** | **CLOSED** | `cd backend && python -X utf8 ../logs/teamflow/tf-mvvyywwo-zt1b2q/scripts/check_qa_contract.py --only=ai-contract` | `PASS ai-contract:AIClient.complete_model 接受 timeout_s（TECHNICAL §5） (parameters=['self','system','user','model_cls','timeout_s'])`，exit 0 | `timeout_s` 形参 **0 → 1**（keyword-only）；`inspect.signature` 反射兜底 **1 → 0**；`interview.py:225` 直传 `timeout_s=SCORING_TIMEOUT_S(14.0)` |
| D-3 | P2 工程/CI 可复现 | **已修复** | **CLOSED** | `cd backend && python -X utf8 ../logs/teamflow/tf-mvvyywwo-zt1b2q/scripts/check_qa_contract.py --only=repro` | `PASS repro:frontend/package-lock.json 存在（npm ci 可复现） (lockfile 就位)`，exit 0 | lockfile 缺失 → `frontend/package-lock.json` 131,877 字节，`dependencies`/`devDependencies` 与 `package.json` 同步，条目带 `resolved`+`integrity`，CI 以 lockfile 为缓存键 |
| D-4 | P3 架构（样式约定） | **已修复** | **CLOSED** | `cd backend && python -X utf8 ../logs/teamflow/tf-mvvyywwo-zt1b2q/scripts/check_qa_contract.py --only=tokens` | `PASS tokens:非 tokens.css 的文件无裸色值（AGENTS §4） (全部走 var(--token))`，exit 0 | 非 tokens.css 裸色值 **23 → 0**（`base.css:0`）；TSX 内联样式亦无裸色值 |

**修复质量核查**：修复并非只改到「检查器过」，而是同时新增了常驻回归门禁 `backend/tests/test_engineering_gates.py`（6 例，AST 级断言：全 `app/` 仅 `repository.py`/`db.py` 可执行 SQL；`complete_model` 必须有 keyword-only `timeout_s` 且 `interview` 源码直接传参、不许再用签名反射；lockfile 存在且条目完整性齐备；CI 使用 `npm ci`；非 tokens.css 无裸色值）。断言为真实 AST/源码/AST 检查，**非空壳**（改回旧写法即失败）。

## 4. 本轮新增表面（round-1 未覆盖的部分）+ 新发现

round-1 的「只验签名、不验行为」缺口：D-2 修复删掉了服务层 `asyncio.wait_for` 兜底分支后，**「客户端超时 → 503 `AI_UNAVAILABLE` + retryable」这条映射（`ai.py:79-89`）失去了行为级断言**（旧断言只活在已删除的反射分支里）。这正是 AC-3「单题 ≤15s」的唯一保障路径，故本轮补齐：

1. **扩展**（未重建）`logs/.../scripts/check_interview_chain.py`：其 case 6 原为「客户端不支持 `timeout_s`」的过期场景，改为三段——(a) 服务层确实把 `SCORING_TIMEOUT_S=14.0`（≤15s）交给客户端并正常出分 200；(b) **真实 `AIClient`** + 假 httpx（`post` 抛 `httpx.TimeoutException`）→ 必须得到 `AppError(code=AI_UNAVAILABLE, status=503, retryable=True)`，不抛裸 `TimeoutError`；(c) 该错误经路由后仍是 503 中文 envelope，且**不写半成品分数**（`score=None`、`status=running`、`answered_count=0`）。结果 `80/80`。
2. **跨模块调用点静态解析**（无需运行时）：`repository.py` 18 个函数 ↔ `app/` 内全部 `repository.xxx()` 调用点 **0 处缺失**；`complete_model` 4 个调用点（`diagnosis.py:437`、`interview.py:154/225`、`profile.py:111`）与 keyword-only `timeout_s` 签名 **全部匹配**。
3. **上传入库真实 mime 落库**：在线 TXT 上传后读 `documents` 表 → `mime='text/plain'`、正文为正确中文（`教育经历`/`计算机科学与技术`，非乱码），证明 D-1 走的 `repository.insert_document(mime=...)` 真实链路可用（非仅静态替换）。
4. **在线探针**（真 uvicorn 127.0.0.1:8000 + 真 SQLite，零网络 AI）：`/health` 200 `{"status":"ok","ai_configured":false}`；`/api/courses` 200；`/api/history?limit=10` 200；`POST /api/resumes/no-such/profile` 404 中文 `NOT_FOUND`；`GET /api/profiles/latest` 404 中文 `还没有画像，请先上传简历`；超 10MB 413、不支持类型 415、坏 PDF 500（缺依赖提示）均为中文 envelope。

### 本轮 open 缺陷表

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| Q-1 | P3 | 架构（入参校验唯一出口） | 1) `grep -n "limit_bytes" backend/app/routers/resume.py`；2) `grep -n "limit_bytes" backend/app/services/parser.py` | 上传大小上限与 `FILE_TOO_LARGE` 文案只由一处产出（`parser.py`），路由层不重复 | 两处各算一次 `settings.max_upload_mb * 1024 * 1024`、各写一遍「文件超过 N MB，请压缩或分卷」（`resume.py:22-28` 与 `parser.py:50-56`），文案改动易漂移 | AC-1 | `cd backend && grep -c "limit_bytes" app/routers/resume.py app/services/parser.py` | 仅 `parser.py` 命中（`resume.py:0`），上限与文案单一出处；`pytest` 与 AC-1 7/7 仍全绿 |
| Q-2 | P3 | 工程约定（错误文案语言） | `curl -sS -X POST -H "Content-Type: application/json" -d "{\"x\":1}" -w "\nrc=%{http_code}\n" http://127.0.0.1:8000/api/profiles/generate`（方法不匹配的框架级错误） | 错误 envelope 的 `message` 一律中文（AGENTS §4） | 框架级 405 返回 `{"error":{"code":"HTTP_ERROR","message":"Method Not Allowed","retryable":false}}`，message 为英文；业务错误（404/413/415/500/502/503）均为中文 | 无直接 AC（工程约定） | 同上 curl | 405 的 `message` 为中文（如「请求方法不被允许」），业务错误保持中文；`check_qa_ac1_upload_probe.py` 仍 7/7 |
| Q-3 | P3 | 工程/测试环境 | `grep -n ".tmp" .gitignore`；`ls -d backend/tests/.tmp` | 测试临时库目录被显式排除，避免未来非 `*.db` 产物进提交面 | `backend/tests/.tmp/` 存在（T13 已建议忽略），`.gitignore` 无 `.tmp/` 规则；当前仅因「空目录不被 Git 跟踪 + `*.db` 已忽略」而未污染提交面 | 无直接 AC（提交面卫生） | `grep -n ".tmp" .gitignore` | 命中 `backend/tests/.tmp/` 规则；`git status --porcelain=v1 -uall` 中仍无 `.tmp` 项 |

> 三条均为 P3 观察项，按规则**不阻断验收**；无 P0/P1/P2。

## 5. 人工补测清单（环境限制，非交付缺陷）

| 项 | 验收标准 | 方法 / 工具 |
|---|---|---|
| 视觉与动效走查 | 深色技术感（tokens 已确认 `--bg-canvas:#0d1117`）、卡片层级、hover/pressed/focus、窄屏 <1024 收横向步骤条 | 真实浏览器 `npm run dev` 后逐页走查（静态断言已覆盖焦点环/disabled/空态/加载态） |
| 前端构建与单测 | `npm ci && npm test && npm run build` 全绿并产出 `dist/` | 可 spawn 子进程的开发机 / CI（本沙箱 `spawn EPERM`） |
| 真实 AI 全链路计时（AC-1 ≤30s / AC-3 单题 ≤15s / AC-7 ≤5 分钟 / AC-4 10s 出分） | 配真实 `AI_API_KEY` 后一次完整闭环计时 | 真实 Key + 秒表 / 浏览器开发者工具 |
| PDF / DOCX 真实解析（AC-1） | 上传含文本层的 PDF 与 DOCX，≤30s 返回正文与章节数 | `pip install -r backend/requirements.txt`（pypdf / python-docx）后上传真实文件 |
| 刷新持久化（AC-7） | 浏览器刷新后画像 / 记录 / 最新报告仍在 | 真实浏览器 + 同一 SQLite（E2E 已用「新会话」等价覆盖） |
| 屏幕阅读器 / safe-area / 多触点 | a11y 语义与移动端安全区正常 | VoiceOver / NVDA、真机 |

## 6. 提交面卫生（0c）

`git status --porcelain=v1 -uall` 共 **96 项**：无 `node_modules/`、`dist/`、`.pnpm-store/`、`__pycache__/`、`.pytest_cache/`、`*.db`、`.env`；
`git check-ignore -v frontend/node_modules backend/app/__pycache__ logs/teamflow/tf-mvvyywwo-zt1b2q` 三条均命中 `.gitignore`；
`frontend/package-lock.json` 出现在候选（**应提交**，D-3 的修复物）；`.env.example` 允许提交。**未发现垃圾文件进提交面。**

## 7. 结论

- **验收就绪：是。** round-1 的 D-1 ~ D-4 **全部 CLOSED**（逐条按原检测命令复跑通过，且以新增 6 例工程门禁常驻防回归）。
- 回归面：全部既有回归检查器 **19 个**（另有 scripts/ 下一次���迁移/救援 helper，不属回归契约）复跑全绿 + 5 条工程命令全绿（E2E 50/50、契约 9/9、AC-1 在线 7/7、pytest 73、typecheck 0 错、lint 0 error）。
- 本轮新增行为级证据：客户端超时 → 503 中文 envelope 且不写半成品（AC-3 唯一保障路径），上传 mime 真实落库（D-1 真实链路）。
- 缺陷：**无 P0 / P1 / P2**；新增 3 条 P3 观察（Q-1 上限校验重复、Q-2 框架级 405 英文文案、Q-3 `.tmp` 未忽略），建议下一迭代收敛。
- 未验证项全部登记在 §5（浏览器不可用、vitest/vite build 不可 spawn、ruff 未装、PDF/DOCX 依赖未装），均为**环境限制**。
